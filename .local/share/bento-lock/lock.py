#!/usr/bin/env python3
import os, sys, getpass, time, ctypes, ctypes.util, threading, json, urllib.request, subprocess, shutil, socket, gc
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

SOCKET_PATH = f"/tmp/bento-lock-{os.getuid()}.sock"

# --- High-Performance PAM Authentication ---
libpam = ctypes.CDLL(ctypes.util.find_library('pam') or 'libpam.so.0')
libc = ctypes.CDLL(ctypes.util.find_library('c') or 'libc.so.6')

class PamMessage(ctypes.Structure):
    _fields_ = [('msg_style', ctypes.c_int), ('msg', ctypes.c_char_p)]

class PamResponse(ctypes.Structure):
    _fields_ = [('resp', ctypes.c_char_p), ('resp_retcode', ctypes.c_int)]

conv_func = ctypes.CFUNCTYPE(
    ctypes.c_int,
    ctypes.c_int,
    ctypes.POINTER(ctypes.POINTER(PamMessage)),
    ctypes.POINTER(ctypes.POINTER(PamResponse)),
    ctypes.c_void_p
)

class PamConv(ctypes.Structure):
    _fields_ = [('conv', conv_func), ('appdata_ptr', ctypes.c_void_p)]

def authenticate_user(username, password):
    def conv(n_messages, messages, p_response, appdata):
        size = ctypes.sizeof(PamResponse) * n_messages
        resp_mem = libc.malloc(size)
        ctypes.memset(resp_mem, 0, size)
        resp_array = ctypes.cast(resp_mem, ctypes.POINTER(PamResponse))
        
        for i in range(n_messages):
            msg = messages[i].contents
            if msg.msg_style in (1, 2):
                resp_array[i].resp = libc.strdup(password.encode('utf-8'))
                resp_array[i].resp_retcode = 0
            else:
                resp_array[i].resp = None
                resp_array[i].resp_retcode = 0
        p_response[0] = resp_array
        return 0

    c_conv = PamConv(conv_func(conv), None)
    pamh = ctypes.c_void_p()
    ret = libpam.pam_start(b'cinnamon-screensaver', username.encode('utf-8'), ctypes.byref(c_conv), ctypes.byref(pamh))
    if ret != 0:
        ret = libpam.pam_start(b'login', username.encode('utf-8'), ctypes.byref(c_conv), ctypes.byref(pamh))
        if ret != 0:
            return False
            
    ret = libpam.pam_authenticate(pamh, 0)
    libpam.pam_end(pamh, ret)
    return ret == 0

def get_current_wallpaper():
    try:
        out = subprocess.check_output(['gsettings', 'get', 'org.cinnamon.desktop.background', 'picture-uri'], text=True).strip()
        wp = out.strip("'").replace("file://", "")
        if os.path.exists(wp):
            return wp
    except Exception:
        pass
    default_wp = "/home/df/Pictures/Wallpapers/workspace-1.jpg"
    if os.path.exists(default_wp):
        return default_wp
    return "/home/df/Pictures/Wallpapers/workspace-4.jpg"

cached_weather = {
    "temp": "28°C",
    "status": "Partly Cloudy",
    "feels": "Feels like 29°C"
}

def fetch_weather_thread():
    global cached_weather
    try:
        req = urllib.request.Request('https://wttr.in/?format=j1', headers={'User-Agent': 'curl/7.88.1'})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode())
            curr = data['current_condition'][0]
            temp_c = curr['temp_C'] + "°C"
            desc = curr['weatherDesc'][0]['value']
            feels_c = "Feels like " + curr['FeelsLikeC'] + "°C"
            cached_weather = {
                "temp": temp_c,
                "status": desc,
                "feels": feels_c
            }
    except Exception:
        pass

