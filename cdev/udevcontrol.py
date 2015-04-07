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
Talk to udevadm on the udev control socket
"""

import os
import errno
import asyncio
import logging
from . import async
from . import struct
from . import socket
from .device import RUNTIME_PATH

logger = logging.getLogger(__name__)

# See systemd/src/udev/udev-ctrl.c

# define VERSION
# tested against:
UDEV_VERSION = b"213"

# enum udev_ctrl_msg_type
UDEV_CTRL_UNKNOWN = 0
UDEV_CTRL_SET_LOG_LEVEL = 1
UDEV_CTRL_STOP_EXEC_QUEUE = 2
UDEV_CTRL_START_EXEC_QUEUE = 3
UDEV_CTRL_RELOAD = 4
UDEV_CTRL_SET_ENV = 5
UDEV_CTRL_SET_CHILDREN_MAX = 6
UDEV_CTRL_PING = 7
UDEV_CTRL_EXIT = 8

# define UDEV_CTRL_MAGIC
UDEV_CTRL_MAGIC = 0xdead1dea

# struct udev_ctrl_msg_wire
class UdevControlHeader(struct.Struct):
    format = "@16sII"
    names = "version", "magic", "type"

    @classmethod
    def new(cls):
        return cls(b"udev-" + UDEV_VERSION, UDEV_CTRL_MAGIC, 0)


class UdevControlMessage:
    __slots__ = "header", "conn", "data"

    _intval_t = struct.struct.Struct("@I")

    def __init__(self, *, header=None, conn=None, data=b'DEAD'):
        if header is not None:
            self.header = header
        else:
            self.header = UdevControlHeader.new()

        self.data = data
        self.conn = conn

    def __getattr__(self, name):
        if name in self.header.names:
            return getattr(self.header, name)
        raise AttributeError("UdevControlMessage doesn't have an attribute called %s" % name)

    def __setattr__(self, name, value):
        if name in self.__slots__:
            return super().__setattr__(name, value)
        elif name in self.header.names:
            return setattr(self.header, name, value)
        raise AttributeError("UdevControlMessage doesn't have an attribute called %s" % name)

    # Emulate the union
    @property
    def intval(self):
        return self._intval_t.unpack(self.data)
    @intval.setter
    def intval(self, value):
        self.data = self._intval_t.pack(value)

    @property
    def buf(self):
        """
        NOTE: returns with any trailing nullbytes
        """
        return self.data
    @buf.setter
    def buf(self, value):
        self.data = value[:256]

    def set_data(self, data):
        if isinstance(data, int):
            self.intval = data
        elif isinstance(data, bytes):
            self.buf = data
        else:
            raise ValueError("Udev control message data must be bytes or int, not %s" % type(data).__name__)

    # parse and pack
    def pack(self):
        return self.header.pack() + self.data

    @classmethod
    def parse(cls, buffer, offset=0, *, conn=None):
        header = UdevControlHeader.unpack_from(buffer, offset)
        data = buffer[offset+header.size:offset+header.size+256]
        return cls(header=header, data=data, conn=conn)

    size = UdevControlHeader.size + 256


# struct udev_ctrl_connection
class UdevControlConnection:
    def __init__(self, ctrl, sock):
        self.ctrl = ctrl
        self.sock = sock

        sock.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)

    @asyncio.coroutine
    def recv(self):
        data, ancdata, flags, addr = (yield from async.sock_recvmsg(self.sock, UdevControlMessage.size, socket.CMSG_SPACE(socket.ucred.size)))

        #if not ancdata or ancdata[0][1] != socket.SCM_CREDENTIALS:
        #    logger.error("no sender credentials received, message ignored")
        #    return None

        #cred = socket.ucred.unpack(ancdata[0][2])
        #if cred.uid > 0:
        #    logger.error("sender uid=%i, message ignored" % cred.uid)
        #    return None

        return UdevControlMessage.parse(data, conn=self)

    @asyncio.coroutine
    def run(self):
        while True:
            try:
                msg = (yield from self.recv())
            except:
                logger.exception("Could not receive control message")
                self.sock.close()
                return

            if msg is not None:
                self.ctrl.handle_msg(msg)


# struct udev_ctrl
class UdevControl:
    """
    Must be subclassed with an implementation of handle_msg(msg: UdevControlMessage)

    call start() to create an asyncio Task.
    """
    def __init__(self):
        self.sock = None
        self.saddr = None
        self.bound = False
        self.cleanup_socket = False
        self.connected = False

        self.task = None
        self.result = None

    @classmethod
    def new_from_fd(cls, fd: int):
        self = cls()

        if fd < 0:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET|socket.SOCK_CLOEXEC|socket.SOCK_NONBLOCK, 0)
        else:
            self.sock = socket.fromfd(fd, socket.AF_UNIX, socket.SOCK_SEQPACKET|socket.SOCK_CLOEXEC|socket.SOCK_NONBLOCK)
            self.bound = True

        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)

        self.saddr = os.path.join(RUNTIME_PATH, "control")

        return self

    @classmethod
    def new(cls):
        return cls.new_from_fd(-1)

    def enable_receiving(self):
        if not self.bound:
            try:
                self.sock.bind(self.saddr)
            except OSError as e:
                if e.errno == errno.EADDRINUSE:
                    os.unlink(self.saddr)
                    self.sock.bind(self.saddr)

            self.sock.listen(1)

            self.bound = True
            self.cleanup_socket = True

    def get_fd(self):
        return self.sock.fileno

    @asyncio.coroutine
    def accept(self):
        sock, addr = (yield from asyncio.get_event_loop().sock_accept(self.sock))

        cred = sock.getpeercred()
        if cred.uid > 0:
            logger.error("sender uid=%i, message ignored" % cred.uid)

        return UdevControlConnection(self, sock)

    @asyncio.coroutine
    def run(self):
        self.enable_receiving()

        while self.result is None:
            conn = (yield from self.accept())

            if conn is not None:
                asyncio.async(conn.run())

        if self.cleanup_socket:
            self.sock.close()
        return self.result

    def start(self):
        self.task = asyncio.Task(self.run())
        return self.task
