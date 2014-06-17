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

import logging


class AsyncioFilter:
    def __init__(self, level=logging.INFO):
        self.level = level

    def filter(self, record):
            if record.name.startswith("asyncio") and record.levelno < self.level:
                return 0
            return 1


default_format = "%(asctime)s %(levelname)s [%(module)s:%(lineno)d] %(name)s - %(message)s"


def basicConfig(level=logging.DEBUG, asyncio_level=logging.INFO, format=default_format, handler=None):
    if handler is None:
        handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.addFilter(AsyncioFilter(asyncio_level))
    handler.setFormatter(logging.Formatter(format))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(level)
