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
Helpers for working with sockets

* defines the NETLINK_* constants
* adds a ucred structure (see cdev.struct)
* adds getpeercred()
"""

from socket import *
from . import struct

# -----------------------------------------------------------------------------
# NETLINK protocol constants (from linux/netlink.h)
NETLINK_ROUTE           = 0 # Routing/device hook
NETLINK_UNUSED          = 1 # Unused number
NETLINK_USERSOCK        = 2 # Reserved for user mode socket protocols
NETLINK_FIREWALL        = 3 # Firewalling hook
NETLINK_INET_DIAG       = 4 # INET socket monitoring
NETLINK_NFLOG           = 5 # netfilter/iptables ULOG
NETLINK_XFRM            = 6 # ipsec
NETLINK_SELINUX         = 7 # SELinux event notifications
NETLINK_ISCSI           = 8 # Open-iSCSI
NETLINK_AUDIT           = 9 # auditing
NETLINK_FIB_LOOKUP      = 10
NETLINK_CONNECTOR       = 11
NETLINK_NETFILTER       = 12 # netfilter subsystem
NETLINK_IP6_FW          = 13
NETLINK_DNRTMSG         = 14 # DECnet routing messages
NETLINK_KOBJECT_UEVENT  = 15 # Kernel messages to userspace
NETLINK_GENERIC         = 16
# leave room for NETLINK_DM (DM events)
NETLINK_SCSITRANSPORT   = 18 # SCSI Transport
NETLINK_ECRYPTFS        = 19


# -----------------------------------------------------------------------------
# credentials passing with SO_PEERCRED
class ucred(struct.FrozenStruct):
    format = "iII"
    names = "pid", "uid", "gid"


def getpeercred(sock):
    peercred = sock.getsockopt(SOL_SOCKET, SO_PEERCRED, ucred.size)
    return ucred.unpack(peercred)

socket.getpeercred = getpeercred
