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
Pure python implementation of MurmurHash2

While I consider this implementation highly optimized,
there's only so much optimization you can do in python.

Conclusion:
    USE A C VERSION WHERE AVAILABLE!!!!!
"""

import array

if array.array('L').itemsize == 4:
    uint32_t = 'L'
elif array.array('I').itemsize == 4:
    uint32_t = 'I'
else:
    raise ImportError("Could not determine 4-byte array code!")


def MurmurHash2(input, seed=0):
    """
    Generate a 32-bit hash from a string using the MurmurHash2 algorithm

    takes a bytestring!

    Pure-python implementation.
    """
    l = len(input)

    # m and r are mixing constants generated offline
    # They're not really magic, they just happen to work well
    m = 0x5bd1e995
    #r = 24

    # Initialize the hash to a "random" value
    h = seed ^ l

    # Mix 4 bytes at a time into the hash
    x = l % 4
    o = l - x

    for k in array.array(uint32_t, input[:o]):
        # Original Algorithm
        #k *= m;
        #k ^= k >> r;
        #k *= m;

        #h *= m;
        #h ^= k;

        # My Algorithm
        k = (k * m) & 0xFFFFFFFF
        h = (((k ^ (k >> 24)) * m) ^ (h * m)) & 0xFFFFFFFF

        # Explanation: We need to keep it 32-bit. There are a few rules:
        # 1. Inputs to >> must be truncated, it never overflows
        # 2. Inputs to * must be truncated, it may overflow
        # 3. Inputs to ^ may be overflowed, it overflows if any input was overflowed
        # 4. The end result must be truncated
        # Therefore:
        # b = k * m -> may overflow, we truncate it because b >> r cannot take overflowed data
        # c = b ^ (b >> r) -> never overflows, as b is truncated and >> never does
        # h = (c * m) ^ (h * m) -> both inputs to ^ may overflow, but since ^ can take it, we truncate once afterwards.

    # Handle the last few bytes of the input array
    if x > 0:
        if x > 2:
            h ^= input[o+2] << 16
        if x > 1:
            h ^= input[o+1] << 8
        h = ((h ^ input[o]) * m) & 0xFFFFFFFF

    # Do a few final mixes of the hash to ensure the last few
    # bytes are well incorporated

    # Original:
    #h ^= h >> 13;
    #h *= m;
    #h ^= h >> 15;

    h = ((h ^ (h >> 13)) * m) & 0xFFFFFFFF
    return (h ^ (h >> 15))


def util_string_bloom64(input):
    """
    as in libudev-util.c
    """
    h = MurmurHash2(input)

    return (1 << (h & 63)) | (1 << ((h >> 6) & 63)) | (1 << ((h >> 12) & 63)) | (1 << ((h >> 18) & 63))
