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
rules for node creation
"""

from . import rules


class Context(rules.Context):
    __slots__ = ("user", "group", "mode", "modified_devices")

    def __init__(self, device, action):
        super().__init__(device, action)

        self.user = self.group = self.mode = None
        self.modified_devices = set()

    def device_modified(self, device):
        self.modified_devices.add(device)


class UserAssignment(rules._SimpleAssignment):
    __slots__ = ()

    def assign(self, context):
        context.user = self.value


class GroupAssignment(rules._SimpleAssignment):
    __slots__ = ()

    def assign(self, context):
        context.group = self.value


class ModeAssignment(rules._SimpleAssignment):
    __slots__ = ()

    def assign(self, context):
        context.mode = self.value

    @classmethod
    def create_value(cls, value):
        try:
            return int(value, 8)
        except:
            raise SyntaxError("Mode must be an octal integral number!")


class _ModifyingAssignmentMixin:
    __slots__ = ()

    def __call__(self, context):
        if not context.device.is_db_loaded:
            context.device.read_db()
        context.device_modified(context.device)
        return super().__call__(context)


class UdevEnvironmentAssignment(_ModifyingAssignmentMixin, rules._ParameterizedSimpleAssignment):
    __slots__ = ()

    def assign(self, context):
        context.device.environment[self.parameter] = self.value


class UdevTagAssignment(_ModifyingAssignmentMixin, rules._SetAssignment):
    __slots__ = ()

    def get_set(self, context):
        return context.device.tags


class UdevSymlinkAssignment(_ModifyingAssignmentMixin, rules._SetAssignment):
    __slots__ = ()

    def get_set(self, context):
        return context.device.devlinks


class RulesPreset(rules.RulesPreset):
    conditions = dict(rules.RulesPreset.conditions)
    conditions.update({
    })
    assignments = dict(rules.RulesPreset.assignments)
    assignments.update({
        "USER": UserAssignment,
        "GROUP": GroupAssignment,
        "MODE": ModeAssignment,
        "ENV": UdevEnvironmentAssignment,
        "TAG": UdevTagAssignment,
        "SYMLINK": UdevSymlinkAssignment,
    })
