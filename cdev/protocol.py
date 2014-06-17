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

import struct
import pickle
import json
import logging

logger = logging.getLogger(__name__)


def _recv(sock, n):
    data = list()
    while n > 0:
        d = sock.recv(n)
        n -= len(d)
        data.append(d)
    return b"".join(data)


D_DATA = 0x0
D_STRU = 0x1
D_JSON = 0x2
D_PIKL = 0x3

def serialize_data(type, data, fmt=None):
    if type == D_DATA:
        return data
    elif type == D_STRU:
        return struct.pack("!H", len(fmt)) + bytes(fmt, "ascii") + struct.pack(fmt, *data)
    elif type == D_JSON:
        return json.dumps(data).encode()
    elif type == D_PIKL:
        return pickle.dumps(data)
    else:
        raise TypeError("Unknown serialize type: %x" % type)

def deserialize_data(type, data):
    if type == D_DATA:
        return data, None
    elif type == D_STRU:
        fmt_size = struct.unpack_from("!H", data, 0)[0]
        fmt = str(data[2:2+fmt_size], "ascii")
        return struct.unpack_from(fmt, data, 2 + fmt_size), fmt
    elif type == D_JSON:
        return json.loads(data.decode()), None
    elif type == D_PIKL:
        return pickle.loads(data), None
    else:
        raise TypeError("Cannot deserialize type %x" % type)

def unpack_header(data, offset=0):
    return struct.unpack_from("!11pBQ", data, offset)


class Message:
    def __init__(self, command, type=D_DATA, data=b'', fmt=None):
        self.command = command
        self.type = type
        self.data = data
        self.fmt = fmt

    def pack(self):
        data = serialize_data(self.type, self.data, self.fmt)
        return struct.pack("!11pBQ%ss" % len(data), self.command, self.type, len(data), data)

    def send_to(self, sock):
        sock.sendall(self.pack())

    def write_to(self, stream_writer):
        stream_writer.write(self.pack())

    @classmethod
    def recv_from(cls, sock):
        command, type, size = struct.unpack("!11pBQ", sock.recv(20))
        data, fmt = deserialize_data(type, sock.recv(size))
        return cls(command, type, data, fmt)
