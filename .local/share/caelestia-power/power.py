#!/usr/bin/env python3
import os, sys, time, json, socket, subprocess, getpass
import gi
try:
    import dbus
    import dbus.mainloop.glib
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
except ImportError:
    dbus = None
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('WebKit2', '4.1')
from gi.repository import Gtk, Gdk, WebKit2, GLib

SOCKET_PATH = f"/tmp/caelestia-power-{os.getuid()}.sock"
DATA_DIR = os.path.expanduser("~/.local/share/caelestia-power")

def get_uptime_str():
    try:
        out = subprocess.check_output(['uptime', '-p'], text=True, stderr=subprocess.DEVNULL).strip()
        return out
    except Exception:
        return "up"

class CaelestiaPowerWindow(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("CaelestiaPowerMenu")
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.stick()

        self.set_app_paintable(True)
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        geom = screen.get_monitor_geometry(0)
        self.move(geom.x, geom.y)
        self.set_default_size(geom.width, geom.height)
        self.fullscreen()

        ucm = WebKit2.UserContentManager()
        ucm.register_script_message_handler("power")
        ucm.connect("script-message-received::power", self.on_power_message)

        settings = WebKit2.Settings()
        settings.set_enable_developer_extras(False)
        settings.set_enable_javascript(True)
        settings.set_allow_file_access_from_file_urls(True)
        settings.set_allow_universal_access_from_file_urls(True)
        settings.set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.ALWAYS)

        self.webview = WebKit2.WebView.new_with_user_content_manager(ucm)
        self.webview.set_settings(settings)
        self.webview.set_background_color(Gdk.RGBA(0.0, 0.0, 0.0, 0.0))
        self.webview.connect("context-menu", lambda *args: True)

        html_path = os.path.join(DATA_DIR, "index.html")
        self.webview.load_uri(f"file://{html_path}")

        self.add(self.webview)
        self.connect("key-press-event", self.on_key_press)
        self.connect("destroy", Gtk.main_quit)

        self.is_visible = False
        if dbus:
            try:
                bus = dbus.SessionBus()
                bus.add_signal_receiver(
                    self.on_theme_changed,
                    signal_name="ThemeChanged",
                    dbus_interface="org.caelestia.Theme",
                    path="/org/caelestia/Theme"
                )
            except Exception:
                pass
        self.current_user = getpass.getuser()

    def on_theme_changed(self, colors_path):
        GLib.idle_add(self.apply_theme_from_file, colors_path)

    def apply_theme_from_file(self, colors_path=None):
        path = colors_path or os.path.expanduser("~/.cache/caelestia/colors.json")
        if not os.path.exists(path):
            return
        try:
            with open(path, "r") as f:
                theme = json.load(f)
            js = f"""
            (function() {{
                const root = document.documentElement;
                root.style.setProperty('--flamingo', '{theme['primary']}');
                root.style.setProperty('--pink', '{theme['primary']}');
                root.style.setProperty('--mauve', '{theme['secondary']}');
                root.style.setProperty('--border-active', '{theme['border_active']}');
                root.style.setProperty('--border-subtle', '{theme['border_subtle']}');
            }})();
            """
            self.webview.run_javascript(js)
        except Exception:
            pass

    def on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.hide_popup()
            return True
        return False

    def show_popup(self):
        self.stick()
        self.set_keep_above(True)
        self.fullscreen()
        self.is_visible = True
        self.apply_theme_from_file()
        self.show_all()
        self.present()
        self.grab_focus()
        self.webview.grab_focus()

        # Push user & uptime details
        details = {
            "user": f"{self.current_user}@t480",
            "uptime": get_uptime_str()
        }
        js_code = f"if (window.updatePowerDetails) {{ updatePowerDetails({json.dumps(details)}); }}"
        self.webview.run_javascript(js_code)

    def hide_popup(self):
        self.is_visible = False
        self.hide()
        Gdk.flush()
        if os.path.exists(SOCKET_PATH):
            try:
                os.unlink(SOCKET_PATH)
            except OSError:
                pass
        Gtk.main_quit()

    def toggle_popup(self):
        if self.is_visible:
            self.hide_popup()
        else:
            self.show_popup()

    def on_power_message(self, ucm, js_result):
        val = js_result.get_js_value()
        try:
            data = json.loads(val.to_string())
            action = data.get("action")

            if action == "lock":
                self.hide_popup()
                subprocess.Popen([os.path.expanduser('~/.local/bin/caelestia-lock')])
            elif action == "logout":
                self.hide_popup()
                subprocess.run(['cinnamon-session-quit', '--logout', '--no-prompt'])
            elif action == "suspend":
                self.hide_popup()
                subprocess.run(['systemctl', 'suspend'])
            elif action == "hibernate":
                self.hide_popup()
                subprocess.run(['systemctl', 'hibernate'])
            elif action == "reboot":
                self.hide_popup()
                subprocess.run(['cinnamon-session-quit', '--reboot', '--no-prompt'])
            elif action == "shutdown":
                self.hide_popup()
                subprocess.run(['cinnamon-session-quit', '--power-off', '--no-prompt'])
            elif action == "close":
                self.hide_popup()
        except Exception as e:
            print("Power message error:", e)

def setup_socket_server(win):
    if os.path.exists(SOCKET_PATH):
        try:
            os.unlink(SOCKET_PATH)
        except OSError:
            pass

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.setblocking(False)
    srv.bind(SOCKET_PATH)
    srv.listen(10)

    def on_sock_event(source, condition):
        try:
            conn, _ = srv.accept()
            msg = conn.recv(1024).decode().strip()
            if msg == "toggle":
                win.toggle_popup()
            elif msg == "show":
                win.show_popup()
            elif msg == "hide":
                win.hide_popup()
            conn.close()
        except Exception:
            pass
        return True

    GLib.io_add_watch(srv.fileno(), GLib.IOCondition.IN, on_sock_event)
    return srv

def main():
    win = CaelestiaPowerWindow()
    srv = setup_socket_server(win)
    win.show_popup()
    Gtk.main()

if __name__ == "__main__":
    main()
