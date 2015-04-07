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
Pure-python implementation of UDEV devices.

Can write udev database files.
"""

import os
import logging
import weakref

logger = logging.getLogger(__name__)

# udev runtime dir
RUNTIME_PATH = "/run/udev"
RUNTIME_DATA_PATH = RUNTIME_PATH + "/data"
SYS_PATH = "/sys"
DEV_PATH = "/dev"


class Device:
    """
    Manages a sysfs device node
    """
    __slots__ = ("syspath", "devpath", "sysname", "sysnum",
                 "devnum", "devnode", "devnode_mode", "devtype", "ifindex",
                 "id_filename", "subsystem", "environment",
                 "properties", "sysattrs", "devlinks", "tags",
                 "is_uevent_loaded", "is_db_loaded", "is_initialized",
                 "__weakref__")

    registry = weakref.WeakValueDictionary()

    def __init__(self):
        self.syspath = None
        self.devpath = None
        self.sysname = None
        self.sysnum  = None

        self.devnum = None
        self.devnode = None
        self.devnode_mode = None
        self.devtype = None
        self.ifindex = None

        self.id_filename = None
        self.subsystem = None

        self.properties = {}
        self.environment = {}
        self.sysattrs = {}
        self.devlinks = set()
        self.tags = set()

        self.is_uevent_loaded = False
        self.is_db_loaded = False
        self.is_initialized = False

    # -------------------------------------------------------------------------
    # [Handle special properties]
    # internal setter methods
    def set_syspath(self, path):
        self.syspath = path
        self.devpath = path[len(SYS_PATH):].rstrip("/")

        self.add_property("DEVPATH", self.devpath)
        self.add_property("KERNEL", os.path.basename(self.devpath))

        self.sysname = os.path.basename(path).replace("!", "/")

        for i, c in enumerate(reversed(self.sysname)):
            if not c.isdigit():
                break;
        self.sysnum = path[-i:]

    def set_subsystem(self, subsys):
        self.subsystem = subsys
        self.add_property("SUBSYSTEM", subsys)

    def set_devtype(self, devtype):
        self.devtype = devtype
        self.add_property("DEVTYPE", devtype)

    def set_ifindex(self, ifindex):
        self.ifindex = ifindex
        self.add_property("IFINDEX", str(ifindex))

    def set_devnode(self, devnode):
        if not devnode.startswith("/"):
            devnode = os.path.join(DEV_PATH, devnode)
        self.devnode = devnode
        self.add_property("DEVNAME", devnode)

    def add_property(self, key, value):
        """
        Add a propety to the device object
        NOTE: these are not persistent!!!
        use store_*_env() to modify the udev db.
        """
        self.properties[key] = value

    # getters
    def get_subsystem(self):
        if self.subsystem is None:
            # read subsystem link
            subsystem_link = os.path.join(self.syspath, "subsystem")
            if os.path.exists(subsystem_link):
                self.set_subsystem(os.path.basename(os.readlink(subsystem_link)))
            # implicit names
            elif self.devpath.startswith("/module/"):
                self.set_subsystem("module")
            elif self.devpath.startswith("/drivers/"):
                self.set_subsystem("drivers")
            elif self.devpath.startswith("/subsystem/") or\
                 self.devpath.startswith("/class/") or\
                 self.devpath.startswith("/bus/"):
                self.set_subsystem("subsystem")
        return self.subsystem

    def get_devnum(self):
        if self.devnum is None:
            self.read_uevent_file()
        return self.devnum

    def get_devtype(self):
        if self.devtype is None:
            self.read_uevent_file()
        return self.devtype

    def get_major_minor(self):
        dn = self.get_devnum()
        if not dn:
            return 0,0
        return os.major(dn), os.minor(dn)

    def get_ifindex(self):
        if self.ifindex is None:
            self.read_uevent_file()
        return self.ifindex

    def get_tags(self):
        if not self.is_db_loaded:
            self.read_db()
        return self.tags

    def get_devlinks(self):
        if not self.is_db_loaded:
            self.read_db()
        return self.devlinks

    # -------------------------------------------------------------------------
    # access properties
    def __getitem__(self, key):
        """ Retrieves a property """
        v = self._getitem(key)
        if v is not None:
            return v

        self.read_uevent_file()
        self.read_db()

        return self._getitem(key)

    def _getitem(self, key):
        if key in self.properties:
            return self.properties[key]
        elif key in self.environment:
            return self.environment[key]

    def get_properties(self):
        if not self.is_uevent_loaded:
            self.read_uevent_file()
        if not self.is_db_loaded:
            self.read_db()
        return self.properties

    def get_props_and_env(self):
        return dict(self.get_properties(), **self.environment)

    def get_environment(self):
        if not self.is_db_loaded:
            self.read_db()
        return self.environment

    def get_env(self, key, default=None):
        if not self.is_db_loaded:
            self.read_db()
        return self.environment.get(key, default)

    # -------------------------------------------------------------------------
    # [Manage relevant files]
    # Get uevent properties from sysfs if this device wasn't created from a uevent
    def read_uevent_file(self, *, force=False):
        """
        Read the device's uevent file
        """
        if self.is_uevent_loaded and not force:
            return

        path = os.path.join(self.syspath, "uevent")
        if not os.path.exists(path) or not os.access(path, os.R_OK, effective_ids=True):
            #logger.warn("Couldn't open device uevent file: No such file or directory (%s)" % path)
            return
            
        # Apparently, open() can still fail even after the above checks (Permission Denied, seems to happen on /sys/bus/usb/uevent a lot)
        # So we make sure not to break the system if it does.
        try:
            f = open(path, "r")
        except:
            logger.exception("Failed to open device uevent file for reading: %s" % path)
            return

        self.is_uevent_loaded = True

        maj = min = 0
        with f:
            for line in f:
                if not line.strip():
                    continue

                key, value = line.rstrip("\n").split("=", 1)

                if key == "DEVTYPE":
                    self.set_devtype(value)
                elif key == "IFINDEX":
                    self.set_ifindex(int(value))
                elif key == "DEVNAME":
                    self.set_devnode(value)
                else:
                    if key == "MAJOR":
                        maj = int(value)
                    elif key == "MINOR":
                        min = int(value)
                    elif key == "DEVMODE":
                        self.devnode_mode = int(value, 8)

                    self.add_property(key, value)

        self.devnum = os.makedev(maj, min)

    # Use the udev runtime database
    # All methods operating on the database take an optional db_file keyword argument to override the database path
    def get_id_filename(self):
        """
        Compute the filename of the database file
        """
        if self.id_filename is None:
            if self.get_subsystem() is None:
                return

            if self.get_devnum() and os.major(self.devnum) > 0:
                # use dev_t
                self.id_filename = "%s%i:%i" % ('b' if self.get_subsystem() == "block" else 'c', os.major(self.get_devnum()), os.minor(self.get_devnum()))
            elif self.get_ifindex() is not None:
                # use netdev ifindex
                self.id_filename = "n%i" % self.get_ifindex()
            else:
                # use SUBSYSTEM:SYSNAME
                # get_sysname() has ! translated, get it from devpath
                sysname = os.path.basename(self.devpath)
                self.id_filename = "+%s:%s" % (self.get_subsystem(), sysname)
            #logger.debug("ID_FILENAME for %s is %s" % (self.devpath, self.id_filename))
        return self.id_filename

    def read_db(self, *, db_file=None, force=False, clean=None):
        """
        Read the UDEV db for this device

        Use the force keyword argument to re-load the db even if it's already been loaded.
        Use the clean keyword argument to prevent the current values getting cleaned.
        """
        if clean is None:
            clean = db_file is None

        if db_file is None:
            if self.is_db_loaded and not force:
                return
            self.is_db_loaded = True

            id = self.get_id_filename()
            if not id:
                return
            db_file = os.path.join(RUNTIME_DATA_PATH, id)

            if not os.path.exists(db_file):
                return

        with open(db_file, "r") as f:
            self.is_initialized = True

            if clean:
                self.devlinks = set()
                self.environment = {}
                self.tags = set()

            for line in f:
                line = line.rstrip("\n")

                if line[0] == 'S':
                    # devlink
                    self.devlinks.add(line[2:])
                elif line[0] == 'L':
                    # devlink priority
                    pass#self.set_devlink_priority(int(line[2:]))
                elif line[0] == 'E':
                    # property
                    prop, value = line[2:].split("=", 1)
                    self.environment[prop] = value
                elif line[0] == 'G':
                    # tag
                    self.tags.add(line[2:])
                elif line[0] == 'W':
                    # watch handle
                    pass#self.set_watch_handle(int(line[2:]))
                elif line[0] == 'I':
                    # initialization time
                    pass#self.set_usec_initialized(int(line[2:]))

        #logger.info("Read udev db file for %s" % self.devpath)

    # To keep the environment in sync, all the store_*_env execute file transactions! (bottleneck!)
    def store_one_env(self, key, value, *, db_file=None):
        """
        Write a value to the environment file
        """
        if db_file is None:
            id = self.get_id_filename()
            if not id:
                raise TypeError("get_id_filename() returned None and db_file wasn't given.")
            db_file = os.path.join(RUNTIME_DATA_PATH, id)

        lines = []
        if os.path.exists(db_file):
            with open(db_file, "r") as f:
                for line in f:
                    if not line.startswith("E:%s=" % key):
                        lines.append(line)

        lines.append("E:%s=%s\n" % (key, value))

        with open(db_file, "w") as f:
            for line in lines:
                f.write(line)

        # update
        self.environment[key] = value

    def store_many_env(self, dict, *, db_file=None):
        if db_file is None:
            id = self.get_id_filename()
            if not id:
                raise TypeError("get_id_filename() returned None and db_file wasn't given.")
            db_file = os.path.join(RUNTIME_DATA_PATH, id)

        lines = []
        if os.path.exists(db_file):
            with open(db_file, "r") as f:
                for line in f:
                    if not (line.startswith("E:") and line[2:].split("=", 1)[0] in dict):
                        lines.append(line)

        for i in dict.items():
            lines.append("E:%s=%s\n" % i)

        with open(db_file, "w") as f:
            for line in lines:
                f.write(line)

        self.environment.update(dict)

    def store_new_env(self, dict, *, db_file=None):
        """
        Like store_many_env, but replaces all evnironment entries.
        """
        if db_file is None:
            id = self.get_id_filename()
            if not id:
                raise TypeError("get_id_filename() returned None and db_file wasn't given.")
            db_file = os.path.join(RUNTIME_DATA_PATH, id)

        lines = []
        if os.path.exists(db_file):
            with open(db_file, "r") as f:
                for line in f:
                    if not line.startswith("E:"):
                        lines.append(line)

        for i in dict.items():
            lines.append("E:%s=%s\n" % i)

        with open(db_file, "w") as f:
            for line in lines:
                f.write(line)

        self.environment = dict

    # The *_env_buffer methods operate directly on the udev database file.
    # store_new_env_from_buffer therefore BREAKS ENVIROMENT SYNC!
    def make_db_env_buffer(self, *, db_file=None, error_if_nonexistent=False):
        """
        Like read_db_env, but makes a bytestring with \0-separated KEY=VALUE pairs
        """
        if db_file is None:
            id = self.get_id_filename()
            if not id:
                raise TypeError("get_id_filename() returned None and db_file wasn't given.")
            db_file = os.path.join(RUNTIME_DATA_PATH, id)

        kvp = []
        if os.path.exists(db_file):
            with open(db_file, "rb") as f:
                for line in f:
                    if line.startswith(b"E:"):
                        kvp.append(line[2:].rstrip(b"\n"))
        elif error_if_nonexistent:
            raise FileNotFoundError("%s: No such file or directory" % db_file)
        return b'\0'.join(kvp)

    def store_new_env_buffer(self, buffer, *, db_file=None):
        """
        store_new_env, but reads a make_db_env_buffer buffer
        """
        if db_file is None:
            id = self.get_id_filename()
            if not id:
                raise TypeError("get_id_filename() returned None and db_file wasn't given.")
            db_file = os.path.join(RUNTIME_DATA_PATH, id)

        lines = []
        if os.path.exists(db_file):
            with open(db_file, "rb") as f:
                for line in f:
                    if not line.startswith(b"E:"):
                        lines.append(line)

        if buffer:
            for prop in buffer.split(b'\0'):
                lines.append(b"E:" + prop + b'\n')

        with open(db_file, "wb") as f:
            for line in lines:
                f.write(line)

        # YOU REALLY SHOULD DISCARD THIS DEVICE INSTANCE AFTER CALLING THIS >.<
        # If you insist on keeping this instace, at least call read_db(force=True).

    # Flush the current db state to disk
    # USE WITH CARE!
    def flush_db(self, *, db_file=None):
        """
        Stores all environment entries, devlinks and tags in the udev database
        """
        if db_file is None:
            id = self.get_id_filename()
            if not id:
                raise TypeError("get_id_filename() returned None and db_file wasn't given.")
            db_file = os.path.join(RUNTIME_DATA_PATH, id)

        lines = []
        with open(db_file, "r") as fp:
            for line in fp:
                if line[0] not in "SEG":
                    lines.append(line)

        with open(db_file, "w") as fp:
            for line in lines:
                fp.write(line)
            for devlink in self.devlinks:
                fp.write("S:%s\n" % devlink)
            for env_entry in self.environment.items():
                fp.write("E:%s=%s\n" % env_entry)
            for tag in self.tags:
                fp.write("G:%s\n" % tag)

    # -------------------------------------------------------------------------
    # [/sys Attributes]
    def get_sysattr(self, name):
        if name not in self.sysattrs:
            syspath = os.path.join(self.syspath, name)
            try:
                with open(syspath) as f:
                    value = f.read().rstrip("\n")
            except FileNotFoundError:
                value = None
            #else:
            #    print(syspath, "=", value)
            self.sysattrs[name] = value
        return self.sysattrs[name]

    # -------------------------------------------------------------------------
    # [Create device instances]
    @classmethod
    def _from_real_syspath(cls, syspath, path):
        # syspath starts in sys
        if not syspath.startswith(SYS_PATH):
            logger.warn("SYSPATH not in /sys: %s" % syspath)
            return None

        # syspath is not a root directory
        devpath = syspath[len(SYS_PATH):]
        if not devpath or devpath == "/":
            #logger.warn("SYSPATH not complete: %s" % syspath)
            return None

        if path[len(SYS_PATH):].startswith("/devices/"):
            # devices require an uevent file
            if not os.path.exists(os.path.join(path, "uevent")):
                #logger.warn("DEVICE node without uevent: %s (%s)" % (syspath, path))
                return None

        else:
            # other things need to be directories
            if not os.path.isdir(path):
                logger.warn("Not a directory: %s (%s)" % (syspath, path))
                return None

        self = cls()
        self.set_syspath(path)
        cls.registry[path] = self
        return self

    @classmethod
    def from_syspath(cls, syspath):
        return cls._from_real_syspath(syspath, os.path.realpath(syspath))

    @classmethod
    def from_syspath_or_registry(cls, syspath):
        # possibly a symlink
        path = os.path.realpath(syspath)

        if path in cls.registry:
            return cls.registry[path]
        else:
            return cls._from_real_syspath(syspath, path)

    @classmethod
    def from_devpath(cls, devpath):
        return cls.from_syspath(SYS_PATH + devpath)

    @classmethod
    def from_devpath_or_registry(cls, devpath):
        return cls.from_syspath_or_registry(SYS_PATH + devpath)

    @classmethod
    def from_props(cls, props, *, from_uevent=False):
        # Needs at least DEVPATH!
        self = cls()
        self.properties = dict(props)
        self.set_syspath(SYS_PATH + props["DEVPATH"])
        if "SUBSYSTEM" in props:
            self.set_subsystem(props["SUBSYSTEM"])
        if "IFINDEX" in props:
            self.set_ifindex(int(props["IFINDEX"]))
        if "DEVNAME" in props:
            self.set_devnode(props["DEVNAME"])
        if "DEVTYPE" in props:
            self.set_devtype(props["DEVTYPE"])
        if "DEVMODE" in props:
            self.devnode_mode = int(props["DEVMODE"], 8)
        major = minor = 0
        if "MAJOR" in props:
            major = int(props["MAJOR"])
        if "MINOR" in props:
            minor = int(props["MINOR"])
        self.devnum = os.makedev(major, minor)
        self.is_uevent_loaded = from_uevent

        # The device itself doesn't have an action!
        if "ACTION" in props:
            del self.properties["ACTION"]

        cls.registry[self.syspath] = self
        return self

    def get_parent(self):
        """
        Get this device's parent.
        """
        devpath = self.devpath
        while "/" in devpath[1:]: # don't return devices for things like /devices or /class
            devpath = devpath.rsplit("/", 1)[0]
            device = self.from_devpath_or_registry(devpath)
            if device:
                return device

    # -------------------------------------------------------------------------
    # [Manage Device Registry]
    @classmethod
    def enable_persistent_registry(cls):
        """
        Make the registry strong.
        This means the application needs to manually invalidate devices on changes (listen to UEVENTs)
        On the other hand, this makes the registry much more efficient.
        """
        cls.registry = dict(cls.registry)

    @classmethod
    def invalidate_syspath(cls, syspath):
        if syspath in cls.registry:
            del cls.registry[syspath]

    @classmethod
    def invalidate_devpath(cls, devpath):
        cls.invalidate_syspath(SYS_PATH + devpath)

    def invalidate(self):
        del self.registry[self.syspath]
