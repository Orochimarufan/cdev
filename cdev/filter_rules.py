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
Rules that cdevd applies to decide whether it should forward an event.
"""

from . import rules


class Context(rules.Context):
    """
    A rule execution context
    """
    __slots__ = ("result", "cgroups", "forward", "source", "emit")

    def __init__(self, device, action, source):
        super().__init__(device, action)
        self.source = source
        self.result = None
        self.cgroups = None
        self.forward = {"ENV", "DEVLINKS"}
        self.emit = None

    def update_result(self, value):
        """
        Set the result, but continue
        """
        self.result = value

    def set_result(self, value):
        """
        Set the result and stop processing
        """
        self.result = value
        self.done = True


class Target(rules._Assignment):
    """
    Specifies the rule result
    """
    __slots__ = ()

    def assign(self, context):
        """ TARGET= """
        context.set_result(self.value)

    def extend(self, context):
        """ TARGET+= """
        context.update_result(self.value)

    @classmethod
    def create_value(cls, value):
        if value.lower() == "allow":
            return True
        elif value.lower() == "deny":
            return False
        else:
            raise SyntaxError("Unknown TARGET: %s" % value)


class CGroups(rules._Assignment):
    """
    Make cdev apply the correct device rules to the control group.
    """
    __slots__ = ()

    def __repr__(self):
        return "CGroups(%s)" % self.value

    def assign(self, context):
        """ CGROUPS= """
        context.cgroups=self.value

    @classmethod
    def create_value(cls, value):
        if value.lower() not in ("lxc",):
            raise SyntaxError("Unknown value for CGROUPS: %s" % value)
        return value.lower()


class ForwardAssignment(rules._SetAssignment):
    """
    Forward certain things:
        - ENV: the udev environment
        - TAGS: the udev tags
    """

    __slots__ = ()

    def get_set(self, context):
        return context.forward

    @classmethod
    def create_value(cls, value):
        if value.lower() not in ("env","tags"):
            raise SyntaxError("Unknown value for FORWARD: %s" % value)
        return value.upper()


class SourceCondition(rules._Condition):
    """
    Should be either sys, udev or kernel.

    sys: generated from walking sys (boot/shutdown)
    udev: from UDEV_MONITOR_UDEV
    kernel: from UDEV_MONITOR_KERNEL
    rule: from a ACTION+= rule [Not Implemented.]
    """
    __slots__ = ()

    def __call__(self, context):
        return self.operation(context.source, self.rvalue)


class ActionAssignment(rules._Assignment):
    """
    Emit an additional event, with the same properties but different actions.

    Note that although it uses +=, in the current implementation, only one additional event can be generated.
    """

    def extend(self, context):
        print("ACTION")
        context.emit = self.value

    @classmethod
    def create(cls, name, arg, op, value):
        what = None
        options = set()
        if arg:
            if "::" in arg:
                opt_str, what = arg.split("::", 1)
                options = set(x.lower() for x in opt_str.split(":"))
            else:
                what = arg
        # Arg is optional.
        return cls(op, (what, value, options))


# -----------------------------------------------------------------------------
cdev_env = {}

class CENV(rules._ParameterizedSimpleAssignment):
    __slots__ = ()

    def assign(self, context):
        id = context.device.get_id_filename()
        if not id:
            return
        if id not in cdev_env:
            cdev_env[id] = {}
        cdev_env[id][self.parameter] = self.value

class CENVCondition(rules._GeneralizedCondition):
    __slots__ = ()

    def lvalue(self, device):
        id = device.get_id_filename()
        if not id:
            return
        if id not in cdev_env:
            return
        if self.lvalue_source not in cdev_env[id]:
            return
        return cdev_env[id][self.lvalue_source]

class CENVSCondition(rules._HierarchyCondition, CENVCondition):
    __slots__ = ()

def cenv_remove(device):
    if device.get_id_filename() in cdev_env:
        del cdev_env[device.get_id_filename()]


# -----------------------------------------------------------------------------
# Collect Conditions into rules and rulesets

class RulesPreset(rules.RulesPreset):
    conditions = dict(rules.RulesPreset.conditions)
    conditions.update({
        "CENV": CENVCondition,
        "CENVS": CENVSCondition,

        "SOURCE": SourceCondition,
    })

    assignments = dict(rules.RulesPreset.assignments)
    assignments.update({
        "TARGET": Target,
        "CGROUP": CGroups,
        "CENV": CENV,
        "FORWARD": ForwardAssignment,
        "ACTION": ActionAssignment,
    })
