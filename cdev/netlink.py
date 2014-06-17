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
Work with the udev monitor netlink messages
"""

import os
import collections
import logging
from . import device
from . import murmurhash2
from . import struct
from . import socket

logger = logging.getLogger(__name__)

# udev NETLINK multicast groups (from libudev/libudev-monitor.c)
UDEV_NETLINK_NONE = 0
UDEV_NETLINK_KERNEL = 1
UDEV_NETLINK_UDEV = 2
UDEV_NETLINK_CDEV = 4 #only for testing.


def open_netlink(protocol, mcast_groups):
    """
    Open an AF_NETLINK socket on \c protocol and listen to \c mcast_groups
    """
    sock = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, protocol)
    sock.bind((0, mcast_groups)) # The kernel assigns the pid.
    return sock


# -----------------------------------------------------------------------------
# libudev NETLINK wire protocol

# libudev NETLINK header info
udev_netlink_header_prefix = b"libudev\0"
udev_netlink_header_magic = 0xfeedcafe


class UdevNetlinkHeader(struct.MixStruct):
    """
    The libudev message header
    """
    __slots__ = ()

    formats = "!8sI", "=I2I", "!4I" # Note to udev devs: WHY IN HELL DO YOU MIX BYTEORDERS!?!
    names = "prefix", "magic", "header_size", "properties_off", "properties_len", "filter_subsystem_hash", "filter_devtype_hash", "filter_tag_bloom_hi", "filter_tag_bloom_lo"

    @classmethod
    def new(cls):
        return cls((udev_netlink_header_prefix, udev_netlink_header_magic, cls.size, cls.size, 0, 0, 0, 0, 0))


class UdevNetlinkMessage:
    """
    A libudev message.

    CAUTION: the header's properties_len field isn't meaningful!
             It's only used for packing to and unpacking from bytestrings.

    ACTION is stored separately so we can share the properties dict with the device object.
    """
    __slots__ = ("header", "properties", "action", "original_buffer")

    def __init__(self, *, header=None, props=None, action=None):
        if header is not None:
            self.header = header
        else:
            self.header = UdevNetlinkHeader.new()

        if props is not None:
            self.properties = props
        else:
            self.properties = {}

        if action is not None:
            self.action = action
        elif "ACTION" in props:
            self.action = props["ACTION"]
        else:
            self.action = None

        self.original_buffer = None

    def __getattr__(self, name):
        if name in self.header.names:
            return getattr(self.header, name)
        raise AttributeError("UdevNetlinkMessage doesn't have an attribute called %s" % name)

    def __getitem__(self, key):
        if key == "ACTION":
            return self.action
        return self.properties[key]

    def make_device(self):
        return device.Device.from_props(self.properties, from_uevent=True)

    def get_action(self):
        return self.action

    def clone(self, *, props=None, action=None):
        """
        shallowly copy the message.

        pass props to override the properties

        CAUTION: Don't use this to create a message for a different device!
                 The header fields contain hashed information about the device!
                 Or, to put it straight: don't change SUBSYSTEM or DEVTYPE.

        the original_buffer is NOT cloned.
        """
        return type(self)(header=self.header, props=self.properties if props is None else props, action=self.action if action is None else action)

    # Pack it into a bytestring
    def pack(self):
        # TODO: don't run a check on everything. think of a better way.
        props_buffer = b"ACTION=" + self.action.encode() + b'\0'
        props_buffer += b"".join(("%s=%s\0" % i).encode() for i in self.properties.items() if i[0] != "ACTION")
        self.header.properties_len = len(props_buffer)
        return self.header.pack() + props_buffer

    # Create messages
    @classmethod
    def from_device_and_action(cls, device, action, *, include_env=True):
        if include_env:
            props = device.get_props_and_env()
        else:
            props = device.get_properties()
        self = cls(props=props, action=action)

        self.fill_hashes_from_device(device)
        self.fill_bloom_from_device(device)

        return self

    @classmethod
    def from_props(cls, props, action=None):
        self = cls(props=props, action=action)
        self.fill_hashes_from_props(props)
        return self

    @classmethod
    def parse(cls, buffer, offset=0):
        header = UdevNetlinkHeader.unpack_from(buffer, offset)

        # Do some checks:
        if header.magic != udev_netlink_header_magic:
            logger.error("libudev netlink message wih broken magic: %x" % header.magic)
            return None

        props_buffer = buffer[offset+header.properties_off:offset+header.properties_off+header.properties_len-1] # we don't need the trailing \0, hence -1
        props = dict(prop_x.decode().split('=', 1) for prop_x in props_buffer.split(b'\0'))

        self = cls(header=header, props=props)
        self.original_buffer = buffer[offset:offset+header.header_size+header.properties_len]

        return self

    @classmethod
    def from_kernel_message(cls, kern_message):
        props = dict((prop.decode().split("=", 1) for prop in kern_message.split(b'\0')[1:-1]))
        self = cls(props=props)
        self.fill_hashes_from_props(props)
        return self

    # Fill the *_hash and *_bloom fields in the header
    def fill_hashes_from_device(self, device):
        subsystem = device.get_subsystem()
        if subsystem is not None:
            self.header.filter_subsystem_hash = murmurhash2.MurmurHash2(subsystem.encode())
        devtype = device.get_devtype()
        if devtype is not None:
            self.header.filter_devtype_hash = murmurhash2.MurmurHash2(devtype.encode())

    def fill_bloom_from_device(self, device):
        tag_bloom_bits = 0
        for tag in device.get_tags():
            tag_bloom_bits |= murmurhash2.util_string_bloom64(tag.encode())
        self.header.filter_tag_bloom_hi = tag_bloom_bits >> 32
        self.header.filter_tag_bloom_lo = tag_bloom_bits & 0xFFFFFFFF

    def fill_hashes_from_props(self):
        if "SUBSYSTEM" in self.properties:
            self.header.filter_subsystem_hash = murmurhash2.MurmurHash2(self.properties["SUBSYSTEM"].encode())
        if "DEVTYPE" in self.properties:
            self.header.filter_devtype_hash = murmurhash2.MurmurHash2(self.properties["DEVTYPE"].encode())


# Handle the messages (legacy)
def udev_netlink_message_get_props(buffer, offset=0):
    """
    Parse a libudev uevent message
    """
    return UdevNetlinkMessage.parse(buffer, offset).properties

def uevent_netlink_message_get_props(buffer):
    """
    Kernel uevent messages are simple.
    """
    return dict((prop.decode().split("=", 1) for prop in buffer.split(b'\0')[1:-1])) # again, we don't want the trailing \0, we also don't need the header.

def udev_netlink_message_generic_get_props(buffer):
    """
    Decide if we have a kernel or libudev message
    """
    if buffer[:8] == udev_netlink_header_prefix:
        return udev_netlink_message_get_props(buffer)
    else:
        return uevent_netlink_message_get_props(buffer)
