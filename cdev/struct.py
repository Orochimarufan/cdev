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
define structures like classes:

class MyStruct(cdev.struct.Struct):
    format = "III"
    names = "id", "version", "magic"

struct classes implement pack(), unpack() and unpack_from()

MixStruct helps with different byteorders or size definitions in the same structure (gotta work with what other people design sometimes!):

class MyStruct(cdev.struct.MixStruct):
    formats = "!iii", "=LLL", "@i"
    names = "nl1", "nl2", "nl3", "h1", "h2", "h3", "n"


There also are Frozen(Mix)Struct classes that use a tuple for storage instead of a list

All (Frozen)(Mix)Struct types use __slots__.
"""

import struct
from itertools import chain

# Import a few functions
calcsize = struct.calcsize
unpack = struct.unpack
unpack_from = struct.unpack_from
pack = struct.pack


# Helpers
def calccount(fmt):
    """
    Calculate the number of items in a format string
    """
    cnt = 0
    numbuf = []

    for c in fmt:
        if c.isdigit():
            numbuf.append(c)
            continue
        elif numbuf:
            times = int("".join(numbuf))
            numbuf.clear()
        else:
            times = 1

        if c in "@=<>!":
            pass # doesn't impact item count
        elif c in "sp":
            # Strings are prepended with the length, not a multiplier.
            cnt += 1
        else:
            cnt += times
    return cnt


# extended Struct type
class StructType(type):
    def __init__(cls, name, bases, body):
        super().__init__(name, bases, body)

        # Generate name mapping
        names = body["names"]
        cls._namemap = {n:i for i,n in enumerate(names)}

        # Skip if we got a MixStruct
        if type(cls) is not StructType:
            return

        # create struct instance
        format = body["format"]

        cls._struct = struct.Struct(format)
        cls._totalct = calccount(format)
        cls.size = cls._struct.size

        if len(names) != cls._totalct:
            raise TypeError("Struct holds %i items, but %i names were specified!" % (cls._itemcnt, len(names)))


class _StructBase:
    __slots__ = ()

    def __getattr__(self, name):
        if name in self.names:
            return self[self._namemap[name]]
        else:
            raise AttributeError("Struct %s has no member '%s'" % (type(self).__name__, name))

    def pack(self):
        return self._struct.pack(self)

    @classmethod
    def unpack_from(cls, buffer, offset=0):
        return cls(cls._struct.unpack_from(buffer, offset))

    @classmethod
    def unpack(cls, buffer):
        return cls(cls._struct.unpack(buffer))


class FrozenStruct(_StructBase, tuple, metaclass=StructType):
    __slots__ = ()

    def __init__(self, iterable):
        if len(self) != self._totalct:
            raise TypeError("Size of struct %s is %i, tried to initialize with %i items" % (type(self).__name__, self._totalct, len(self)))

    def __setattr__(self, name, value):
        raise AttributeError("Cannot assign to %s" % type(self).__name__)

    format = ""
    names = ()


class Struct(_StructBase, list, metaclass=StructType):
    __slots__ = ()

    def __init__(self, iterable):
        super().__init__(iterable)
        if len(self) != self._totalct:
            raise TypeError("Size of struct %s is %i, tried to initialize with %i items" % (type(self).__name__, self._totalct, len(self)))

    def __setattr__(self, name, value):
        if name in self.names:
            self[self._namemap[name]] = value
        else:
            raise AttributeError("Struct %s has no member '%s'" % (type(self).__name__, name))

    format = ""
    names = ()


# deal with the mixed byteorders :/
class MixStructType(StructType):
    def __init__(cls, name, bases, body):
        if "format" in body:
            body["formats"] = (body["format"],)

        super().__init__(name, bases, body)

        formats = body["formats"]

        # [pre-calculate various things]
        # compile the parts
        cls._structs = tuple(struct.Struct(format) for format in formats)
        # calculate the absolute byte offsets
        cls._offsets = tuple(sum(struct.size for struct in cls._structs[:i]) for i in range(len(cls._structs)))
        # calculate the item counts for each part
        cls._itemcnt = tuple(map(calccount, formats))
        # calculate the absolute item offsets
        cls._itemoff = tuple(sum(cls._itemcnt[:i]) for i in range(len(formats)))
        # sum up the part sizes to get the total size
        cls._totalct = sum(cls._itemcnt)
        cls.size = sum(struct.size for struct in cls._structs)

        #print(formats, cls._itemcnt, cls._itemoff, len(names))

        if len(cls.names) != cls._totalct:
            raise TypeError("Struct holds %i items, but %i names were specified!" % (cls._totalct, len(names)))


class _MixStructBase:
    __slots__ = ()

    def pack(self):
        return b"".join(self._structs[i].pack(*self[self._itemoff[i]:self._itemoff[i]+self._itemcnt[i]]) for i in range(len(self._structs)))

    @classmethod
    def unpack_from(cls, buffer, offset=0):
        return cls(chain.from_iterable(cls._structs[i].unpack_from(buffer, offset+cls._offsets[i]) for i in range(len(cls._structs))))

    @classmethod
    def unpack(cls, buffer):
        return cls(chain.from_iterable(cls._structs[i].unpack_from(buffer, cls._offsets[i]) for i in range(len(cls._structs))))


class FrozenMixStruct(_MixStructBase, FrozenStruct, metaclass=MixStructType):
    __slots__ = ()

    formats = ()
    names = ()


class MixStruct(_MixStructBase, Struct, metaclass=MixStructType):
    """
    A structure with mixed byteorders

    NOTE: implemented as list, to make it mutable.
    """
    __slots__ = ()

    formats = ()
    names = ()
