#!/usr/bin/env python3
import os, sys
os.execv("/usr/bin/python3", ["python3", os.path.expanduser("~/.local/share/bento-wallpaper/wallpaper_daemon.py")] + sys.argv[1:])
