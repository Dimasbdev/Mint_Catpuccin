#!/usr/bin/env python3
import os
import sys
import time
import socket
import subprocess
import ctypes
import ctypes.util
import gi

gi.require_version('Gio', '2.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gio, GLib

LOCK_CMD = os.path.expanduser("~/.local/bin/bento-lock")
SOCKET_PATH = f"/tmp/bento-lock-{os.getuid()}.sock"
LOCK_FLAG = f"/tmp/bento-lock-{os.getuid()}.locked"

NODE_INFO = Gio.DBusNodeInfo.new_for_xml('''
<node>
  <interface name='org.cinnamon.ScreenSaver'>
    <method name='Lock'>
      <arg type='s' name='msg' direction='in'/>
    </method>
    <method name='Quit'/>
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

class X11IdleMonitor:
    """Ultra-fast, zero-overhead hardware idle time monitor via XScreenSaverQueryInfo."""
    def __init__(self):
        self.dpy = None
        self.root = None
        self.xss = None
        self.info = None
        try:
            x11 = ctypes.cdll.LoadLibrary(ctypes.util.find_library('X11'))
            xss = ctypes.cdll.LoadLibrary(ctypes.util.find_library('Xss'))

            class XScreenSaverInfo(ctypes.Structure):
                _fields_ = [
                    ('window', ctypes.c_ulong),
                    ('state', ctypes.c_int),
                    ('kind', ctypes.c_int),
                    ('til_or_since', ctypes.c_ulong),
                    ('idle', ctypes.c_ulong),
                    ('eventMask', ctypes.c_ulong)
                ]

            self.x11 = x11
            self.xss = xss
            self.XScreenSaverInfo = XScreenSaverInfo
            self.dpy = x11.XOpenDisplay(None)
            if self.dpy:
                self.root = x11.XDefaultRootWindow(self.dpy)
                self.info = XScreenSaverInfo()
        except Exception as e:
            print(f"[bento-screensaver] X11 idle monitor init failed: {e}", file=sys.stderr)

    def get_idle_seconds(self):
        if not self.dpy or not self.xss or not self.info:
            return 0.0
        try:
            self.xss.XScreenSaverQueryInfo(self.dpy, self.root, ctypes.byref(self.info))
            return self.info.idle / 1000.0
        except Exception:
            return 0.0


class ScreensaverProxy:
    def __init__(self):
        self.lock_time = 0
        self.is_locked = False
        self.conn = None
        self.check_timer_id = None
        self.idle_lock_timer_id = None
        self.x11_idle_timer_id = None

        self.x11_monitor = X11IdleMonitor()

        # Connect GSettings
        try:
            self.session_settings = Gio.Settings(schema_id="org.cinnamon.desktop.session")
        except Exception:
            self.session_settings = None

        try:
            self.ss_settings = Gio.Settings(schema_id="org.cinnamon.desktop.screensaver")
        except Exception:
            self.ss_settings = None

    def get_idle_delay(self):
        if self.session_settings:
            try:
                return self.session_settings.get_uint("idle-delay")
            except Exception:
                pass
        return 600

    def get_lock_enabled(self):
        if self.ss_settings:
            try:
                return self.ss_settings.get_boolean("lock-enabled")
            except Exception:
                pass
        return True

    def get_lock_delay(self):
        if self.ss_settings:
            try:
                return self.ss_settings.get_uint("lock-delay")
            except Exception:
                pass
        return 0

    def get_idle_activation_enabled(self):
        if self.ss_settings:
            try:
                return self.ss_settings.get_boolean("idle-activation-enabled")
            except Exception:
                pass
        return True

    def is_idle_inhibited(self):
        """Check if session is currently inhibited from idle (e.g. fullscreen video/presentation)."""
        if not self.conn:
            return False
        try:
            res = self.conn.call_sync(
                'org.gnome.SessionManager',
                '/org/gnome/SessionManager',
                'org.gnome.SessionManager',
                'IsInhibited',
                GLib.Variant('(u)', (8,)),  # GSM_INHIBITOR_FLAG_IDLE = 8
                GLib.VariantType('(b)'),
                Gio.DBusCallFlags.NONE,
                200,
                None
            )
            return bool(res.unpack()[0])
        except Exception:
            return False

    def is_active(self):
        return os.path.exists(LOCK_FLAG) or self.is_locked

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
        """Polls whether screen was unlocked via PAM / user input."""
        active = os.path.exists(LOCK_FLAG)
        if not active:
            self.set_active(False)
            self.check_timer_id = None
            return False
        return True

    def _start_status_polling(self):
        if not self.check_timer_id:
            self.check_timer_id = GLib.timeout_add(1000, self.check_lock_status)

    def lock(self, msg=""):
        if self.is_active():
            return
        self.lock_time = time.time()
        self.set_active(True)

        fast_send = os.path.expanduser("~/.local/bin/bento-sock-send")
        locked_ok = False
        if os.path.exists(fast_send) and os.path.exists(SOCKET_PATH):
            try:
                if subprocess.run([fast_send, SOCKET_PATH, "lock"], timeout=0.5).returncode == 0:
                    locked_ok = True
            except Exception:
                pass

        if not locked_ok and os.path.exists(SOCKET_PATH):
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(0.5)
                s.connect(SOCKET_PATH)
                s.sendall(b"lock\n")
                s.close()
                locked_ok = True
            except Exception:
                pass

        if not locked_ok:
            subprocess.Popen(
                [LOCK_CMD],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )

        # Always ensure unlock status polling is active
        if self.check_timer_id:
            GLib.source_remove(self.check_timer_id)
            self.check_timer_id = None
        GLib.timeout_add(1500, lambda: (self._start_status_polling(), False)[1])

    def unlock(self):
        fast_send = os.path.expanduser("~/.local/bin/bento-sock-send")
        if os.path.exists(fast_send) and os.path.exists(SOCKET_PATH):
            try:
                subprocess.run([fast_send, SOCKET_PATH, "unlock"], timeout=0.5)
            except Exception:
                pass
        elif os.path.exists(SOCKET_PATH):
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(0.5)
                s.connect(SOCKET_PATH)
                s.sendall(b"unlock\n")
                s.close()
            except Exception:
                pass
        if os.path.exists(LOCK_FLAG):
            try:
                os.unlink(LOCK_FLAG)
            except OSError:
                pass
        self.set_active(False)
        if self.check_timer_id:
            GLib.source_remove(self.check_timer_id)
            self.check_timer_id = None

    def _cancel_idle_lock_timer(self):
        if self.idle_lock_timer_id:
            GLib.source_remove(self.idle_lock_timer_id)
            self.idle_lock_timer_id = None

    def _on_presence_status_changed(self, conn, sender, path, iface, signal, params, user_data):
        try:
            (status_code,) = params.unpack()
            if status_code == 3:  # 3 = IDLE
                self._handle_session_idle()
            else:
                self._cancel_idle_lock_timer()
        except Exception as e:
            print(f"[bento-screensaver] Presence status changed error: {e}", file=sys.stderr)

    def _handle_session_idle(self):
        if self.is_active():
            return
        if not self.get_idle_activation_enabled() or not self.get_lock_enabled():
            return
        if self.is_idle_inhibited():
            return

        lock_delay = self.get_lock_delay()
        if lock_delay == 0:
            print("[bento-screensaver] Session presence IDLE -> locking screen", flush=True)
            self.lock()
        else:
            self._cancel_idle_lock_timer()
            self.idle_lock_timer_id = GLib.timeout_add_seconds(
                lock_delay,
                self._on_idle_delay_timeout
            )

    def _on_idle_delay_timeout(self):
        self.idle_lock_timer_id = None
        if not self.is_active() and not self.is_idle_inhibited():
            print("[bento-screensaver] Idle lock-delay expired -> locking screen", flush=True)
            self.lock()
        return False

    def _check_x11_idle_tick(self):
        """Continuous safety guard: queries hardware idle time directly from X11."""
        if self.is_active():
            return True

        if not self.get_idle_activation_enabled() or not self.get_lock_enabled():
            return True

        idle_delay = self.get_idle_delay()
        if idle_delay == 0:
            return True  # Idle locking disabled by user

        lock_delay = self.get_lock_delay()
        total_limit = idle_delay + lock_delay

        idle_seconds = self.x11_monitor.get_idle_seconds()
        if idle_seconds >= total_limit:
            if not self.is_idle_inhibited():
                print(f"[bento-screensaver] Hardware idle limit reached ({idle_seconds:.1f}s >= {total_limit}s) -> locking screen", flush=True)
                self.lock()

        return True

    def handle_method_call(self, conn, sender, path, iface, method, params, invocation):
        try:
            if method == 'Lock':
                self.lock()
                invocation.return_value(None)
            elif method == 'Quit':
                invocation.return_value(None)
            elif method == 'SetActive':
                (val,) = params.unpack()
                if val:
                    if not self.is_active():
                        if self.get_lock_enabled():
                            self.lock()
                        else:
                            self.set_active(True)
                    else:
                        self.set_active(True)
                else:
                    self.set_active(False)
                invocation.return_value(None)
            elif method == 'GetActive':
                active = self.is_active()
                if active and not self.is_locked:
                    self.set_active(True)
                elif not active and not self.lock_time:
                    self.set_active(False)
                invocation.return_value(GLib.Variant('(b)', (self.is_locked,)))
            elif method == 'GetActiveTime':
                t = int(time.time() - self.lock_time) if (self.is_locked and self.lock_time > 0) else 0
                invocation.return_value(GLib.Variant('(u)', (t,)))
            elif method == 'SimulateUserActivity':
                self._cancel_idle_lock_timer()
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

        # 1. Subscribe to org.gnome.SessionManager.Presence StatusChanged
        conn.signal_subscribe(
            'org.gnome.SessionManager',
            'org.gnome.SessionManager.Presence',
            'StatusChanged',
            '/org/gnome/SessionManager/Presence',
            None,
            Gio.DBusSignalFlags.NONE,
            self._on_presence_status_changed,
            None
        )

        # 2. Subscribe to systemd-logind Lock & Unlock signals on system bus
        try:
            sys_bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            sys_bus.signal_subscribe(
                'org.freedesktop.login1',
                'org.freedesktop.login1.Session',
                'Lock',
                None,
                None,
                Gio.DBusSignalFlags.NONE,
                lambda *args: self.lock(),
                None
            )
            sys_bus.signal_subscribe(
                'org.freedesktop.login1',
                'org.freedesktop.login1.Session',
                'Unlock',
                None,
                None,
                Gio.DBusSignalFlags.NONE,
                lambda *args: self.unlock(),
                None
            )
        except Exception as e:
            print(f"[bento-screensaver] Logind signal subscription error: {e}", file=sys.stderr)

        # 3. Start hardware X11 idle check ticker every 5 seconds
        if not self.x11_idle_timer_id:
            self.x11_idle_timer_id = GLib.timeout_add_seconds(5, self._check_x11_idle_tick)


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
