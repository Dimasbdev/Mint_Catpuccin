#!/usr/bin/env python3
import os, sys, json, subprocess, time, urllib.parse, base64, ctypes
import cairo
import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('WebKit2', '4.1')
gi.require_version('Gio', '2.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, WebKit2, GLib, Gio

import dbus
import dbus.service
import dbus.mainloop.glib

dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

class ToastWindow(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("BentoToast")
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)
        self.set_app_paintable(True)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.set_can_focus(False)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        self.stick()

        # Geometry positioning (top right below panel)
        monitor = screen.get_monitor_geometry(screen.get_primary_monitor())
        self.win_width = 410
        self.max_height = monitor.height - 60
        self.current_height = 110
        self.pos_x = monitor.x + monitor.width - self.win_width - 12
        self.pos_y = monitor.y + 46  # Right below the 40px top panel

        self.move(self.pos_x, self.pos_y)
        self.set_default_size(self.win_width, self.current_height)

        # WebKit setup
        ucm = WebKit2.UserContentManager()
        ucm.register_script_message_handler("window_state")
        ucm.connect("script-message-received::window_state", self.on_window_state)

        ucm.register_script_message_handler("notification_closed")
        ucm.connect("script-message-received::notification_closed", self.on_notification_closed)

        ucm.register_script_message_handler("action_invoked")
        ucm.connect("script-message-received::action_invoked", self.on_action_invoked)

        ucm.register_script_message_handler("update_geometry")
        ucm.connect("script-message-received::update_geometry", self.on_update_geometry)

        settings = WebKit2.Settings()
        settings.set_enable_javascript(True)
        settings.set_allow_file_access_from_file_urls(True)
        settings.set_allow_universal_access_from_file_urls(True)
        settings.set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.ALWAYS)

        self.webview = WebKit2.WebView.new_with_user_content_manager(ucm)
        self.webview.set_can_focus(False)
        self.webview.set_settings(settings)
        self.webview.set_background_color(Gdk.RGBA(0.0, 0.0, 0.0, 0.0))

        html_path = os.path.expanduser("~/.local/share/bento-toast/index.html")
        self.webview.load_uri(f"file://{html_path}")
        self.webview.connect("context-menu", lambda *args: True)

        self.add(self.webview)
        self.connect("destroy", Gtk.main_quit)
        self.connect("map-event", self.on_map_event)

        self.active_count = 0
        self.server = None

        # Subscribe to dynamic theme changes
        try:
            bus = dbus.SessionBus()
            bus.add_signal_receiver(
                self.on_theme_changed,
                signal_name="ThemeChanged",
                dbus_interface="org.bento.Theme",
                path="/org/bento/Theme"
            )
        except Exception:
            pass
        self.apply_theme_from_file()

    def on_theme_changed(self, colors_path):
        GLib.idle_add(self.apply_theme_from_file, colors_path)

    def apply_theme_from_file(self, colors_path=None):
        path = colors_path or os.path.expanduser("~/.cache/bento/colors.json")
        if not os.path.exists(path):
            return
        try:
            with open(path, "r") as f:
                theme = json.load(f)
            js = f"""
            (function() {{
                const root = document.documentElement;
                root.style.setProperty('--flamingo', '{theme['primary']}');
                root.style.setProperty('--accent', '{theme['primary']}');
                root.style.setProperty('--mauve', '{theme['secondary']}');
                root.style.setProperty('--accent-sec', '{theme['secondary']}');
                root.style.setProperty('--border-subtle', '{theme['border_subtle']}');
                root.style.setProperty('--border-active', '{theme['border_active']}');
                root.style.setProperty('--glow', '{theme['accent_subtle']}');
            }})();
            """
            self.webview.run_javascript(js)
        except Exception:
            pass

    def on_map_event(self, widget, event):
        # Strip WM_TAKE_FOCUS so Muffin never tries to focus or disturb active window
        try:
            gdkwin = self.get_window()
            if gdkwin:
                x11 = ctypes.CDLL('libX11.so.6')
                xid = gdkwin.get_xid()
                d = x11.XOpenDisplay(None)
                if d:
                    wm_protocols_atom = x11.XInternAtom(d, b'WM_PROTOCOLS', False)
                    wm_take_focus_atom = x11.XInternAtom(d, b'WM_TAKE_FOCUS', False)
                    actual_type = ctypes.c_ulong()
                    actual_format = ctypes.c_int()
                    nitems = ctypes.c_ulong()
                    bytes_after = ctypes.c_ulong()
                    prop = ctypes.c_void_p()
                    if x11.XGetWindowProperty(d, xid, wm_protocols_atom, 0, 100, False, 4,
                                              ctypes.byref(actual_type), ctypes.byref(actual_format),
                                              ctypes.byref(nitems), ctypes.byref(bytes_after),
                                              ctypes.byref(prop)) == 0 and prop.value:
                        atoms = (ctypes.c_ulong * nitems.value).from_address(prop.value)
                        clean_atoms = [a for a in atoms if a != wm_take_focus_atom]
                        c_arr = (ctypes.c_ulong * len(clean_atoms))(*clean_atoms)
                        x11.XChangeProperty(d, xid, wm_protocols_atom, 4, 32, 0, c_arr, len(clean_atoms))
                        x11.XFree(prop)
                        x11.XFlush(d)
                    x11.XCloseDisplay(d)
        except Exception:
            pass
        return False

    def on_update_geometry(self, ucm, js_result):
        try:
            data = json.loads(js_result.get_js_value().to_string())
            h = int(data.get('height', 0))
            rects = data.get('rects', [])
            if h <= 0 or not rects:
                self.hide()
                return

            target_h = min(max(h, 60), self.max_height)
            self.current_height = target_h
            self.resize(self.win_width, target_h)
            gdkwin = self.get_window()
            if gdkwin:
                gdkwin.resize(self.win_width, target_h)
                
                # Apply X11 input shape: only the actual toast pills intercept mouse events
                # Everything else passes through to underlying windows!
                region = cairo.Region()
                for r in rects:
                    rx = int(r.get('x', 0))
                    ry = int(r.get('y', 0))
                    rw = int(r.get('w', 0))
                    rh = int(r.get('h', 0))
                    if rw > 0 and rh > 0:
                        region.union(cairo.RectangleInt(rx, ry, rw, rh))
                if region.num_rectangles() > 0:
                    gdkwin.input_shape_combine_region(region, 0, 0)
        except Exception:
            pass

    def on_window_state(self, ucm, js_result):
        state = js_result.get_js_value().to_string()
        if state == "empty":
            self.active_count = 0
            self.hide()
            try:
                import gc
                gc.collect()
                ctypes.CDLL("libc.so.6").malloc_trim(0)
            except Exception:
                pass
        elif state == "active":
            self.active_count += 1
            if not self.get_visible():
                self.show_all()
                self.set_keep_above(True)
                self.move(self.pos_x, self.pos_y)

    def on_notification_closed(self, ucm, js_result):
        try:
            data = json.loads(js_result.get_js_value().to_string())
            nid = int(data.get('id', 0))
            reason = int(data.get('reason', 2))
            if self.server and nid > 0:
                self.server.NotificationClosed(nid, reason)
        except Exception:
            pass

    def on_action_invoked(self, ucm, js_result):
        try:
            data = json.loads(js_result.get_js_value().to_string())
            nid = int(data.get('id', 0))
            action = str(data.get('action', 'default'))
            if self.server and nid > 0:
                self.server.ActionInvoked(nid, action)
        except Exception:
            pass

    def show_toast(self, notif_data):
        if not self.get_visible():
            self.show_all()
            self.set_keep_above(True)
            self.move(self.pos_x, self.pos_y)
        js_code = f"addNotification({json.dumps(notif_data)});"
        self.webview.run_javascript(js_code)

    def dismiss_toast(self, nid, reason=3):
        js_code = f"dismissToast({nid}, {reason});"
        self.webview.run_javascript(js_code)


