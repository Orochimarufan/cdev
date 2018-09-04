#!/usr/bin/python
# cdev-udevd -- A device management/hotplug daemon for container environments.
#
# Copyright (c) 2015 Taeyeon Mori
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
Extended version of the python fnmatch module.

Recognized Patterns
===================

a|b       at the top level, either a or b
*         any character, from zero to infinite occurrences, non-greedy
+         any character, from one to infinite occurrences, non-greedy
?         any character, one occurrence, non-greedy
{a,b,...} either a or b (or ...), where they can be arbitrary sub-expressions
{a|b|...} same as {a,b,...}
[...]     character group, see rules in python's re documentation
[^...]    negative character group "all characters but..." see the python re documentation
^x        when prefixing a non-greedy operator (*+?) it makes them greedy, otherwise means "anything but x" (non-greedy)
^^x       makes second meaning of ^x greedy.
\\x       remove any special meaning from x

Note that, different from real (Bourne-)shell globing, this compiles down into a single regular expression.
    Therefore, when matching "{a,b}*" against ["a.txt", "d.txt"] you will get ["a.txt"], not ["a.txt", "b*"]
    In most cases this is the desirable outcome anyway.
"""


import re


CLOSE_NONE              = 0x000000
CLOSE_PAREN             = 0x010000
CLOSE_BRACKET           = 0x020000
CLOSE_ANYTHING_FOLLOWS  = 0x040000
CLOSE_NONGREEDY         = 0x080000

SCOPE_NONE              = 0x0000
SCOPE_NEXT              = 0x0100

STATE_NORMAL            = 0x00
STATE_ESCAPED           = 0x01
STATE_NEGATE            = 0x02
STATE_CHARACTER_GROUP   = 0x04
STATE_CHOICE_GROUP      = 0x08


class FnmatchExprParser:
    def __init__(self):
        self.regexp = ['^']
        self.state_stack = [STATE_NORMAL]

    # Access state
    @property
    def state(self) -> int:
        return self.state_stack[-1]

    def state_push(self, state: int):
        self.state_stack.append(state)

    def state_pop(self):
        state = self.state_stack.pop()

        # Close any parentheses
        if state & CLOSE_PAREN:
            self.regexp.append(')')
        if state & CLOSE_BRACKET:
            self.regexp.append(']')
        if state & CLOSE_ANYTHING_FOLLOWS:
            # a ^x expression can be followed by anything because (?!...) doesn't consume the string.
            self.regexp.append(".*")

        # Recurse for any SCOPE_NEXT items left on the stack
        if self.state & SCOPE_NEXT:
            self.state_pop()

    def state_greedy(self):
        if self.state & STATE_NEGATE:
            # we don't want the CLOSE_* to execute
            self.state_stack.pop()
        else:
            self.regexp.append('?')

        if self.state & SCOPE_NEXT:
            self.state_pop()


    # Handle one literal character
    def add_literal_character(self, c: str):
        self.regexp.append(re.escape(c))

        # If the state only applies to the next
        if self.state & SCOPE_NEXT:
            self.state_pop()

    def feed(self, c: str, column: int=None):
        state = self.state

        # Escaping characters always works
        if state & STATE_ESCAPED:
            self.regexp.append('\\' + c if c in "dDsSwWfnrtvx" else re.escape(c))
            self.state_pop()

        elif c == '\\':
            self.state_push(STATE_ESCAPED | SCOPE_NEXT)

        # Most characters loose their special meaning inside character groups.
        elif state & STATE_CHARACTER_GROUP:
            # Character groups work exactly like in the re module
            # ] doesn't have a special meaning when following [ while ^ does
            if self.regexp[-1] == "[":
                if c == '^':
                    self.regexp.append('^')
                else:
                    self.add_literal_character(c)
            else:
                if c == ']':
                    self.state_pop()
                else:
                    self.add_literal_character(c)

        # General Case, since these can be nested
        elif c == '[':
            self.state_push(STATE_CHARACTER_GROUP | CLOSE_BRACKET)
            self.regexp.append('[')

        elif c == ']':
            raise ValueError("Unbalanced brackets at column %i" % column)

        elif c == '{':
            self.state_push(STATE_CHOICE_GROUP | CLOSE_PAREN)
            self.regexp.append('(?:')

        elif c == '}':
            if state & STATE_CHOICE_GROUP:
                self.state_pop()
            else:
                raise ValueError("Unbalanced braces at column %i" % column)

        elif c == '^':
            # Since "(?!x)" doesn't consume anything of the string, "anything but x" means "(?!x).*" hence CLOSE_ANYTHING_FOLLOWS
            if state & STATE_NEGATE:
                self.state_stack.pop()
                self.state_push(STATE_NEGATE | SCOPE_NEXT | CLOSE_PAREN | CLOSE_ANYTHING_FOLLOWS)
            else:
                self.state_push(STATE_NEGATE | SCOPE_NEXT | CLOSE_PAREN | CLOSE_ANYTHING_FOLLOWS | CLOSE_NONGREEDY)
            self.regexp.append("(?!")

        elif c == '?':
            self.regexp.append(".?")
            self.state_greedy()

        elif c == '*':
            self.regexp.append(".*")
            self.state_greedy()

        elif c == '+':
            self.regexp.append(".+")
            self.state_greedy()

        elif c == ',':
            if state & STATE_CHOICE_GROUP:
                self.regexp.append('|')
            else:
                self.add_literal_character(',')

        elif c == '|':
            if state == STATE_NORMAL or state & STATE_CHOICE_GROUP:
                self.regexp.append('|')
            else:
                self.add_literal_character('|')

        else:
            # Otherwise, it's just a normal character
            self.add_literal_character(c)

    def finish(self) -> str:
        if len(self.state_stack) != 1:
            raise ValueError("Unbalanced Expression.")
        self.regexp.append('$')
        return ''.join(self.regexp)


def translate(expr: str) -> str:
    p = FnmatchExprParser()
    for i, c in enumerate(expr):
        p.feed(c, column=i)
    return p.finish()


def compile(expr: str) -> "re.Pattern":
    return re.compile(translate(expr))

def match(string: str, expr: str) -> "re.Match":
    return re.match(translate(expr), string)

