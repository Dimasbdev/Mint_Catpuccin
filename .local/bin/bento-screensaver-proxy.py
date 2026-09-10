#!/usr/bin/env python3
import os
import sys
import time
import socket
import os, subprocess
import gi

gi.require_version('Gio', '2.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gio, GLib

LOCK_CMD = "~.local/bin/bento-lock"
SOCKET_PATH = f"/tmp/bento-lock-{os.getuid()}.sock"

NODE_INFO = Gio.DBusNodeInfo.new_for_xml('''
<node>
  <interface name='org.cinnamon.ScreenSaver'>
    <method name='Lock'>
      <arg type='s' name='msg' direction='in'/>
    </method>
    <method name='SetActive'>
      <arg type='b' name='value' direction='in'/>
    </method>
    <method name='GetActive'>
      <arg type='b' name='active' direction='out'/>
    </method>
    <method name='GetActiveTime'>
      <arg type='u' name='value' direction='out'/>
    </method>
    <method name='SimulateUserActivity'/>
    <signal name='ActiveChanged'>
      <arg type='b' name='new_value'/>
    </signal>
  </interface>
</node>
''')

class ScreensaverProxy:
    def __init__(self):
        self.lock_time = 0
        self.is_locked = False
        self.conn = None
        self.check_timer_id = None

    def is_active(self):
        if not os.path.exists(SOCKET_PATH):
            return False
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(0.1)
            s.connect(SOCKET_PATH)
            s.close()
            return True
        except (socket.error, OSError):
            try:
                os.unlink(SOCKET_PATH)
            except OSError:
                pass
            return False

    def set_active(self, val):
        if self.is_locked != val:
            self.is_locked = val
            if not val:
                self.lock_time = 0
            if self.conn:
                try:
                    self.conn.emit_signal(
                        None,
                        '/org/cinnamon/ScreenSaver',
                        'org.cinnamon.ScreenSaver',
                        'ActiveChanged',
                        GLib.Variant('(b)', (val,))
                    )
                except Exception:
                    pass

    def check_lock_status(self):
        active = self.is_active()
        if not active:
            self.set_active(False)
            self.check_timer_id = None
            return False
        return True

    def lock(self):
        if not self.is_active():
            self.lock_time = time.time()
            self.set_active(True)
            subprocess.Popen(
                [LOCK_CMD],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            if not self.check_timer_id:
                self.check_timer_id = GLib.timeout_add(500, self.check_lock_status)

    def handle_method_call(self, conn, sender, path, iface, method, params, invocation):
        try:
            if method == 'Lock':
                self.lock()
                invocation.return_value(None)
            elif method == 'SetActive':
                (val,) = params.unpack()
                if val:
                    self.lock()
                invocation.return_value(None)
            elif method == 'GetActive':
                active = self.is_active()
                self.set_active(active)
                if active and not self.check_timer_id:
                    self.check_timer_id = GLib.timeout_add(500, self.check_lock_status)
                invocation.return_value(GLib.Variant('(b)', (active,)))
            elif method == 'GetActiveTime':
                active = self.is_active()
                t = int(time.time() - self.lock_time) if (active and self.lock_time > 0) else 0
                invocation.return_value(GLib.Variant('(u)', (t,)))
            elif method == 'SimulateUserActivity':
                invocation.return_value(None)
            else:
                invocation.return_value(None)
        except Exception as e:
            invocation.return_dbus_error(
                "org.cinnamon.ScreenSaver.Error",
                str(e)
            )

    def on_bus_acquired(self, conn, name):
        self.conn = conn
        conn.register_object(
            '/org/cinnamon/ScreenSaver',
            NODE_INFO.interfaces[0],
            self.handle_method_call,
            None,
            None
        )

def main():
    proxy = ScreensaverProxy()
    owner_id = Gio.bus_own_name(
        Gio.BusType.SESSION,
        'org.cinnamon.ScreenSaver',
        Gio.BusNameOwnerFlags.REPLACE,
        proxy.on_bus_acquired,
        None,
        None
    )
    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()
