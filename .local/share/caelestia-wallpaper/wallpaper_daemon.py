#!/usr/bin/env python3
"""
Lightweight Workspace Wallpaper & Dynamic Theme Daemon (No WebKit)
Monitors workspace changes, applies per-workspace wallpapers instantly (~3ms),
extracts & caches dynamic accent palettes, and broadcasts theme changes via D-Bus.
"""
import os, sys, json, hashlib, colorsys, math, subprocess
from PIL import Image

import gi
gi.require_version('Wnck', '3.0')
gi.require_version('Gio', '2.0')
gi.require_version('GLib', '2.0')
from gi.repository import Wnck, Gio, GLib

try:
    import dbus
    import dbus.service
    import dbus.mainloop.glib
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
except ImportError:
    dbus = None

CONFIG_DIR = os.path.expanduser("~/.config/bento-wallpaper")
WORKSPACES_CONFIG_FILE = os.path.join(CONFIG_DIR, "workspaces.json")
CACHE_BASE_DIR = os.path.expanduser("~/.cache/bento-wallpaper")
OPTIMIZED_DIR = os.path.join(CACHE_BASE_DIR, "optimized")
SHARED_THEME_DIR = os.path.expanduser("~/.cache/caelestia")
SHARED_COLORS_FILE = os.path.join(SHARED_THEME_DIR, "colors.json")
SHARED_CSS_FILE = os.path.join(SHARED_THEME_DIR, "accent.css")
WALLPAPERS_DIR = os.path.expanduser("~/Pictures/Wallpapers")

os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(OPTIMIZED_DIR, exist_ok=True)
os.makedirs(SHARED_THEME_DIR, exist_ok=True)

# Catppuccin Flamingo Dark Anchor Colors
FLAMINGO_RGB = (245, 194, 231)  # #f5c2e7
MAUVE_RGB = (203, 166, 247)     # #cba6f7
SURFACE_RGB = (49, 50, 68)      # #313244
BG_RGB = (24, 24, 37)           # #181825

def rel_luminance(rgb):
    def adjust(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = [adjust(x) for x in rgb]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def contrast_ratio(rgb1, rgb2):
    l1 = rel_luminance(rgb1)
    l2 = rel_luminance(rgb2)
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)

def rgb_to_hex(rgb):
    return '#{:02x}{:02x}{:02x}'.format(int(rgb[0]), int(rgb[1]), int(rgb[2]))


if dbus:
    class ThemeService(dbus.service.Object):
        def __init__(self, bus):
            try:
                bus_name = dbus.service.BusName("org.caelestia.Theme", bus=bus, allow_replacement=True, replace_existing=True)
                super().__init__(bus_name, "/org/caelestia/Theme")
            except Exception as e:
                print(f"ThemeService init error: {e}", file=sys.stderr)

        @dbus.service.signal("org.caelestia.Theme", signature="s")
        def ThemeChanged(self, colors_path):
            pass
else:
    ThemeService = None


