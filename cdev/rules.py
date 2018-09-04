#!/usr/bin/python
# cdev -- A device management/hotplug daemon for container environments.
#
# Copyright (c) 2014 Taeyeon Mori
# All rights reserved.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

"""
Base implementation for udev-like rules
"""

import re
import operator
import os
import logging

from . import fnmatch

logger = logging.getLogger(__name__)


class Context:
    """
    A rule execution context
    """
    __slots__ = ("device", "action", "done", "goto_label", "debug")

    def __init__(self, device, action):
        self.device = device
        self.action = action

        self.done = False
        self.goto_label = None

        self.debug = False

    # Rules interface
    def goto(self, label):
        self.goto_label = label

    def end_ruleset(self):
        self.done = True

    # RuleSet flow control interface
    def begin_ruleset(self):
        """
        Reset the done state for each RuleSet
        """
        self.done = False

    def is_done(self):
        """
        Check if this ruleset is done
        """
        return self.done

    def get_clear_goto(self):
        """
        Clear and retrieve the goto label
        """
        goto = self.goto_label
        self.goto_label = None
        return goto


# -----------------------------------------------------------------------------
# Match against things
class _Condition:
    """
    A condition consists of a lvalue, an operation and a rvalue.
    The lvalue needs to be computed
    """
    __slots__ = ("operation", "rvalue")

    def __init__(self, operation, rvalue):
        if hasattr(operation, "compile"):
            rvalue = operation.compile(rvalue)

        self.operation = operation
        self.rvalue = rvalue

    def __call__(self, context):
        return self.operation(self.lvalue(context.device), self.rvalue)

    @classmethod
    def create(cls, name, arg, operation, value):
        """
        Used to create a condition from a token string.
        @sa RulesPreset
        """
        if arg:
            raise SyntaxError("Condition %s takes no argument!" % name)

        return cls(operation, value)


class _HierarchyCondition(_Condition):
    """
    Matches against the whole hierarcy.
    """
    __slots__ = ()

    def __call__(self, context):
        device = context.device
        while device is not None:
            if self.operation == match_log:
                print(device.devpath)
            if self.operation(self.lvalue(device), self.rvalue):
                return True
            device = device.get_parent()
        return False


class _GeneralizedCondition(_Condition):
    """
    Takes an additional value to compute lvalue.
    """
    __slots__ = ("lvalue_source")

    def __init__(self, source, operation, rvalue):
        super().__init__(operation, rvalue)
        self.lvalue_source = source

    def __repr__(self):
        return "%s(%r, %r, %r)" % (type(self).__name__, self.lvalue_source, self.operation, self.rvalue)

    @classmethod
    def create(cls, name, arg, operation, value):
        if not arg:
            raise SyntaxError("Condition %s expects an argument!" % name)

        return cls(arg, operation, value)


class PropertyCondition(_GeneralizedCondition):
    """
    Matches against a Device Property.
    """
    __slots__ = ()

    def lvalue(self, device):
        return device[self.lvalue_source]

    # Gerneralized by name
    @classmethod
    def create(cls, name, arg, operation, value):
        if arg:
            raise SyntaxError("Condition %s takes no argument!" % name)

        return cls(name, operation, value)

class PropertiesCondition(_HierarchyCondition, PropertyCondition):
    __slots__ = ()

    # Remove the trailing 'S'
    @classmethod
    def create(cls, name, arg, operation, value):
        if arg:
            raise SyntaxError("Condition %s takes no argument!" % name)

        name = name[:-1] if name[-1] == 'S' else name

        return cls(name, operation, value)


class AttrCondition(_GeneralizedCondition):
    """
    Matches against a device sysattr.
    """
    __slots__ = ()

    def lvalue(self, device):
        return device.get_sysattr(self.lvalue_source)

class AttrsCondition(_HierarchyCondition, AttrCondition):
    __slots__ = ()


class ActionCondition(_Condition):
    __slots__ = ()

    def __call__(self, context):
        return self.operation(context.action, self.rvalue)


# Udev stuff
class UdevEnvironmentCondition(_GeneralizedCondition):
    __slots__ = ()

    def lvalue(self, device):
        return device.get_env(self.lvalue_source)


class UdevEnvironmentsCondition(_HierarchyCondition, UdevEnvironmentCondition):
    __slots__ = ()


# -----------------------------------------------------------------------------
# Assign things
class _SimpleAssignment:
    """
    Assign something
    """
    __slots__ = ("value")

    def __init__(self, value):
        self.value = value

    def __call__(self, context):
        return self.assign(context) is None

    def __repr__(self):
        return "%s(=\"%s\")" % (type(self).__name__, self.value)

    @classmethod
    def create(cls, name, arg, operation, value):
        if operation != op_assign:
            raise SyntaxError("Can only assign (=) to %s" % name)
        if arg:
            raise SyntaxError("Assignment to %s does not take an argument" % name)
        return cls(cls.create_value(value))

    @classmethod
    def create_value(cls, value):
        return value