class NotificationServer(dbus.service.Object):
    def __init__(self, bus, win):
        self.bus_name = dbus.service.BusName(
            'org.freedesktop.Notifications',
            bus=bus,
            allow_replacement=True,
            replace_existing=True,
            do_not_queue=True
        )
        super().__init__(self.bus_name, '/org/freedesktop/Notifications')
        self.win = win
        self.win.server = self
        self.next_id = 1
        self.icon_theme = Gtk.IconTheme.get_default()
        try:
            self.notif_settings = Gio.Settings(schema="org.cinnamon.desktop.notifications")
        except Exception:
            self.notif_settings = None

    def file_to_data_uri(self, file_path):
        if not file_path or not os.path.exists(file_path):
            return ""
        try:
            if file_path.endswith('.svg'):
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                return "data:image/svg+xml;utf8," + urllib.parse.quote(content)
            else:
                ext = 'png' if file_path.endswith('.png') else 'jpeg'
                with open(file_path, 'rb') as f:
                    b64 = base64.b64encode(f.read()).decode('utf-8')
                return f"data:image/{ext};base64,{b64}"
        except Exception:
            return f"file://{file_path}"

    def resolve_icon(self, nid, app_icon, app_name, hints):
        # 1. Check for raw image data in hints
        for key in ('image-data', 'image_data', 'icon_data'):
            if key in hints:
                try:
                    data = hints[key]
                    w, h, rowstride, has_alpha, bps, ch, img_bytes = data
                    pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(
                        GLib.Bytes.new(bytes(img_bytes)),
                        GdkPixbuf.Colorspace.RGB,
                        bool(has_alpha),
                        int(bps),
                        int(w),
                        int(h),
                        int(rowstride)
                    )
                    dest = f"/tmp/bento-toast-{nid}.png"
                    pixbuf.savev(dest, "png", [], [])
                    return self.file_to_data_uri(dest), True
                except Exception:
                    pass

        # 2. Check for image path hint
        for key in ('image-path', 'image_path'):
            if key in hints:
                p = str(hints[key]).replace('file://', '')
                if os.path.exists(p):
                    return self.file_to_data_uri(p), True

        # 3. Check app_icon string
        if app_icon:
            clean_icon = app_icon.replace('file://', '')
            if os.path.exists(clean_icon):
                return self.file_to_data_uri(clean_icon), True
            # System icon lookup
            info = self.icon_theme.lookup_icon(app_icon, 48, 0)
            if info:
                return self.file_to_data_uri(info.get_filename()), False

        # 4. Fallback to app_name lookup
        if app_name:
            info = self.icon_theme.lookup_icon(app_name.lower(), 48, 0)
            if info:
                return self.file_to_data_uri(info.get_filename()), False

        # 5. Default generic status icon
        info = self.icon_theme.lookup_icon("dialog-information", 48, 0)
        if info:
            return self.file_to_data_uri(info.get_filename()), False

        return "", False

    @dbus.service.method("org.freedesktop.Notifications", in_signature="susssasa{sv}i", out_signature="u")
    def Notify(self, app_name, replaces_id, app_icon, summary, body, actions, hints, expire_timeout):
        nid = int(replaces_id) if int(replaces_id) > 0 else self.next_id
        if nid == self.next_id:
            self.next_id += 1

        # Check Cinnamon Do Not Disturb setting
        if self.notif_settings is not None:
            try:
                display_notifications = self.notif_settings.get_boolean("display-notifications")
                urgency = int(hints.get('urgency', 1))
                if not display_notifications and urgency < 2:
                    # DND is active: suppress popups and sounds for non-critical notifications
                    return dbus.UInt32(nid)
            except Exception:
                pass

        app_name_str = str(app_name) if app_name else "Notification"
        summary_str = str(summary) if summary else ""
        body_str = str(body) if body else ""
        timeout_ms = int(expire_timeout) if int(expire_timeout) > 0 else 5000

        icon_data_uri, is_large = self.resolve_icon(nid, str(app_icon), app_name_str, hints)
        act_list = [str(a) for a in actions]

        notif_data = {
            "id": nid,
            "app_name": app_name_str,
            "summary": summary_str,
            "body": body_str,
            "icon": icon_data_uri,
            "is_image": is_large,
            "actions": act_list,
            "has_default_action": "default" in act_list,
            "timeout": timeout_ms
        }

        # Show toast in window
        GLib.idle_add(lambda: self.win.show_toast(notif_data))

        # Play notification sound if enabled
        try:
            sound_file = "/usr/share/mint-artwork/sounds/notification.oga"
            if os.path.exists(sound_file) and not bool(hints.get('suppress-sound', False)):
                subprocess.Popen(['paplay', sound_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

        return dbus.UInt32(nid)

    @dbus.service.method("org.freedesktop.Notifications", in_signature="u", out_signature="")
    def CloseNotification(self, id):
        nid = int(id)
        GLib.idle_add(lambda: self.win.dismiss_toast(nid, 3))
        self.NotificationClosed(nid, 3)

    @dbus.service.method("org.freedesktop.Notifications", in_signature="", out_signature="as")
    def GetCapabilities(self):
        return dbus.Array([
            'actions',
            'body',
            'body-hyperlinks',
            'body-markup',
            'icon-static',
            'persistence',
            'sound'
        ], signature='s')

    @dbus.service.method("org.freedesktop.Notifications", in_signature="", out_signature="ssss")
    def GetServerInformation(self):
        return ('Bento Toast', 'Bento', '1.0', '1.2')

    @dbus.service.signal("org.freedesktop.Notifications", signature="uu")
    def NotificationClosed(self, id, reason):
        pass

    @dbus.service.signal("org.freedesktop.Notifications", signature="us")
    def ActionInvoked(self, id, action_key):
        pass


def main():
    bus = dbus.SessionBus()
    win = ToastWindow()
    server = NotificationServer(bus, win)
    
    # Hide window initially until first notification
    win.hide()
    
    Gtk.main()

if __name__ == "__main__":
    main()