class WallpaperDaemon:
    def __init__(self, theme_service=None):
        self.theme_service = theme_service
        self.active_wallpaper = ""
        self.last_palette_primary = ""
        try:
            cfg_file = Gio.File.new_for_path(WORKSPACES_CONFIG_FILE)
            self.cfg_monitor = cfg_file.monitor_file(Gio.FileMonitorFlags.NONE, None)
            self.cfg_monitor.connect("changed", self.on_config_changed)
        except Exception:
            self.cfg_monitor = None
        self.cinnamon_bg_settings = Gio.Settings(schema="org.cinnamon.desktop.background")
        try:
            self.gnome_bg_settings = Gio.Settings(schema="org.gnome.desktop.background")
        except Exception:
            self.gnome_bg_settings = None

        self.wnck_screen = Wnck.Screen.get_default()
        if self.wnck_screen:
            self.wnck_screen.force_update()
            self.wnck_screen.connect("active-workspace-changed", self.on_active_workspace_changed)
            curr = self.wnck_screen.get_active_workspace()
            if curr:
                self.on_active_workspace_changed(self.wnck_screen, None)

    def load_workspaces_config(self):
        ws_data = {
            "0": os.path.join(WALLPAPERS_DIR, "workspace-1.jpg"),
            "1": os.path.join(WALLPAPERS_DIR, "workspace-2.jpg"),
            "2": os.path.join(WALLPAPERS_DIR, "workspace-3.jpg"),
            "3": os.path.join(WALLPAPERS_DIR, "workspace-4.jpg"),
        }
        if os.path.exists(WORKSPACES_CONFIG_FILE):
            try:
                with open(WORKSPACES_CONFIG_FILE, "r") as f:
                    cfg = json.load(f)
                    data = cfg.get("workspaces", {})
                    for k, v in data.items():
                        if os.path.exists(v):
                            ws_data[k] = v
            except Exception:
                pass
        return ws_data

    def get_fallback_palette(self, wp_path=""):
        pr, pg, pb = FLAMINGO_RGB
        sr, sg, sb = MAUVE_RGB
        return {
            "wallpaper": wp_path,
            "primary": rgb_to_hex(FLAMINGO_RGB),
            "primary_rgb": f"{pr}, {pg}, {pb}",
            "secondary": rgb_to_hex(MAUVE_RGB),
            "secondary_rgb": f"{sr}, {sg}, {sb}",
            "on_primary": "#11111b",
            "accent_subtle": f"rgba({pr}, {pg}, {pb}, 0.16)",
            "border_active": f"rgba({pr}, {pg}, {pb}, 0.45)",
            "border_subtle": f"rgba({pr}, {pg}, {pb}, 0.14)"
        }

    def extract_and_blend_palette(self, im_scaled, wp_path=""):
        try:
            small = im_scaled.resize((120, 120), Image.Resampling.BILINEAR)
            q = small.quantize(colors=32, method=Image.Quantize.MEDIANCUT)
            palette = q.getpalette()[:32 * 3]
            colors = q.getcolors()

            scored = []
            for count, idx in colors:
                r = palette[idx * 3]
                g = palette[idx * 3 + 1]
                b = palette[idx * 3 + 2]
                max_c, min_c = max(r, g, b), min(r, g, b)
                chroma = (max_c - min_c) / 255.0
                lightness = (max_c + min_c) / 510.0

                if lightness < 0.12 or lightness > 0.96 or chroma < 0.08:
                    continue
                score = (chroma ** 1.2) * (count ** 0.5)
                h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
                scored.append((score, (r, g, b), h, s, v))

            scored.sort(key=lambda x: x[0], reverse=True)
            if not scored:
                h_pri = 312 / 360.0 # Flamingo default
                h_sec = 267 / 360.0 # Mauve default
            else:
                # Use the actual wallpaper hue (e.g. Green for Eva, Blue for Lain, Coral for Sunset)
                h_pri = scored[0][2]
                h_sec = (h_pri + 0.10) % 1.0
                for c in scored[1:]:
                    diff = abs((c[2] - h_pri + 0.5) % 1.0 - 0.5)
                    if diff > 0.08:
                        h_sec = c[2]
                        break

            # Catppuccin pastel tuning for primary (clean, bright, soft saturation)
            cat_s = 0.68
            cat_l = 0.78
            rgb = [int(round(x * 255.0)) for x in colorsys.hls_to_rgb(h_pri, cat_l, cat_s)]
            while contrast_ratio(rgb, SURFACE_RGB) < 4.5 and cat_l < 0.94:
                cat_l += 0.01
                rgb = [int(round(x * 255.0)) for x in colorsys.hls_to_rgb(h_pri, cat_l, cat_s)]

            # Catppuccin pastel tuning for secondary
            sec_s = 0.65
            sec_l = 0.76
            sec_rgb = [int(round(x * 255.0)) for x in colorsys.hls_to_rgb(h_sec, sec_l, sec_s)]
            while contrast_ratio(sec_rgb, SURFACE_RGB) < 4.5 and sec_l < 0.94:
                sec_l += 0.01
                sec_rgb = [int(round(x * 255.0)) for x in colorsys.hls_to_rgb(h_sec, sec_l, sec_s)]

            pr, pg, pb = rgb
            sr, sg, sb = sec_rgb
            return {
                "wallpaper": wp_path,
                "primary": rgb_to_hex(rgb),
                "primary_rgb": f"{pr}, {pg}, {pb}",
                "secondary": rgb_to_hex(sec_rgb),
                "secondary_rgb": f"{sr}, {sg}, {sb}",
                "on_primary": "#11111b",
                "accent_subtle": f"rgba({pr}, {pg}, {pb}, 0.16)",
                "border_active": f"rgba({pr}, {pg}, {pb}, 0.45)",
                "border_subtle": f"rgba({pr}, {pg}, {pb}, 0.14)"
            }
        except Exception:
            return self.get_fallback_palette(wp_path)

    def get_optimized_and_palette(self, orig_path):
        if not orig_path or not os.path.exists(orig_path):
            return orig_path, self.get_fallback_palette(orig_path)
        try:
            mtime = os.path.getmtime(orig_path)
            hash_val = hashlib.md5(f"{orig_path}_{mtime}_1920x1080".encode()).hexdigest()
            opt_path = os.path.join(OPTIMIZED_DIR, f"{hash_val}.jpg")
            colors_cache_path = os.path.join(OPTIMIZED_DIR, f"{hash_val}.colors.json")

            # Instant return (<1ms) if cached
            if os.path.exists(opt_path) and os.path.exists(colors_cache_path):
                try:
                    with open(colors_cache_path, "r") as f:
                        palette = json.load(f)
                    return opt_path, palette
                except Exception:
                    pass

            # Pre-scale image and extract palette at the same time
            with Image.open(orig_path) as im:
                im = im.convert('RGB')
                im_scaled = im.resize((1920, 1080), Image.Resampling.BILINEAR)
                im_scaled.save(opt_path, "JPEG", quality=95)
                palette = self.extract_and_blend_palette(im_scaled, orig_path)

            with open(colors_cache_path, "w") as f:
                json.dump(palette, f, indent=2)

            return opt_path, palette
        except Exception:
            return orig_path, self.get_fallback_palette(orig_path)

    def on_config_changed(self, monitor, file, other_file, event_type):
        if event_type in (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CREATED):
            if self.wnck_screen:
                self.wnck_screen.force_update()
                curr = self.wnck_screen.get_active_workspace()
                if curr:
                    idx = str(curr.get_number())
                    mapping = self.load_workspaces_config()
                    target_wp = mapping.get(idx)
                    if target_wp and os.path.exists(target_wp):
                        self.set_desktop_background(target_wp)

    def update_cinnamon_theme(self, palette):
        try:
            primary = palette.get("primary", "#a1edb8")
            if primary == self.last_palette_primary:
                return
            self.last_palette_primary = primary

            cinnamon_css = os.path.expanduser("~/.themes/Catppuccin-Flamingo-Dark/cinnamon/cinnamon.css")
            if not os.path.exists(cinnamon_css):
                return

            with open(cinnamon_css, "r") as f:
                content = f.read()

            marker_start = "/* === NOCTALIA DYNAMIC ACCENT START === */"
            marker_end = "/* === NOCTALIA DYNAMIC ACCENT END === */"

            pr, pg, pb = [x.strip() for x in palette.get("primary_rgb", "161, 237, 184").split(",")]
            border_active = palette.get("border_active", f"rgba({pr}, {pg}, {pb}, 0.45)")
            border_hover = f"rgba({pr}, {pg}, {pb}, 0.7)"

            dynamic_section = f"""{marker_start}
/* Universal Capsule Base (applies to ALL applet-box in panel: hwmonitor, calendar, tray, power, etc.) */
#panel .applet-box {{
    background-color: rgba(24, 24, 37, 0.85);
    border: 1px solid {border_active};
    border-radius: 9999px;
    padding: 0 8px;
    margin: 6px 2px;
    height: 28px;
    color: #cdd6f4;
    transition-duration: 150ms;
}}

/* Workspace Switcher: outer shell must stay transparent and borderless */
#panel .workspace-nano-df-applet,
.workspace-nano-df-applet {{
    background-color: transparent !important;
    border: none !important;
    box-shadow: none !important;
    padding: 0 !important;
    margin: 6px 2px !important;
}}

#panel .applet-box:hover {{
    background-color: rgba(36, 36, 54, 0.95);
    border-color: {border_hover};
    color: {primary};
}}

#panel .applet-box:hover .applet-icon,
#panel .applet-box:hover StIcon {{
    color: {primary} !important;
}}

#panel .applet-box:hover .applet-label {{
    color: {primary} !important;
    font-weight: 700 !important;
}}

#panelCenter .applet-box .applet-label,
#panelCenter .applet-label {{
    color: #ffffff !important;
    font-weight: 600 !important;
}}

#panelCenter .applet-box:hover .applet-label {{
    color: {primary} !important;
    font-weight: 700 !important;
}}

#panelLeft .applet-box:first-child {{
    border: 1px solid {border_active} !important;
}}

#panelLeft .applet-box:first-child:hover {{
    border-color: {border_hover} !important;
}}

.calendar-today,
.calendar-today:active,
.calendar-today:focus,
.calendar-today:hover {{
    background-color: {primary} !important;
    color: #11111b !important;
    border-radius: 9999px;
}}

#menu-search-entry:focus {{
    border: 2px solid {primary} !important;
}}
{marker_end}"""

            if marker_start in content and marker_end in content:
                before = content.split(marker_start)[0]
                after = content.split(marker_end)[1]
                new_content = before + dynamic_section + after
            else:
                new_content = content + "\n\n" + dynamic_section

            with open(cinnamon_css, "w") as f:
                f.write(new_content)

            # Omit ReloadTheme on workspace switch to ensure zero lag (~3ms instant switch).
            # Live capsule theming is handled directly in-memory by workspace-nano@df.
        except Exception as e:
            print(f"Error updating cinnamon theme: {e}", file=sys.stderr)

    def update_shared_theme(self, palette):
        try:
            with open(SHARED_COLORS_FILE, "w") as f:
                json.dump(palette, f, indent=2)

            css_content = f"""/* Generated by Caelestia Wallpaper Theme Engine */
@define-color accent_color {palette['primary']};
@define-color accent_secondary {palette['secondary']};
@define-color accent_fg {palette['on_primary']};
@define-color accent_subtle {palette['accent_subtle']};
@define-color accent_border {palette['border_active']};
"""
            with open(SHARED_CSS_FILE, "w") as f:
                f.write(css_content)

            self.update_cinnamon_theme(palette)

            if self.theme_service:
                self.theme_service.ThemeChanged(SHARED_COLORS_FILE)
        except Exception as e:
            print(f"Error writing shared theme: {e}", file=sys.stderr)

    def set_desktop_background(self, new_wp_path):
        if not new_wp_path or not os.path.exists(new_wp_path) or self.active_wallpaper == new_wp_path:
            return
        self.active_wallpaper = new_wp_path
        opt_path, palette = self.get_optimized_and_palette(new_wp_path)
        try:
            self.cinnamon_bg_settings.set_string("picture-uri", f"file://{opt_path}")
            self.cinnamon_bg_settings.set_string("picture-options", "zoom")
            if self.gnome_bg_settings:
                self.gnome_bg_settings.set_string("picture-uri", f"file://{opt_path}")
                self.gnome_bg_settings.set_string("picture-options", "zoom")
            self.update_shared_theme(palette)
        except Exception as e:
            print(f"Error setting background: {e}", file=sys.stderr)

    def on_active_workspace_changed(self, screen, prev_workspace):
        try:
            ws = screen.get_active_workspace()
            if not ws:
                return
            idx = str(ws.get_number())
            mapping = self.load_workspaces_config()
            target_wp = mapping.get(idx)
            if target_wp and os.path.exists(target_wp):
                self.set_desktop_background(target_wp)
        except Exception as e:
            print(f"Workspace switch error: {e}", file=sys.stderr)


def main():
    theme_svc = None
    if dbus:
        try:
            bus = dbus.SessionBus()
            theme_svc = ThemeService(bus)
        except Exception as e:
            print(f"DBus initialization warning: {e}", file=sys.stderr)

    daemon = WallpaperDaemon(theme_service=theme_svc)
    loop = GLib.MainLoop()
    loop.run()

if __name__ == "__main__":
    main()
