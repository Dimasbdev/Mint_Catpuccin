#!/usr/bin/env python3
import os, sys, time, json, socket, subprocess, re, getpass, threading
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('WebKit2', '4.1')
from gi.repository import Gtk, Gdk, WebKit2, GLib

try:
    import dbus
    import dbus.mainloop.glib
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
except ImportError:
    dbus = None

SOCKET_PATH = f"/tmp/caelestia-control-{os.getuid()}.sock"
DATA_DIR = os.path.expanduser("~/.local/share/caelestia-control")

class CaelestiaControlWindow(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("CaelestiaControlCenter")
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

        self.win_width = 420
        self.win_height = 620
        self.set_default_size(self.win_width, self.win_height)
        self.reposition_window()

        ucm = WebKit2.UserContentManager()
        ucm.register_script_message_handler("control")
        ucm.connect("script-message-received::control", self.on_control_message)

        settings = WebKit2.Settings()
        settings.set_enable_developer_extras(False)
        settings.set_enable_javascript(True)
        settings.set_allow_file_access_from_file_urls(True)
        settings.set_allow_universal_access_from_file_urls(True)
        settings.set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.ALWAYS)
        settings.set_enable_smooth_scrolling(True)

        self.webview = WebKit2.WebView.new_with_user_content_manager(ucm)
        self.webview.set_settings(settings)
        self.webview.set_background_color(Gdk.RGBA(0.0, 0.0, 0.0, 0.0))
        self.webview.connect("context-menu", lambda *args: True)
        self.webview.connect("load-changed", self.on_webview_load_changed)

        html_path = os.path.join(DATA_DIR, "index.html")
        self.webview.load_uri(f"file://{html_path}")

        self.add(self.webview)
        self.connect("key-press-event", self.on_key_press)
        self.connect("focus-out-event", self.on_focus_out)
        self.connect("destroy", Gtk.main_quit)

        self.is_visible = False
        self.current_user = getpass.getuser()

        if dbus:
            try:
                bus = dbus.SessionBus()
                bus.add_signal_receiver(
                    self.on_theme_changed,
                    signal_name="ThemeChanged",
                    dbus_interface="org.caelestia.Theme",
                    path="/org/caelestia/Theme"
                )
            except Exception as e:
                print(f"Theme signal subscribe error: {e}", file=sys.stderr)

    def reposition_window(self):
        screen = Gdk.Screen.get_default()
        geom = screen.get_monitor_geometry(0)
        x = geom.x + geom.width - self.win_width - 16
        y = geom.y + 46
        self.move(x, y)

    def on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.hide_popup()
            return True
        return False

    def on_focus_out(self, widget, event):
        if "--no-auto-hide" not in sys.argv and self.is_visible:
            self.hide_popup()
        return False

    def on_theme_changed(self, colors_path):
        GLib.idle_add(self.apply_theme_from_file, colors_path)

    def apply_theme_from_file(self, colors_path=None):
        path = colors_path or os.path.expanduser("~/.cache/caelestia/colors.json")
        if not os.path.exists(path):
            return
        try:
            with open(path, "r") as f:
                theme = json.load(f)
            pri = theme.get("primary", "#f5c2e7")
            sec = theme.get("secondary", "#cba6f7")
            subtle = theme.get("accent_subtle", "rgba(245, 194, 231, 0.14)")
            glow = f"rgba({theme.get('primary_rgb', '245, 194, 231')}, 0.35)"
            b_act = theme.get("border_active", "rgba(245, 194, 231, 0.45)")
            b_sub = theme.get("border_subtle", "rgba(245, 194, 231, 0.14)")
            js = f"""
            (function() {{
                const root = document.documentElement;
                root.style.setProperty('--flamingo', '{pri}');
                root.style.setProperty('--pink', '{pri}');
                root.style.setProperty('--accent', '{pri}');
                root.style.setProperty('--accent-subtle', '{subtle}');
                root.style.setProperty('--accent-glow', '{glow}');
                root.style.setProperty('--mauve', '{sec}');
                root.style.setProperty('--border-active', '{b_act}');
                root.style.setProperty('--border-subtle', '{b_sub}');
            }})();
            """
            self.webview.run_javascript(js)
        except Exception as e:
            print(f"Error applying theme in control: {e}", file=sys.stderr)

    def on_webview_load_changed(self, webview, load_event):
        if load_event == WebKit2.LoadEvent.FINISHED:
            self.apply_theme_from_file()
        if load_event == WebKit2.LoadEvent.FINISHED:
            self.push_state()

    def start_poll_timer(self):
        def poll():
            if self.is_visible:
                self.push_state()
                return True
            return False
        GLib.timeout_add(2500, poll)

    def show_popup(self):
        self.stick()
        self.set_keep_above(True)
        self.reposition_window()
        self.is_visible = True
        self.apply_theme_from_file()
        self.show_all()
        self.present()
        self.grab_focus()
        self.webview.grab_focus()
        self.push_state()
        GLib.timeout_add(150, self.push_state)
        self.start_poll_timer()

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

    def get_system_state(self):
        # 1. Volume & Mute
        vol = 50
        muted = False
        try:
            out = subprocess.check_output(['pactl', 'get-sink-volume', '@DEFAULT_SINK@'], text=True, stderr=subprocess.DEVNULL)
            m = re.search(r'(\d+)%', out)
            if m: vol = int(m.group(1))
            out_m = subprocess.check_output(['pactl', 'get-sink-mute', '@DEFAULT_SINK@'], text=True, stderr=subprocess.DEVNULL)
            muted = 'yes' in out_m.lower()
        except Exception:
            pass

        # 2. Brightness
        brightness = 100
        if dbus:
            try:
                bus = dbus.SessionBus()
                obj = bus.get_object('org.cinnamon.SettingsDaemon.Power', '/org/cinnamon/SettingsDaemon/Power')
                iface = dbus.Interface(obj, 'org.cinnamon.SettingsDaemon.Power.Screen')
                brightness = int(iface.GetPercentage())
            except Exception:
                pass

        # 3. Wi-Fi
        wifi_enabled = False
        wifi_ssid = "Disconnected"
        try:
            out = subprocess.check_output(['nmcli', 'radio', 'wifi'], text=True, stderr=subprocess.DEVNULL).strip()
            wifi_enabled = (out == 'enabled')
            if wifi_enabled:
                try:
                    ssid_out = subprocess.check_output(['iwgetid', '-r'], text=True, stderr=subprocess.DEVNULL).strip()
                except Exception:
                    ssid_out = ''
                if ssid_out:
                    wifi_ssid = ssid_out
                else:
                    devs = subprocess.check_output(['nmcli', '-t', '-f', 'DEVICE,TYPE,STATE,CONNECTION', 'dev'], text=True, stderr=subprocess.DEVNULL).strip()
                    for line in devs.splitlines():
                        parts = line.split(':')
                        if len(parts) >= 4 and parts[1] == 'wifi':
                            dev_state = parts[2]
                            conn_name = parts[3]
                            if dev_state == 'connected' and conn_name:
                                wifi_ssid = conn_name
                                break
                            elif 'connecting' in dev_state:
                                wifi_ssid = "Connecting..."
                                break
                            elif dev_state == 'disconnected':
                                wifi_ssid = "Disconnected"
        except Exception:
            pass

        # 4. Bluetooth
        bt_enabled = False
        try:
            out = subprocess.check_output(['bluetoothctl', 'show'], text=True, stderr=subprocess.DEVNULL)
            bt_enabled = 'Powered: yes' in out
        except Exception:
            pass

        # 5. Night Light
        night_light = False
        try:
            out = subprocess.check_output(['xgamma'], text=True, stderr=subprocess.STDOUT)
            m = re.search(r'Blue\s+([0-9.]+)', out)
            if m and float(m.group(1)) < 0.95:
                night_light = True
        except Exception:
            pass

        # 6. Do Not Disturb
        dnd = False
        try:
            out = subprocess.check_output(['gsettings', 'get', 'org.cinnamon.desktop.notifications', 'display-notifications'], text=True, stderr=subprocess.DEVNULL).strip()
            dnd = (out == 'false')
        except Exception:
            pass

        # 7. Battery & Temp
        bat_pct = 80
        is_charging = False
        try:
            bats = [b for b in os.listdir('/sys/class/power_supply') if b.startswith('BAT')]
            tot_now, tot_full = 0, 0
            for b in bats:
                p = f'/sys/class/power_supply/{b}'
                try:
                    with open(f'{p}/energy_now') as f: tot_now += int(f.read().strip())
                    with open(f'{p}/energy_full') as f: tot_full += int(f.read().strip())
                except Exception:
                    try:
                        with open(f'{p}/charge_now') as f: tot_now += int(f.read().strip())
                        with open(f'{p}/charge_full') as f: tot_full += int(f.read().strip())
                    except Exception:
                        pass
                try:
                    with open(f'{p}/status') as f:
                        if f.read().strip() in ('Charging', 'Full'):
                            is_charging = True
                except Exception:
                    pass
            if tot_full > 0:
                bat_pct = round((tot_now / tot_full) * 100)
        except Exception:
            pass

        cpu_temp = 50
        try:
            for t_path in ('/sys/class/hwmon/hwmon9/temp1_input', '/sys/class/thermal/thermal_zone0/temp'):
                if os.path.exists(t_path):
                    with open(t_path, 'r') as f:
                        val = int(f.read().strip())
                        cpu_temp = round(val / 1000 if val > 1000 else val)
                        break
        except Exception:
            pass

        # 8. MPRIS Media
        media = {
            "active": False,
            "title": "No Media Playing",
            "artist": "Music is idle",
            "art": "",
            "status": "Stopped"
        }
        if dbus:
            try:
                bus = dbus.SessionBus()
                players = [name for name in bus.list_names() if name.startswith('org.mpris.MediaPlayer2')]
                for p in players:
                    obj = bus.get_object(p, '/org/mpris/MediaPlayer2')
                    props = dbus.Interface(obj, 'org.freedesktop.DBus.Properties')
                    try:
                        p_status = str(props.Get('org.mpris.MediaPlayer2.Player', 'PlaybackStatus'))
                        metadata = props.Get('org.mpris.MediaPlayer2.Player', 'Metadata')
                        title = str(metadata.get('xesam:title', ''))
                        artist_val = metadata.get('xesam:artist', [''])
                        artist = str(artist_val[0] if artist_val else '')
                        art = str(metadata.get('mpris:artUrl', ''))
                        if title:
                            media = {
                                "active": True,
                                "title": title,
                                "artist": artist,
                                "art": art,
                                "status": p_status
                            }
                            if p_status == "Playing":
                                break
                    except Exception:
                        continue
            except Exception:
                pass

        return {
            "user": f"{self.current_user}@t480",
            "volume": vol,
            "muted": muted,
            "brightness": brightness,
            "wifi": {
                "enabled": wifi_enabled,
                "ssid": wifi_ssid
            },
            "bluetooth": {
                "enabled": bt_enabled
            },
            "night_light": night_light,
            "dnd": dnd,
            "battery": {
                "pct": bat_pct,
                "charging": is_charging,
                "temp": cpu_temp
            },
            "media": media
        }

    def push_state(self):
        def worker():
            try:
                state = self.get_system_state()
                js_code = f"if (window.updateControlCenter) {{ window.updateControlCenter({json.dumps(state)}); }}"
                GLib.idle_add(lambda: self.webview.run_javascript(js_code))
            except Exception as e:
                print("push_state error:", e)
        threading.Thread(target=worker, daemon=True).start()

    def on_control_message(self, ucm, js_result):
        val = js_result.get_js_value()
        try:
            data = json.loads(val.to_string())
            action = data.get("action")
            value = data.get("value")

            if action in ("ready", "refresh"):
                self.push_state()
                return
            elif action == "set_volume":
                pct = max(0, min(100, int(value)))
                subprocess.run(['pactl', 'set-sink-volume', '@DEFAULT_SINK@', f'{pct}%'], stderr=subprocess.DEVNULL)
            elif action == "toggle_mute":
                subprocess.run(['pactl', 'set-sink-mute', '@DEFAULT_SINK@', 'toggle'], stderr=subprocess.DEVNULL)
            elif action == "set_brightness":
                pct = max(5, min(100, int(value)))
                if dbus:
                    try:
                        bus = dbus.SessionBus()
                        obj = bus.get_object('org.cinnamon.SettingsDaemon.Power', '/org/cinnamon/SettingsDaemon/Power')
                        iface = dbus.Interface(obj, 'org.cinnamon.SettingsDaemon.Power.Screen')
                        iface.SetPercentage(pct)
                    except Exception:
                        pass
            elif action == "toggle_wifi":
                state = self.get_system_state()
                new_state = "off" if state["wifi"]["enabled"] else "on"
                subprocess.run(['nmcli', 'radio', 'wifi', new_state], stderr=subprocess.DEVNULL)
            elif action == "toggle_bluetooth":
                state = self.get_system_state()
                new_state = "off" if state["bluetooth"]["enabled"] else "on"
                subprocess.run(['bluetoothctl', 'power', new_state], stderr=subprocess.DEVNULL)
            elif action == "toggle_nightlight":
                state = self.get_system_state()
                if state["night_light"]:
                    subprocess.run(['xgamma', '-rgamma', '1.0', '-ggamma', '1.0', '-bgamma', '1.0'], stderr=subprocess.DEVNULL)
                    subprocess.run(['gsettings', 'set', 'org.cinnamon.settings-daemon.plugins.color', 'night-light-enabled', 'false'], stderr=subprocess.DEVNULL)
                    subprocess.run(['gsettings', 'set', 'org.cinnamon.settings-daemon.plugins.color', 'night-light-schedule-mode', 'auto'], stderr=subprocess.DEVNULL)
                else:
                    subprocess.run(['xgamma', '-rgamma', '1.0', '-ggamma', '0.82', '-bgamma', '0.62'], stderr=subprocess.DEVNULL)
                    subprocess.run(['gsettings', 'set', 'org.cinnamon.settings-daemon.plugins.color', 'night-light-schedule-mode', 'always'], stderr=subprocess.DEVNULL)
                    subprocess.run(['gsettings', 'set', 'org.cinnamon.settings-daemon.plugins.color', 'night-light-enabled', 'true'], stderr=subprocess.DEVNULL)
            elif action == "toggle_dnd":
                state = self.get_system_state()
                # If currently dnd (display-notifications=false), toggle to normal (display-notifications=true)
                new_state = "true" if state["dnd"] else "false"
                subprocess.run(['gsettings', 'set', 'org.cinnamon.desktop.notifications', 'display-notifications', new_state], stderr=subprocess.DEVNULL)
            elif action == "media":
                self.handle_media_action(value)
            elif action == "action_screenshot":
                self.hide_popup()
                def run_ss():
                    time.sleep(0.25)
                    subprocess.Popen(['gnome-screenshot', '-a'])
                threading.Thread(target=run_ss, daemon=True).start()
            elif action == "action_autotile":
                self.hide_popup()
                subprocess.Popen([os.path.expanduser('~/.local/bin/cinnamon-autotile.py')])
            elif action == "action_clipboard":
                self.hide_popup()
                subprocess.Popen([os.path.expanduser('~/.local/bin/caelestia-clip')])
            elif action == "action_lock":
                self.hide_popup()
                subprocess.Popen([os.path.expanduser('~/.local/bin/caelestia-lock')])
            elif action == "close":
                self.hide_popup()

            # Refresh state in UI after action
            GLib.timeout_add(100, self.push_state)
        except Exception as e:
            print("Control message error:", e)

    def handle_media_action(self, action):
        if not dbus:
            return
        try:
            bus = dbus.SessionBus()
            players = [name for name in bus.list_names() if name.startswith('org.mpris.MediaPlayer2')]
            for p in players:
                obj = bus.get_object(p, '/org/mpris/MediaPlayer2')
                player = dbus.Interface(obj, 'org.mpris.MediaPlayer2.Player')
                try:
                    if action in ('play_pause', 'PlayPause'):
                        player.PlayPause()
                    elif action in ('next', 'Next'):
                        player.Next()
                    elif action in ('prev', 'Previous'):
                        player.Previous()
                    break
                except Exception:
                    continue
        except Exception:
            pass

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
    win = CaelestiaControlWindow()
    srv = setup_socket_server(win)
    win.show_popup()
    Gtk.main()

if __name__ == "__main__":
    main()
