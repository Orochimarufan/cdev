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

import asyncio
import socket
import concurrent.futures
from . import protocol

def _sock_recvmsg(sock, bufsize, ancbufsize, flags, future, registered=False):
    fd = sock.fileno()
    if registered:
        asyncio.get_event_loop().remove_reader(fd)
    if future.cancelled():
        return
    try:
        data = sock.recvmsg(bufsize, ancbufsize, flags | socket.MSG_DONTWAIT)
    except (BlockingIOError, InterruptedError):
        asyncio.get_event_loop().add_reader(fd, _sock_recvmsg, sock, bufsize, ancbufsize, flags, future, True)
    except Exception as e:
        future.set_exception(e)
    else:
        future.set_result(data)

@asyncio.coroutine
def sock_recvmsg(socket, bufsize, ancbufsize=0, flags=0):
    future = asyncio.Future()
    _sock_recvmsg(socket, bufsize, ancbufsize, flags, future)
    return (yield from asyncio.wait_for(future, None))

@asyncio.coroutine
def recv_message(stream_reader):
    command, type, size = protocol.unpack_header((yield from stream_reader.read(20)))
    data, fmt = protocol.deserialize_data(type, (yield from stream_reader.read(size)))
    return protocol.Message(command, type, data, fmt)

@asyncio.coroutine
def recv_message_timeout(stream_reader, timeout=10.0):
    try:
        data = yield from asyncio.wait_for(stream_reader.read(20), timeout=timeout)
    except concurrent.futures.TimeoutError:
        return None
    command, type, size = protocol.unpack_header(data)
    data, fmt = protocol.deserialize_data(type, (yield from stream_reader.read(size)))
    return protocol.Message(command, type, data, fmt)
