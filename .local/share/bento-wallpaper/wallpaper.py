#!/usr/bin/env python3
"""
Bento Wallpaper Switcher (Super + W)
Dynamic Per-Workspace Wallpaper Manager for Cinnamon / X11
"""

import os
import sys
import time
import json
import socket
import random
import hashlib
import threading
import subprocess
import colorsys
from PIL import Image

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('WebKit2', '4.1')
gi.require_version('Wnck', '3.0')
gi.require_version('Gio', '2.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, WebKit2, Wnck, Gio, GLib

UID = os.getuid()
SOCKET_PATH = f"/tmp/bento-wallpaper-{UID}.sock"
LOCK_SOCKET_PATH = f"/tmp/bento-lock-{UID}.sock"

CONFIG_DIR = os.path.expanduser("~/.config/bento-wallpaper")
WORKSPACES_CONFIG_FILE = os.path.join(CONFIG_DIR, "workspaces.json")

CACHE_BASE_DIR = os.path.expanduser("~/.cache/bento-wallpaper")
CACHE_DIR = os.path.join(CACHE_BASE_DIR, "thumbnails")
OPTIMIZED_DIR = os.path.join(CACHE_BASE_DIR, "optimized")
OPT_MAP_FILE = os.path.join(CACHE_BASE_DIR, "opt_map.json")
META_CACHE_FILE = os.path.join(CACHE_BASE_DIR, "meta_cache.json")

DATA_DIR = os.path.expanduser("~/.local/share/bento-wallpaper")
WALLPAPERS_DIR = os.path.expanduser("~/Pictures/Wallpapers")
PINTEREST_DIR = os.path.expanduser("~/Pictures/Pinterest")

os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(OPTIMIZED_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# Fast Gio Settings for background
cinnamon_bg_settings = Gio.Settings(schema="org.cinnamon.desktop.background")
try:
    gnome_bg_settings = Gio.Settings(schema="org.gnome.desktop.background")
except Exception:
    gnome_bg_settings = None

# Enforce instant wallpaper switching (no sluggish fade animation)
try:
    nemo_bg_settings = Gio.Settings(schema="org.nemo.desktop")
    nemo_bg_settings.set_boolean("background-fade", False)
except Exception:
    pass

try:
    muffin_settings = Gio.Settings(schema="org.cinnamon.muffin")
    muffin_settings.set_string("background-transition", "none")
except Exception:
    pass


def load_opt_map():
    if os.path.exists(OPT_MAP_FILE):
        try:
            with open(OPT_MAP_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_opt_map(mapping):
    try:
        with open(OPT_MAP_FILE, "w") as f:
            json.dump(mapping, f, indent=2)
    except Exception:
        pass


def get_screen_resolution():
    try:
        screen = Gdk.Screen.get_default()
        monitor = screen.get_primary_monitor()
        geom = screen.get_monitor_geometry(monitor if monitor >= 0 else 0)
        return geom.width, geom.height
    except Exception:
        return 1920, 1080


def get_optimized_wallpaper(orig_path):
    """
    Pre-renders a display-exact 1080p JPEG (~250KB) cached to disk.
    Allows Nemo/Cinnamon to load the wallpaper in 3ms instead of 370ms.
    """
    if not orig_path or not os.path.exists(orig_path):
        return orig_path

    try:
        mtime = os.path.getmtime(orig_path)
        sw, sh = get_screen_resolution()
        hash_val = hashlib.md5(f"{orig_path}_{mtime}_{sw}x{sh}".encode()).hexdigest()
        opt_path = os.path.join(OPTIMIZED_DIR, f"{hash_val}.jpg")

        if os.path.exists(opt_path) and os.path.getsize(opt_path) > 0:
            return opt_path

        with Image.open(orig_path) as im:
            im = im.convert('RGB')
            im_scaled = im.resize((sw, sh), Image.Resampling.BILINEAR)
            im_scaled.save(opt_path, "JPEG", quality=95)

        opt_map = load_opt_map()
        opt_map[opt_path] = orig_path
        save_opt_map(opt_map)

        return opt_path
    except Exception as e:
        print(f"Error optimizing wallpaper {orig_path}: {e}", file=sys.stderr)
        return orig_path


def format_file_size(size_bytes):
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.0f} KB"
    return f"{size_bytes} B"


def get_current_desktop_wallpaper():
    try:
        uri = cinnamon_bg_settings.get_string("picture-uri")
        wp = uri.replace("file://", "").strip("'")
        opt_map = load_opt_map()
        if wp in opt_map and os.path.exists(opt_map[wp]):
            return opt_map[wp]
        if os.path.exists(wp):
            return wp
    except Exception:
        pass
    fallback = os.path.join(WALLPAPERS_DIR, "workspace-1.jpg")
    return fallback if os.path.exists(fallback) else ""


def generate_thumbnail(img_path):
    try:
        mtime = os.path.getmtime(img_path)
        hash_val = hashlib.md5(f"{img_path}_{mtime}".encode()).hexdigest()
        thumb_path = os.path.join(CACHE_DIR, f"{hash_val}.jpg")

        if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
            return thumb_path

        with Image.open(img_path) as im:
            im = im.convert('RGB')
            im.thumbnail((480, 270), Image.Resampling.LANCZOS)
            im.save(thumb_path, "JPEG", quality=82, optimize=True)
        return thumb_path
    except Exception:
        return img_path


def load_meta_cache():
    if os.path.exists(META_CACHE_FILE):
        try:
            with open(META_CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_meta_cache(cache):
    try:
        with open(META_CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass



def get_accent_color(img_path):
    try:
        with Image.open(img_path) as im:
            im = im.convert('RGB')
            im_thumb = im.resize((64, 64), Image.Resampling.BILINEAR)
            palette_im = im_thumb.quantize(colors=16, method=Image.Quantize.MEDIANCUT)
            palette = palette_im.getpalette()[:48]

            candidates = []
            for i in range(0, len(palette), 3):
                r, g, b = palette[i], palette[i+1], palette[i+2]
                h, s, v = colorsys.rgb_to_hsv(r/255.0, g/255.0, b/255.0)
                score = 0
                if 0.28 <= s <= 0.95 and 0.40 <= v <= 0.95:
                    score = s * 2.5 + v
                elif s > 0.18 and v > 0.35:
                    score = s * 1.5 + v * 0.5
                candidates.append((score, (r, g, b), (h, s, v)))

            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0]
            r, g, b = best[1]

            if best[0] == 0:
                return '#89b4fa', '137, 180, 250'

            h, s, v = best[2]
            if v < 0.65:
                v = 0.76
                r_b, g_b, b_b = colorsys.hsv_to_rgb(h, min(s, 0.85), v)
                r, g, b = int(r_b*255), int(g_b*255), int(b_b*255)

            return '#{:02x}{:02x}{:02x}'.format(r, g, b), f'{r}, {g}, {b}'
    except Exception:
        return '#89b4fa', '137, 180, 250'

def scan_wallpapers():
    scan_dirs = [WALLPAPERS_DIR]
    if os.path.isdir(PINTEREST_DIR):
        scan_dirs.append(PINTEREST_DIR)

    extensions = ('.png', '.jpg', '.jpeg', '.webp', '.bmp')
    results = []
    meta_cache = load_meta_cache()
    updated_cache = False

    for d in scan_dirs:
        if not os.path.isdir(d):
            continue
        for fname in sorted(os.listdir(d)):
            if fname.lower().endswith(extensions):
                full_path = os.path.join(d, fname)
                try:
                    stat = os.stat(full_path)
                    size = stat.st_size
                    if size == 0:
                        continue
                    mtime = stat.st_mtime

                    # Check meta cache
                    cached = meta_cache.get(full_path)
                    if cached and cached.get("mtime") == mtime and os.path.exists(cached.get("thumbnail", "")) and "accent_color" in cached.get("data", {}):
                        results.append(cached["data"])
                        continue

                    width, height = 1920, 1080
                    try:
                        with Image.open(full_path) as im:
                            width, height = im.size
                    except Exception:
                        continue

                    thumb_path = generate_thumbnail(full_path)
                    accent_color, accent_rgb = get_accent_color(full_path)
                    clean_title = os.path.splitext(fname)[0].replace("-", " ").replace("_", " ")

                    item_data = {
                        "path": full_path,
                        "name": fname,
                        "clean_name": clean_title,
                        "size_bytes": size,
                        "size_str": format_file_size(size),
                        "width": width,
                        "height": height,
                        "thumbnail": thumb_path,
                        "accent_color": accent_color,
                        "accent_rgb": accent_rgb
                    }
                    results.append(item_data)

                    meta_cache[full_path] = {
                        "mtime": mtime,
                        "data": item_data,
                        "thumbnail": thumb_path
                    }
                    updated_cache = True
                except Exception:
                    continue

    if updated_cache:
        save_meta_cache(meta_cache)

    return results





class BentoWallpaperWindow(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("Wallpaper Switcher")
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_app_paintable(True)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        self.win_width = 1060
        self.win_height = 760
        self.set_default_size(self.win_width, self.win_height)
        self.set_position(Gtk.WindowPosition.CENTER)

        # WebKit Setup
        ucm = WebKit2.UserContentManager()
        ucm.register_script_message_handler("wallpaper")
        ucm.connect("script-message-received::wallpaper", self.on_js_message)

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
        self.wallpapers_cache = []
        self.active_wallpaper = get_current_desktop_wallpaper()

        # Workspace management setup
        self.workspaces_map = self.load_workspaces_config()
        self.init_wnck_screen()

        # Pre-cache wallpapers in background
        threading.Thread(target=self.initial_scan_worker, daemon=True).start()

    def init_wnck_screen(self):
        try:
            self.wnck_screen = Wnck.Screen.get_default()
            if self.wnck_screen:
                self.wnck_screen.force_update()
                self.wnck_screen.connect("active-workspace-changed", self.on_active_workspace_changed)
                
                # Check current active workspace on boot
                curr_ws = self.wnck_screen.get_active_workspace()
                if curr_ws:
                    curr_idx = curr_ws.get_number()
                    mapped_wp = self.workspaces_map.get(str(curr_idx))
                    if mapped_wp and os.path.exists(mapped_wp):
                        self.set_desktop_background(mapped_wp, transition=False)
        except Exception as e:
            print(f"Wnck init error: {e}", file=sys.stderr)
            self.wnck_screen = None

    def get_workspaces_info(self):
        count = 4
        active_idx = 0
        names = ["Workspace 1", "Workspace 2", "Workspace 3", "Workspace 4"]
        try:
            if self.wnck_screen:
                self.wnck_screen.force_update()
                count = max(1, self.wnck_screen.get_workspace_count())
                active = self.wnck_screen.get_active_workspace()
                if active:
                    active_idx = active.get_number()
                names = []
                for i in range(count):
                    ws = self.wnck_screen.get_workspace(i)
                    names.append(ws.get_name() if ws else f"Workspace {i+1}")
        except Exception:
            pass

        return {
            "count": count,
            "active_index": active_idx,
            "names": names,
            "workspaces_map": self.workspaces_map
        }

    def load_workspaces_config(self):
        defaults = {
            "0": os.path.join(WALLPAPERS_DIR, "workspace-1.jpg"),
            "1": os.path.join(WALLPAPERS_DIR, "workspace-2.jpg"),
            "2": os.path.join(WALLPAPERS_DIR, "workspace-3.jpg"),
            "3": os.path.join(WALLPAPERS_DIR, "workspace-4.jpg"),
        }
        curr = get_current_desktop_wallpaper()
        if curr:
            defaults["0"] = curr

        ws_data = defaults
        if os.path.exists(WORKSPACES_CONFIG_FILE):
            try:
                with open(WORKSPACES_CONFIG_FILE, "r") as f:
                    cfg = json.load(f)
                    data = cfg.get("workspaces", {})
                    for k, v in defaults.items():
                        if k in data and os.path.exists(data[k]):
                            ws_data[k] = data[k]
            except Exception:
                pass

        # Pre-optimize all workspace wallpapers in background thread so they are instantly ready
        def pre_opt():
            for p in ws_data.values():
                if os.path.exists(p):
                    get_optimized_wallpaper(p)
        threading.Thread(target=pre_opt, daemon=True).start()

        return ws_data

    def save_workspaces_config(self):
        try:
            with open(WORKSPACES_CONFIG_FILE, "w") as f:
                json.dump({"workspaces": self.workspaces_map}, f, indent=2)
        except Exception as e:
            print(f"Error saving workspace config: {e}", file=sys.stderr)

    def on_active_workspace_changed(self, screen, prev_workspace):
        try:
            ws = screen.get_active_workspace()
            if not ws:
                return
            idx = ws.get_number()
            target_wp = self.workspaces_map.get(str(idx))
            if target_wp and os.path.exists(target_wp):
                self.set_desktop_background(target_wp)

            # If switcher window is open, notify UI
            if self.is_visible:
                ws_info = self.get_workspaces_info()
                js_code = f"if (window.onWorkspaceChanged) window.onWorkspaceChanged({json.dumps(ws_info)});"
                GLib.idle_add(lambda: self.webview.run_javascript(js_code))
        except Exception as e:
            print(f"Error in on_active_workspace_changed: {e}", file=sys.stderr)

    def set_desktop_background(self, new_wp_path, transition=False):
        if not new_wp_path or not os.path.exists(new_wp_path):
            return

        if self.active_wallpaper == new_wp_path:
            return

        self.active_wallpaper = new_wp_path

        # Get pre-scaled display-optimized file for instantaneous (3ms) Nemo load
        opt_path = get_optimized_wallpaper(new_wp_path)

        # Update Cinnamon and GNOME Desktop Wallpaper via fast Gio.Settings
        try:
            cinnamon_bg_settings.set_string("picture-uri", f"file://{opt_path}")
            cinnamon_bg_settings.set_string("picture-options", "zoom")
            if gnome_bg_settings:
                gnome_bg_settings.set_string("picture-uri", f"file://{opt_path}")
                gnome_bg_settings.set_string("picture-options", "zoom")
        except Exception as e:
            print(f"Error updating background Gio settings: {e}", file=sys.stderr)

        # Update Lockscreen daemon if active
        if os.path.exists(LOCK_SOCKET_PATH):
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(0.4)
                s.connect(LOCK_SOCKET_PATH)
                s.sendall(f"wallpaper:{new_wp_path}\n".encode())
                s.close()
            except Exception:
                pass

    def apply_to_workspace(self, ws_target, wp_path):
        """
        ws_target: 'all' or integer/string index ('0', '1', '2', etc.)
        """
        if not wp_path or not os.path.exists(wp_path):
            return

        ws_info = self.get_workspaces_info()
        curr_active_idx = ws_info["active_index"]
        total_count = ws_info["count"]
        wp_name = os.path.basename(wp_path)

        if str(ws_target).lower() == "all":
            for i in range(total_count):
                self.workspaces_map[str(i)] = wp_path
            self.set_desktop_background(wp_path, transition=True)
            self.save_workspaces_config()

            notify_title = "Wallpaper Updated"
            notify_body = f"Applied to all workspaces: {wp_name}"
        else:
            target_idx = int(ws_target)
            self.workspaces_map[str(target_idx)] = wp_path
            self.save_workspaces_config()

            if target_idx == curr_active_idx:
                self.set_desktop_background(wp_path, transition=True)
                notify_title = f"Workspace {target_idx + 1} Wallpaper"
                notify_body = f"Applied: {wp_name}"
            else:
                notify_title = f"Workspace {target_idx + 1} Wallpaper"
                notify_body = f"Assigned to Workspace {target_idx + 1} (Will show upon switching)"

        # Desktop notification
        try:
            subprocess.Popen([
                'notify-send',
                '-a', 'Wallpaper Switcher',
                notify_title,
                notify_body,
                '-i', wp_path
            ])
        except Exception:
            pass

        # Update WebKit UI
        payload = {
            "path": wp_path,
            "name": wp_name,
            "target": ws_target,
            "workspaces_info": self.get_workspaces_info()
        }
        js_code = f"if (window.onWallpaperApplied) window.onWallpaperApplied({json.dumps(payload)});"
        GLib.idle_add(lambda: self.webview.run_javascript(js_code))

    def initial_scan_worker(self):
        self.wallpapers_cache = scan_wallpapers()
        self.active_wallpaper = get_current_desktop_wallpaper()

    def reposition_center(self):
        screen = self.get_screen()
        monitor = screen.get_primary_monitor()
        geom = screen.get_monitor_geometry(monitor if monitor >= 0 else 0)
        x = geom.x + (geom.width - self.win_width) // 2
        y = geom.y + (geom.height - self.win_height) // 2
        self.move(x, y)

    def on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.hide_window()
            return True
        return False

    def on_focus_out(self, widget, event):
        if self.is_visible:
            GLib.timeout_add(150, self.check_and_hide_on_blur)
        return False

    def check_and_hide_on_blur(self):
        if self.is_visible and not self.is_active():
            self.hide_window()
        return False

    def on_webview_load_changed(self, webview, load_event):
        if load_event == WebKit2.LoadEvent.FINISHED:
            self.refresh_and_push_state()

    def show_window(self):
        self.reposition_center()
        self.stick()
        self.set_keep_above(True)
        self.is_visible = True
        self.show_all()
        self.present()
        self.grab_focus()
        self.webview.grab_focus()

        # Refresh state and push to WebKit
        self.refresh_and_push_state()

    def hide_window(self):
        self.is_visible = False
        self.hide()
        Gdk.flush()
        if os.path.exists(SOCKET_PATH):
            try:
                os.unlink(SOCKET_PATH)
            except OSError:
                pass
        Gtk.main_quit()

    def toggle_window(self):
        if self.is_visible:
            self.hide_window()
        else:
            self.show_window()

    def refresh_and_push_state(self):
        def worker():
            self.wallpapers_cache = scan_wallpapers()
            self.active_wallpaper = get_current_desktop_wallpaper()
            ws_info = self.get_workspaces_info()

            payload = {
                "wallpapers": self.wallpapers_cache,
                "active": self.active_wallpaper,
                "workspaces_info": ws_info
            }
            js_code = f"if (window.setWallpapersState) window.setWallpapersState({json.dumps(payload)});"
            GLib.idle_add(lambda: self.webview.run_javascript(js_code))

        threading.Thread(target=worker, daemon=True).start()

    def pick_random_wallpaper(self, ws_target=None):
        if not self.wallpapers_cache:
            self.wallpapers_cache = scan_wallpapers()

        candidates = [w['path'] for w in self.wallpapers_cache if w['path'] != self.active_wallpaper]
        if not candidates and self.wallpapers_cache:
            candidates = [self.wallpapers_cache[0]['path']]

        if candidates:
            chosen = random.choice(candidates)
            target = ws_target if ws_target is not None else "current"
            if target == "current":
                ws_info = self.get_workspaces_info()
                target = str(ws_info["active_index"])
            self.apply_to_workspace(target, chosen)

    def on_js_message(self, ucm, js_result):
        try:
            val = js_result.get_js_value()
            msg_str = val.to_string()
            data = json.loads(msg_str)
            action = data.get('action')
            payload = data.get('payload', {})

            if action == 'apply':
                if isinstance(payload, dict):
                    wp_path = payload.get("path")
                    target = payload.get("workspace", "current")
                    if target == "current":
                        ws_info = self.get_workspaces_info()
                        target = str(ws_info["active_index"])
                    self.apply_to_workspace(target, wp_path)
                else:
                    ws_info = self.get_workspaces_info()
                    self.apply_to_workspace(str(ws_info["active_index"]), payload)
            elif action == 'random':
                target = payload.get("workspace", "current") if isinstance(payload, dict) else "current"
                self.pick_random_wallpaper(target)
            elif action == 'open_folder':
                subprocess.Popen(['nemo', WALLPAPERS_DIR])
            elif action == 'close':
                self.hide_window()
            elif action == 'refresh':
                self.refresh_and_push_state()
        except Exception as e:
            print(f"Error handling JS message: {e}", file=sys.stderr)


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
            if msg == "toggle":
                win.toggle_window()
            elif msg == "show":
                win.show_window()
            elif msg == "hide":
                win.hide_window()
            elif msg == "random":
                win.pick_random_wallpaper()
            elif msg.startswith("apply:"):
                win.apply_to_workspace("current", msg.split(":", 1)[1])
            elif msg.startswith("apply_ws:"):
                parts = msg.split(":", 2)
                if len(parts) == 3:
                    win.apply_to_workspace(parts[1], parts[2])
            conn.close()
        except Exception:
            pass
        return True

    GLib.io_add_watch(srv.fileno(), GLib.IOCondition.IN, on_sock_event)
    return srv


def main():
    win = BentoWallpaperWindow()
    srv = setup_glib_socket(win)
    win.show_window()
    Gtk.main()


if __name__ == "__main__":
    main()