class _Assignment(_SimpleAssignment):
    """
    Assign something
    """
    __slots__ = ("operation")

    def __init__(self, operation, value):
        super().__init__(value)
        self.operation = operation

    def __call__(self, context):
        return self.operation(self, context) is None

    def __repr__(self):
        if self.operation == op_assign:
            op_str = "="
        elif self.operation == op_extend:
            op_str = "+="
        else:
            op_str = str(self.operation)
        return "%s(%s\"%s\")" % (type(self).__name__, op_str, self.value)

    @classmethod
    def create(cls, name, arg, operation, value):
        if arg:
            raise SyntaxError("Assignment to %s does not take an argument" % name)
        return cls(operation, cls.create_value(value))


class _SetAssignment(_Assignment):
    """
    Assign to a set:
    ="VALUE" -> clear the set and add "VALUE"
    +="VALUE" -> add "VALUE" to the set
    get_set(context) should return the set to operate on.
    """
    __slots__ = ()

    def __call__(self, context):
        set = self.get_set(context)
        if self.operation == op_assign:
            set.clear()
        if self.operation == op_subtract:
            set.discard(self.value)
        else:
            set.add(self.value)
        return True

    @classmethod
    def create(cls, name, arg, operation, value):
        if operation not in (op_assign, op_extend, op_subtract):
            raise SyntaxError("Can only replace (=), extend (+=) or subtract from (-=s) the set %s" % name)
        if arg:
            raise SyntaxError("Assignment to %s does not take an argument" % name)
        return cls(operation, cls.create_value(value))


class _ParameterizedAssignment(_Assignment):
    __slots__ = ("parameter")

    def __init__(self, parameter, *args):
        super().__init__(*args)
        self.parameter = parameter

    @classmethod
    def create(cls, name, arg, operation, value):
        if not arg:
            raise SyntaxError("Assignment to %s takes an argument" % name)
        return cls(arg, operation, cls.create_value(value))

class _ParameterizedSimpleAssignment( _SimpleAssignment):
    __slots__ = ("parameter")

    def __init__(self, parameter, *args):
        super().__init__(*args)
        self.parameter = parameter

    @classmethod
    def create(cls, name, arg, operation, value):
        if operation != op_assign:
            raise SyntaxError("Can only assign (=) to %s" % name)
        if not arg:
            raise SyntaxError("Assignment to %s takes an argument" % name)
        return cls(arg, cls.create_value(value))


class GotoAssignment(_SimpleAssignment):
    __slots__ = ()

    def assign(self, context):
        if self.value == "_EOF_":
            context.end_ruleset()
        else:
            context.goto(self.value)


class DebugAssignment(_SimpleAssignment):
    __slots__ = ()

    def assign(self, context):
        context.debug = self.value

    @classmethod
    def create_value(self, value):
        return value == "1"


# -----------------------------------------------------------------------------
# Operators
def op_assign(assignment, context):     # =
    assignment.assign(context)

def op_extend(assignment, context):     # +=
    assignment.extend(context)

def op_subtract(assignment, context):   # -=
    assignment.subtract(context)

op_equals = operator.eq                 # ===
op_doesntequal = operator.ne            # !==

def op_fnmatches(lvalue: str, rvalue: "re.Pattern") -> bool:        # ==
    return lvalue is not None and rvalue.match(lvalue) is not None
op_fnmatches.compile = fnmatch.compile

def op_doesntfnmatch(lvalue: str, rvalue: "re.Pattern") -> bool:    # !=
    return lvalue is None or rvalue.match(lvalue) is None
op_doesntfnmatch.compile = fnmatch.compile

def op_rematches(lvalue: str, rvalue: "re.Pattern") -> bool:        # ~=
    return lvalue is not None and rvalue.search(lvalue) is not None
op_rematches.compile = re.compile

def op_doesntrematch(lvalue: str, rvalue: "re.Pattern") -> bool:    # ~=
    return lvalue is None or rvalue.search(lvalue) is None
op_doesntrematch.compile = re.compile

def match_log(lvalue, rvalue):      # ?=
    res = lvalue == rvalue
    if lvalue is not None:
        logger.info("Rule Debug: %r %s %r" % (lvalue, "==" if res else "!=", rvalue))
    return res


# -----------------------------------------------------------------------------
# Collect Conditions into rules and rulesets
class Rule(list):
    __slots__ = ("fname", "lineno")

    def __init__(self, fname="<>", lineno=-1):
        self.fname = fname
        self.lineno = lineno

    def __call__(self, context):
        for cond in self:
            res = cond(context)
            assert res is not None, "Got None from condition. This is probably a bug. Return either True or False! %s" % cond
            if not res:
                if context.debug:
                    logger.debug("Rule Failed at: %r" % cond)
                break
        context.debug = False # set it for every rule separately. prevent spam.


class RuleSet(list):
    __slots__ = ("labels", "fname")

    def __init__(self, fname="<>"):
        self.labels = {}
        self.fname = fname

    def add_label(self, name, rulenr):
        self.labels[name] = rulenr

    def add_label_here(self, name):
        self.labels[name] = len(self)

    def __call__(self, context):
        context.begin_ruleset()
        rulenr = 0
        while rulenr < len(self):
            # execute rule
            rule = self[rulenr]

            rule(context)

            # check if we're done
            if context.is_done():
                break

            # handle gotos
            label = context.get_clear_goto()
            if label:
                if label in self.labels:
                    rulernr = self.labels[label]
                else:
                    logger.error("Unknown goto label '%s' at %s, line %i" % (label, rule.fname, rule.lineno))
                    return
            else:
                # next rule
                rulenr += 1


