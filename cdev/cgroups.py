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
Interact with container managers to modify the control group
"""

import logging

logger = logging.getLogger(__name__)

# Define a convenience class :)
class ControlGroupManager:
    registry = {}

    def __init__(self, name):
        self.name = name
        self.registry[name] = self

    def __call__(self, func):
        self.func = func
        return func # Even though it's not really useful.

    def allow(self, container_name, device):
        self.func(container_name, device, True)

    def deny(self, container_name, device):
        self.func(container_name, device, False)

    @classmethod
    def get(cls, name):
        if name in cls.registry:
            return cls.registry[name]

# Add the managers
try:
    import lxc
except ImportError:
    pass
else:
    @ControlGroupManager("lxc")
    def lxc_cgroup_update(container_name, device, allow):
        container = lxc.Container(container_name)

        major, minor = device.get_major_minor()
        if not major:
            return

        type = 'b' if device.get_subsystem() == "block" else 'c'
        perms = "rwm" if allow else "rm"
        cgroup_subsystem = "devices.allow" if allow else "devices.deny"

        logger.info("Adding cgroups rule to lxc container %s: %s = %s%i:%i %s" % (container_name, cgroup_subsystem, type, major, minor, perms))
        container.set_cgroup_item(cgroup_subsystem, "%s %i:%i %s" % (type, major, minor, perms))
