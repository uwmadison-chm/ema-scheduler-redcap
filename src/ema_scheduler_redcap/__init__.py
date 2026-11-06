#!/usr/env/bin python

# Copyright 2023 Board of Regents of the University of Wisconsin System
# Written by Nate Vack <njvack@wisc.edu>, and Stuti Shrivastava <sshrivastav6@wisc.edu>
# Source is available at https://github.com/uwmadison-chm/ema_scheduler_redcap

from importlib.metadata import metadata as _metadata

_meta = _metadata("ema_scheduler_redcap")
__version__ = _meta["Version"]
__author__ = _meta["Author-email"]
__description__ = _meta["Summary"]