# -----------------------------------------------------------------------------
# Parsing helpers
def fill_syntax_error(se, filename, lineno, offset=0, text=None):
    se.filename = filename
    se.lineno = lineno
    se.offset = 0
    if text is not None:
        se.text = text
    elif os.path.exists(filename):
        with open(filename) as f:
            se.text = f.readlines()[se.lineno]

def make_syntax_error(msg, filename, lineno, offset=0, text=None):
    se = SyntaxError(msg)
    fill_syntax_error(se, filename, lineno, offset, text)
    return se


class RulesPreset:
    """
    Knows about all names and can parse a rules file

    static class: use it directly, not instances.
    """
    # The expression to parse one condition/assignment
    cond_expr = re.compile(r'^\s*([a-zA-Z_][a-zA-Z0-9-_]*)(?:\{([a-zA-Z_][a-zA-Z0-9-_:.;+#/]*)\})?\s*(===|!==|\?==|!=|==|~=|!~|\+=|=)\s*"([^"]*)"\s*$')

    # A mapping of all operators
    operations = {
        # assign
        "=": op_assign,
        "+=": op_extend,
        "-=": op_subtract,

        # compare
        "===": op_equals,
        "!==": op_doesntequal,

        "==": op_fnmatches,
        "!=": op_doesntfnmatch,

        "~=": op_rematches,
        "!~": op_doesntrematch,

        #"?==": match_log,
    }

    assign_operations = {op_assign, op_extend, op_subtract} # to check for misplaced operations

    # Default Conditions. Override in subclasses
    conditions = {
        "ACTION": ActionCondition,

        "ATTR": AttrCondition,
        "ATTRS": AttrsCondition,

        "ENV": UdevEnvironmentCondition,
        "ENVS": UdevEnvironmentsCondition,

        # Properties
        "KERNEL": PropertyCondition,
        "SUBSYSTEM": PropertyCondition,
        "DRIVER": PropertyCondition,

        "KERNELS": PropertiesCondition,
        "SUBSYSTEMS": PropertiesCondition,
        "DRIVERS": PropertiesCondition,
    }

    # Default assignments. Override in subclasses
    assignments = {
        "GOTO": GotoAssignment,

        "_DEBUG": DebugAssignment,
    }

    @classmethod
    def parse(self, filepath):
        """
        Parse a rules file according to available conditions and assignments
        """
        ruleset = RuleSet(filepath)

        with open(filepath, "r") as fp:
            for lineno, line in enumerate(fp):
                # Get rid of comments and empty lines
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                # Start a new rule
                rule = Rule(filepath, lineno)
                offset = 0 # character offset

                # split it into conditions
                for cond_string in line.split(","):
                    match = self.cond_expr.match(cond_string)

                    if not match:
                        raise make_syntax_error("Could not parse condition: Invalid Syntax", filepath, lineno, offset, line)

                    name, arg, op_string, value = match.groups()

                    op = self.operations[op_string]
                    cond = None

                    try:
                        if op in self.assign_operations:
                            # Assignment
                            # We need to special-case LABEL=
                            if name == "LABEL":
                                raise SyntaxError("LABEL isn't working in this version.")
                                #if op == op_assign:
                                #    ruleset.add_label_here(value)
                                #    cond = False
                                #else:
                                #    raise SyntaxError("LABEL can only be assigned (=) to.")
                            else:
                                # "Normal" assignment
                                try:
                                    assignment = self.assignments[name]
                                except KeyError:
                                    cond = self.unknown_assignment(name, arg, op, value)
                                else:
                                    cond = assignment.create(name, arg, op, value)
                        else:
                            # Condition
                            try:
                                condition = self.conditions[name]
                            except KeyError:
                                cond = self.unknown_condition(name, arg, op, value)
                            else:
                                cond = condition.create(name, arg, op, value)
                    except SyntaxError as se:
                        # Add information to exception
                        fill_syntax_error(se, filepath, lineno, offset, line)
                        raise

                    # cond should never be None
                    assert cond is not None, "Did someone forget to return from their Condition/Assignment create() (class-)method?"

                    # Add it to the rule
                    if cond is not False:
                        rule.append(cond)

                    # advance offset
                    offset += len(cond_string) + 1 # +1 for the trailing ","

                # Only add the rule if it's non-empty
                if rule:
                    ruleset.append(rule)

        return ruleset

    @classmethod
    def unknown_assignment(self, name, arg, op, value):
        if name in self.conditions:
            raise SyntaxError("Cannot assign to %s." % name)
        else:
            raise SyntaxError("Unknown name: %s" % name)

    @classmethod
    def unknown_condition(self, name, arg, op, value):
        if name in self.assignments:
            raise SyntaxError("Cannot read %s" % name)
        else:
            raise SyntaxError("Unknown name %s" % name)