class BentoLockWindow(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("Lockscreen")
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.SPLASHSCREEN)
        
        self.set_app_paintable(True)
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
            
        self.stick()
        self.fullscreen()
        
        self.has_grab = False
        self.grab_timer_id = None
        self.connect("grab-broken-event", self.on_grab_broken)
        self.connect("window-state-event", self.on_window_state_event)
        self.connect("focus-out-event", self.on_focus_out)
        
        ucm = WebKit2.UserContentManager()
        ucm.register_script_message_handler("auth")
        ucm.connect("script-message-received::auth", self.on_auth_message)

        ucm.register_script_message_handler("media")
        ucm.connect("script-message-received::media", self.on_media_message)
        
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
        
        html_path = os.path.expanduser("~/.local/share/bento-lock/index.html")
        self.webview.load_uri(f"file://{html_path}")
        self.webview.connect("context-menu", lambda *args: True)
        self.webview.connect("load-changed", self.on_webview_load_changed)
        
        self.add(self.webview)
        if dbus:
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
        self.connect("destroy", Gtk.main_quit)
        self.connect("key-press-event", self.on_key_press)
        
        self.current_user = getpass.getuser()
        self.prev_cpu_stat = None
        self.stats_timer_id = None
        self.is_locked = False
        self._last_art_url = None
        self._art_cache_path = f"/tmp/bento-album-art-{os.getuid()}.jpg"
        self._art_cache_time = 0

        if dbus:
            try:
                bus = dbus.SessionBus()
                bus.add_signal_receiver(
                    self.on_mpris_signal,
                    dbus_interface="org.freedesktop.DBus.Properties",
                    signal_name="PropertiesChanged",
                    path="/org/mpris/MediaPlayer2"
                )
            except Exception:
                pass
        
        t = threading.Thread(target=fetch_weather_thread, daemon=True)
        t.start()

    def acquire_grab(self):
        if not self.is_locked:
            return False
        gdk_win = self.get_window()
        if not gdk_win or not gdk_win.is_viewable():
            return True
        
        seat = Gdk.Display.get_default().get_default_seat()
        status = seat.grab(gdk_win, Gdk.SeatCapabilities.KEYBOARD, False, None, None, None)
        if status == Gdk.GrabStatus.SUCCESS:
            self.has_grab = True
            self.grab_timer_id = None
            return False
        return True

    def release_grab(self):
        if self.grab_timer_id:
            GLib.source_remove(self.grab_timer_id)
            self.grab_timer_id = None
        if self.has_grab:
            try:
                seat = Gdk.Display.get_default().get_default_seat()
                seat.ungrab()
            except Exception:
                pass
            self.has_grab = False

    def on_grab_broken(self, widget, event):
        self.has_grab = False
        if self.is_locked and not self.grab_timer_id:
            self.grab_timer_id = GLib.timeout_add(20, self.acquire_grab)
        return False

    def on_focus_out(self, widget, event):
        if self.is_locked:
            self.present()
            self.grab_focus()
            self.webview.grab_focus()
            if not self.has_grab and not self.grab_timer_id:
                self.grab_timer_id = GLib.timeout_add(20, self.acquire_grab)
        return False

    def on_window_state_event(self, widget, event):
        if self.is_locked:
            if event.new_window_state & Gdk.WindowState.ICONIFIED:
                self.deiconify()
            if not (event.new_window_state & Gdk.WindowState.FULLSCREEN):
                self.fullscreen()
            if not (event.new_window_state & Gdk.WindowState.ABOVE):
                self.set_keep_above(True)
            if not (event.new_window_state & Gdk.WindowState.STICKY):
                self.stick()
        return False

    def on_webview_load_changed(self, webview, event):
        if event == WebKit2.LoadEvent.FINISHED:
            self.apply_theme_from_file()
            if self.is_locked:
                wp = get_current_wallpaper()
                self.webview.run_javascript(f"if (window.setWallpaper) setWallpaper('{wp}'); if (window.startLockSequence) startLockSequence();")

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
                root.style.setProperty('--border-active', '{theme['border_active']}');
                root.style.setProperty('--border-subtle', '{theme['border_subtle']}');
            }})();
            """
            self.webview.run_javascript(js)
        except Exception:
            pass

    def show_lockscreen(self):
        self.apply_theme_from_file()
        self.is_locked = True
        self.stick()
        self.set_keep_above(True)
        self.fullscreen()
        
        wp = get_current_wallpaper()
        self.webview.run_javascript(f"if (window.setWallpaper) setWallpaper('{wp}'); if (window.startLockSequence) startLockSequence();")
        
        self.show_all()
        self.present()
        self.grab_focus()
        self.webview.grab_focus()
        
        self.release_grab()
        if self.acquire_grab():
            self.grab_timer_id = GLib.timeout_add(20, self.acquire_grab)
        
        # Start live stats timer only while locked
        self.update_live_stats()
        if not self.stats_timer_id:
            self.stats_timer_id = GLib.timeout_add(1000, self.update_live_stats)

    def hide_lockscreen(self):
        self.is_locked = False
        self.release_grab()
        self.hide()
        Gdk.flush()
        
        if self.stats_timer_id:
            GLib.source_remove(self.stats_timer_id)
            self.stats_timer_id = None
            
        if os.path.exists(SOCKET_PATH):
            try:
                os.unlink(SOCKET_PATH)
            except OSError:
                pass
        Gtk.main_quit()

    def on_mpris_signal(self, *args, **kwargs):
        if self.is_locked:
            GLib.idle_add(self.push_media_update)

    def push_media_update(self):
        if not self.is_locked:
            return False
        media = self.get_mpris_media()
        payload = {"media": media}
        js_code = f"if (window.updateLiveDashboard) {{ updateLiveDashboard({json.dumps(payload)}); }}"
        self.webview.run_javascript(js_code)
        return False

    def resolve_art_url(self, art_url):
        if not art_url:
            return ""
        if art_url.startswith("file://"):
            return art_url
        if art_url.startswith("http://") or art_url.startswith("https://"):
            if self._last_art_url == art_url and os.path.exists(self._art_cache_path):
                return f"file://{self._art_cache_path}?t={int(self._art_cache_time)}"
            try:
                urllib.request.urlretrieve(art_url, self._art_cache_path)
                self._last_art_url = art_url
                self._art_cache_time = time.time()
                return f"file://{self._art_cache_path}?t={int(self._art_cache_time)}"
            except Exception:
                return art_url
        return art_url

    def get_mpris_media(self):
        media = {
            "active": False,
            "title": "No Media Playing",
            "artist": "Music is idle",
            "art": "",
            "status": "Stopped"
        }
        if not dbus:
            return media

        try:
            bus = dbus.SessionBus()
            players = [name for name in bus.list_names() if name.startswith('org.mpris.MediaPlayer2')]
            candidate = None

            for p in players:
                try:
                    obj = bus.get_object(p, '/org/mpris/MediaPlayer2')
                    props = dbus.Interface(obj, 'org.freedesktop.DBus.Properties')
                    p_status = str(props.Get('org.mpris.MediaPlayer2.Player', 'PlaybackStatus'))
                    metadata = props.Get('org.mpris.MediaPlayer2.Player', 'Metadata')

                    title = str(metadata.get('xesam:title', ''))
                    artist_val = metadata.get('xesam:artist', [''])
                    if isinstance(artist_val, (list, tuple, dbus.Array)):
                        artist = ', '.join(str(a) for a in artist_val if a)
                    else:
                        artist = str(artist_val) if artist_val else ''

                    art = str(metadata.get('mpris:artUrl', ''))

                    if title:
                        resolved_art = self.resolve_art_url(art)
                        m_data = {
                            "active": True,
                            "title": title,
                            "artist": artist if artist else "Unknown Artist",
                            "art": resolved_art,
                            "status": p_status
                        }
                        if p_status == "Playing":
                            return m_data
                        elif not candidate:
                            candidate = m_data
                except Exception:
                    continue

            if candidate:
                return candidate
        except Exception:
            pass

        return media

    def on_auth_message(self, ucm, js_result):
        val = js_result.get_js_value()
        msg = val.to_string()
        
        if msg == "unlock_complete":
            self.hide_lockscreen()
            return
            
        password = msg
        try:
            ok = authenticate_user(self.current_user, password)
        except Exception:
            ok = False
            
        if ok:
            self.webview.run_javascript("authSuccess();")
        else:
            self.webview.run_javascript("authFailed();")

    def on_key_press(self, widget, event):
        keyval = event.keyval
        if keyval in (Gdk.KEY_AudioPlay, Gdk.KEY_AudioPause):
            self.control_media('PlayPause')
            return True
        elif keyval == Gdk.KEY_AudioNext:
            self.control_media('Next')
            return True
        elif keyval == Gdk.KEY_AudioPrev:
            self.control_media('Previous')
            return True
        elif keyval == Gdk.KEY_AudioStop:
            self.control_media('Stop')
            return True
        elif keyval == Gdk.KEY_Escape:
            self.webview.run_javascript("const inp = document.getElementById('pwd-input'); if (inp) { inp.value = ''; inp.focus(); }")
            return True
        return False

    def on_media_message(self, ucm, js_result):
        val = js_result.get_js_value()
        action = val.to_string()
        self.control_media(action)

    def read_cpu_stat(self):
        try:
            with open("/proc/stat", "r") as f:
                fields = [float(x) for x in f.readline().split()[1:]]
            return (fields[3] + fields[4], sum(fields))
        except Exception:
            return (0.0, 0.0)

    def get_cpu_pct(self):
        idle, total = self.read_cpu_stat()
        if self.prev_cpu_stat:
            p_idle, p_total = self.prev_cpu_stat
            d_idle = idle - p_idle
            d_total = total - p_total
            self.prev_cpu_stat = (idle, total)
            if d_total > 0:
                return max(1, min(100, round((1.0 - (d_idle / d_total)) * 100)))
        time.sleep(0.04)
        i2, t2 = self.read_cpu_stat()
        d_idle = i2 - idle
        d_total = t2 - total
        self.prev_cpu_stat = (i2, t2)
        if d_total > 0:
            return max(1, min(100, round((1.0 - (d_idle / d_total)) * 100)))
        return 12

    def control_media(self, action):
        if not dbus:
            return
        try:
            bus = dbus.SessionBus()
            players = [name for name in bus.list_names() if name.startswith('org.mpris.MediaPlayer2')]
            for p in players:
                obj = bus.get_object(p, '/org/mpris/MediaPlayer2')
                try:
                    player = dbus.Interface(obj, 'org.mpris.MediaPlayer2.Player')
                    if action in ('play_pause', 'toggle_play', 'PlayPause'):
                        player.PlayPause()
                    elif action in ('next', 'Next'):
                        player.Next()
                    elif action in ('prev', 'previous', 'Previous'):
                        player.Previous()
                    elif action in ('stop', 'Stop'):
                        player.Stop()
                    
                    # Refresh live dashboard immediately
                    GLib.timeout_add(100, self.push_media_update)
                    break
                except Exception:
                    continue
        except Exception:
            pass

    def update_live_stats(self):
        if not self.is_locked:
            return False

        try:
            w_temp = cached_weather["temp"]
            w_stat = cached_weather["status"]
            w_feels = cached_weather["feels"]

            cpu_pct = self.get_cpu_pct()

            ram_pct = 30
            try:
                with open("/proc/meminfo", "r") as f:
                    lines = f.readlines()
                mem = {}
                for l in lines:
                    p = l.split(":")
                    if len(p) == 2:
                        mem[p[0].strip()] = int(p[1].strip().split()[0])
                total = mem.get("MemTotal", 1)
                avail = mem.get("MemAvailable", 0)
                ram_pct = round(((total - avail) / total) * 100)
            except Exception:
                pass

            laptop_temp = 50
            try:
                for t_path in ('/sys/class/hwmon/hwmon9/temp1_input', '/sys/class/thermal/thermal_zone0/temp'):
                    if os.path.exists(t_path):
                        with open(t_path, 'r') as f:
                            val = int(f.read().strip())
                            laptop_temp = round(val / 1000 if val > 1000 else val)
                            break
            except Exception:
                pass

            bat_pct = 80
            bat_status = "Discharging"
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
                bat_status = "Charging" if is_charging else "Discharging"
            except Exception:
                pass

            media = self.get_mpris_media()

            net_str = "Connected"
            try:
                out = subprocess.check_output(['iwgetid', '-r'], stderr=subprocess.DEVNULL).decode().strip()
                if out:
                    net_str = f"Wi-Fi: {out}"
                else:
                    out = subprocess.check_output(['nmcli', '-t', '-f', 'active,ssid', 'dev', 'wifi'], stderr=subprocess.DEVNULL).decode().strip()
                    for line in out.splitlines():
                        if line.startswith('yes:'):
                            net_str = f"Wi-Fi: {line.split(':')[1]}"
                            break
            except Exception:
                pass

            uptime_str = "1h"
            try:
                with open('/proc/uptime') as f:
                    secs = float(f.readline().split()[0])
                hrs = int(secs // 3600)
                mins = int((secs % 3600) // 60)
                uptime_str = f"{hrs}h {mins}m" if hrs else f"{mins}m"
            except Exception:
                pass

            disk_str = ""
            try:
                _, _, free = shutil.disk_usage('/')
                disk_str = f"{free // (2**30)} GB Free"
            except Exception:
                pass

            payload = {
                "weather": {
                    "temp": w_temp,
                    "status": w_stat,
                    "feels": w_feels
                },
                "hardware": {
                    "cpu": cpu_pct,
                    "ram": ram_pct,
                    "temp": laptop_temp,
                    "bat": bat_pct,
                    "bat_status": bat_status,
                    "is_charging": is_charging
                },
                "media": media,
                "system": {
                    "net": net_str,
                    "uptime": uptime_str,
                    "disk": disk_str
                }
            }

            js_code = f"if (window.updateLiveDashboard) {{ updateLiveDashboard({json.dumps(payload)}); }}"
            self.webview.run_javascript(js_code)
        except Exception as e:
            pass
        return True

def setup_glib_socket(win):
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
            if msg == "lock":
                win.show_lockscreen()
            elif msg == "unlock":
                win.hide_lockscreen()
            elif msg.startswith("wallpaper:"):
                new_wp = msg.split(":", 1)[1]
                if os.path.exists(new_wp):
                    win.webview.run_javascript(f"if (window.setWallpaper) setWallpaper('{new_wp}');")
            conn.close()
        except Exception:
            pass
        return True

    GLib.io_add_watch(srv.fileno(), GLib.IOCondition.IN, on_sock_event)
    return srv

def main():
    win = BentoLockWindow()
    srv = setup_glib_socket(win)
    
    if '--daemon' not in sys.argv:
        win.show_lockscreen()
        
    Gtk.main()

if __name__ == "__main__":
    main()
