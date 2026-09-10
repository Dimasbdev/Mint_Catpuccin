#!/usr/bin/env python3
import os, sys, time, json, subprocess, re, threading
import cairo
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('WebKit2', '4.1')
from gi.repository import Gtk, Gdk, WebKit2, GLib

try:
    import dbus
    from dbus.mainloop.glib import DBusGMainLoop
except ImportError:
    dbus = None

DATA_DIR = os.path.expanduser("~/.local/share/bento-osd")

def get_current_volume():
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
    return vol, muted

def get_current_mic_mute():
    muted = False
    try:
        out = subprocess.check_output(['pactl', 'get-source-mute', '@DEFAULT_SOURCE@'], text=True, stderr=subprocess.DEVNULL)
        muted = 'yes' in out.lower()
    except Exception:
        pass
    return muted

def get_current_brightness():
    pct = 100
    try:
        p_act = '/sys/class/backlight/intel_backlight/actual_brightness'
        p_max = '/sys/class/backlight/intel_backlight/max_brightness'
        if os.path.exists(p_act) and os.path.exists(p_max):
            with open(p_act, 'r') as f: act = int(f.read().strip())
            with open(p_max, 'r') as f: mx = int(f.read().strip())
            if mx > 0:
                pct = round((act / mx) * 100)
    except Exception:
        pass
    return pct

class BentoOSDWindow(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("BentoPillOSD")
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(False)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.stick()

        self.set_app_paintable(True)
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        # Force transparent window background to remove rectangular compositor frame
        css = Gtk.CssProvider()
        css.load_from_data(b"window, decoration, .background { background-color: transparent; background: transparent; box-shadow: none; border: none; }")
        Gtk.StyleContext.add_provider_for_screen(screen, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        def on_draw(widget, cr):
            cr.set_source_rgba(0, 0, 0, 0)
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.paint()
            return False
        self.connect("draw", on_draw)

        self.win_width = 280
        self.win_height = 54
        self.set_default_size(self.win_width, self.win_height)
        self.reposition_window()

        settings = WebKit2.Settings()
        settings.set_enable_developer_extras(False)
        settings.set_enable_javascript(True)
        settings.set_allow_file_access_from_file_urls(True)
        settings.set_allow_universal_access_from_file_urls(True)
        settings.set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.NEVER)

        self.webview = WebKit2.WebView()
        self.webview.set_settings(settings)
        self.webview.set_background_color(Gdk.RGBA(0.0, 0.0, 0.0, 0.0))
        self.webview.connect("context-menu", lambda *args: True)

        html_path = os.path.join(DATA_DIR, "index.html")
        self.webview.load_uri(f"file://{html_path}")

        self.add(self.webview)
        self.connect("destroy", Gtk.main_quit)

        self.is_visible = False
        self.hide_timer_id = None
        self.finish_hide_timer_id = None

        # State tracking
        self.last_volume, self.last_muted = get_current_volume()
        self.last_mic_muted = get_current_mic_mute()
        self.last_brightness = get_current_brightness()

        if dbus:
            try:
                DBusGMainLoop(set_as_default=True)
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
                root.style.setProperty('--dynamic-accent', '{theme.get('primary', '#f5c2e7')}');
                root.style.setProperty('--dynamic-secondary', '{theme.get('secondary', '#cba6f7')}');
                root.style.setProperty('--flamingo', '{theme.get('primary', '#f5c2e7')}');
                root.style.setProperty('--accent', '{theme.get('primary', '#f5c2e7')}');
                root.style.setProperty('--mauve', '{theme.get('secondary', '#cba6f7')}');
                root.style.setProperty('--border', '{theme.get('border_active', 'rgba(245, 194, 231, 0.45)')}');
            }})();
            """
            self.webview.run_javascript(js)
        except Exception:
            pass

    def reposition_window(self):
        screen = Gdk.Screen.get_default()
        geom = screen.get_monitor_geometry(0)
        x = geom.x + (geom.width - self.win_width) // 2
        y = geom.y + 46
        self.move(x, y)

    def trigger_osd(self, osd_type, value, muted=False):
        self.reposition_window()
        self.stick()
        self.set_keep_above(True)

        self.apply_theme_from_file()
        if not self.is_visible:
            self.show_all()
            self.is_visible = True

        data = {
            "type": osd_type,
            "value": value,
            "muted": muted
        }
        js_code = f"if (window.updateOSD) {{ updateOSD({json.dumps(data)}); }}"
        self.webview.run_javascript(js_code)

        # Reset dismiss timer
        if self.hide_timer_id:
            GLib.source_remove(self.hide_timer_id)
            self.hide_timer_id = None
        if self.finish_hide_timer_id:
            GLib.source_remove(self.finish_hide_timer_id)
            self.finish_hide_timer_id = None

        self.hide_timer_id = GLib.timeout_add(1600, self.start_hide_animation)

    def start_hide_animation(self):
        self.hide_timer_id = None
        self.webview.run_javascript("if (window.animateHideOSD) { animateHideOSD(); }")
        self.finish_hide_timer_id = GLib.timeout_add(260, self.finish_hide)
        return False

    def finish_hide(self):
        self.finish_hide_timer_id = None
        self.is_visible = False
        self.hide()
        Gdk.flush()
        try:
            import gc, ctypes
            gc.collect()
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except Exception:
            pass
        return False

def start_monitors(win):
    # 1. PulseAudio pactl subscribe monitor
    def audio_worker():
        while True:
            try:
                proc = subprocess.Popen(['pactl', 'subscribe'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                for line in proc.stdout:
                    if 'sink' in line or 'source' in line:
                        # Query updated state
                        vol, muted = get_current_volume()
                        mic_muted = get_current_mic_mute()

                        if vol != win.last_volume or muted != win.last_muted:
                            win.last_volume = vol
                            win.last_muted = muted
                            GLib.idle_add(win.trigger_osd, 'volume', vol, muted)
                        elif mic_muted != win.last_mic_muted:
                            win.last_mic_muted = mic_muted
                            GLib.idle_add(win.trigger_osd, 'mic', 0, mic_muted)
            except Exception:
                time.sleep(1)

    t_audio = threading.Thread(target=audio_worker, daemon=True)
    t_audio.start()

    # 2. Brightness monitor (Fast sysfs check + D-Bus signal receiver)
    def brightness_worker():
        while True:
            try:
                cur_b = get_current_brightness()
                if abs(cur_b - win.last_brightness) >= 1:
                    win.last_brightness = cur_b
                    GLib.idle_add(win.trigger_osd, 'brightness', cur_b, False)
            except Exception:
                pass
            time.sleep(0.08) # 80ms poll takes 0.00% CPU on sysfs file read

    t_bright = threading.Thread(target=brightness_worker, daemon=True)
    t_bright.start()

def main():
    win = BentoOSDWindow()
    start_monitors(win)

    if '--test' in sys.argv:
        # Trigger test volume osd on launch
        GLib.timeout_add(300, win.trigger_osd, 'volume', win.last_volume, win.last_muted)

    Gtk.main()

if __name__ == "__main__":
    main()
