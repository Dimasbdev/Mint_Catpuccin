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
SHARED_THEME_DIR = os.path.expanduser("~/.cache/bento")
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
                bus_name = dbus.service.BusName("org.bento.Theme", bus=bus, allow_replacement=True, replace_existing=True)
                super().__init__(bus_name, "/org/bento/Theme")
            except Exception as e:
                print(f"ThemeService init error: {e}", file=sys.stderr)

        @dbus.service.signal("org.bento.Theme", signature="s")
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

        self.update_workspaces_palette_cache()
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
                        v_exp = os.path.expanduser(v)
                        if os.path.exists(v_exp):
                            ws_data[k] = v_exp
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

    def update_workspaces_cinnamon_css(self, all_palettes):
        try:
            cinnamon_css = os.path.expanduser("~/.themes/Catppuccin-Flamingo-Dark/cinnamon/cinnamon.css")
            if not os.path.exists(cinnamon_css):
                return

            with open(cinnamon_css, "r") as f:
                content = f.read()

            marker_start = "/* === NOCTALIA DYNAMIC ACCENT START === */"
            marker_end = "/* === NOCTALIA DYNAMIC ACCENT END === */"

            ws_rules = []
            for ws_idx, pinfo in all_palettes.items():
                pri = pinfo["primary"]
                border_act = pinfo["border"]
                border_hov = border_act.replace("0.45", "0.75")

                ws_rules.append(f"""/* --- Workspace {ws_idx}: {pri} --- */
#panel.ws-{ws_idx} .applet-box {{
    border: 1px solid {border_act} !important;
}}
#panel.ws-{ws_idx} .applet-box:hover {{
    background-color: rgba(36, 36, 54, 0.95) !important;
    border-color: {border_hov} !important;
    color: {pri} !important;
}}
#panel.ws-{ws_idx} .applet-box:hover .applet-icon,
#panel.ws-{ws_idx} .applet-box:hover StIcon {{
    color: {pri} !important;
}}
#panel.ws-{ws_idx} .applet-box:hover .applet-label,
#panel.ws-{ws_idx} #panelCenter .applet-box:hover .applet-label {{
    color: {pri} !important;
    font-weight: 700 !important;
}}
.ws-{ws_idx} .calendar-today,
.ws-{ws_idx} .calendar-today:active,
.ws-{ws_idx} .calendar-today:focus,
.ws-{ws_idx} .calendar-today:hover,
#panel.ws-{ws_idx} .calendar-today,
#panel.ws-{ws_idx} .calendar-today:active,
#panel.ws-{ws_idx} .calendar-today:focus,
#panel.ws-{ws_idx} .calendar-today:hover {{
    background-color: {pri} !important;
    color: #11111b !important;
    border-radius: 9999px;
}}
.ws-{ws_idx} .calendar-today-day-label {{
    color: {pri} !important;
}}
.ws-{ws_idx} .calendar-today-home-button-enabled {{
    background-color: {pri} !important;
    color: #11111b !important;
}}
#panel.ws-{ws_idx} #menu-search-entry:focus {{
    border: 2px solid {pri} !important;
}}
.ws-{ws_idx} .workspace-switch-osd,
.workspace-switch-osd.ws-{ws_idx} {{
    color: {pri} !important;
    border: 1px solid {border_act} !important;
}}
.ws-{ws_idx} .workspace-switch-osd .workspace-switch-osd-indicator:active,
.workspace-switch-osd.ws-{ws_idx} .workspace-switch-osd-indicator:active {{
    background-color: {pri} !important;
}}
.ws-{ws_idx} .workspace-switch-osd StLabel,
.workspace-switch-osd.ws-{ws_idx} StLabel {{
    color: {pri} !important;
}}

/* Dynamic Bento Sound Player for Workspace {ws_idx} */
.ws-{ws_idx} .sound-player,
.menu.ws-{ws_idx} .sound-player,
.sound-player.ws-{ws_idx},
.popup-menu-content.ws-{ws_idx} .sound-player {{
    border: 1px solid {border_act} !important;
    box-shadow: 0 16px 36px rgba(0, 0, 0, 0.55), 0 0 16px {border_act} !important;
}}
.ws-{ws_idx} .sound-player > StBoxLayout:first-child,
.menu.ws-{ws_idx} .sound-player > StBoxLayout:first-child,
.sound-player.ws-{ws_idx} > StBoxLayout:first-child {{
    color: {pri} !important;
}}
.ws-{ws_idx} .sound-player-generic-coverart,
.menu.ws-{ws_idx} .sound-player-generic-coverart,
.sound-player.ws-{ws_idx} .sound-player-generic-coverart {{
    color: {pri} !important;
}}
.ws-{ws_idx} .sound-player-overlay StButton:hover,
.menu.ws-{ws_idx} .sound-player-overlay StButton:hover,
.sound-player.ws-{ws_idx} .sound-player-overlay StButton:hover {{
    background-color: {border_act} !important;
    color: {pri} !important;
    border-color: {pri} !important;
    box-shadow: 0 0 12px {border_act} !important;
}}
.ws-{ws_idx} .sound-player-overlay StButton:active,
.menu.ws-{ws_idx} .sound-player-overlay StButton:active,
.sound-player.ws-{ws_idx} .sound-player-overlay StButton:active {{
    background-color: {pri} !important;
    color: #11111b !important;
    border-color: {pri} !important;
}}
.ws-{ws_idx} .sound-player .slider,
.menu.ws-{ws_idx} .sound-player .slider,
.sound-player.ws-{ws_idx} .slider {{
    -slider-active-background-color: {pri} !important;
}}
.ws-{ws_idx} .sound-volume-menu-item StIcon,
.menu.ws-{ws_idx} .sound-volume-menu-item StIcon,
.popup-menu-content.ws-{ws_idx} .sound-volume-menu-item StIcon {{
    color: {pri} !important;
}}
.ws-{ws_idx} .sound-volume-menu-item .slider,
.menu.ws-{ws_idx} .sound-volume-menu-item .slider,
.popup-menu-content.ws-{ws_idx} .sound-volume-menu-item .slider {{
    -slider-active-background-color: {pri} !important;
}}
.ws-{ws_idx} .popup-menu .popup-menu-item:hover,
.ws-{ws_idx} .popup-menu .popup-menu-item:active,
.ws-{ws_idx} .menu .popup-menu-item:hover,
.ws-{ws_idx} .menu .popup-menu-item:active,
.menu.ws-{ws_idx} .popup-menu-item:hover,
.menu.ws-{ws_idx} .popup-menu-item:active {{
    color: {pri} !important;
    background-color: {border_act.replace("0.45", "0.15")} !important;
}}""")

            all_ws_css = "\n\n".join(ws_rules)

            dynamic_section = f"""{marker_start}
/* Universal Capsule Base (applies to ALL applet-box in panel: hwmonitor, calendar, tray, power, etc.) */
#panel .applet-box {{
    background-color: rgba(24, 24, 37, 0.85) !important;
    border: 1px solid rgba(161, 194, 237, 0.45) !important;
    border-radius: 9999px !important;
    padding: 0 8px !important;
    margin: 6px 2px !important;
    height: 28px !important;
    color: #cdd6f4 !important;
    transition-duration: 150ms;
}}

/* Non-hover state: clean Catppuccin subtext #cdd6f4 */
#panel .applet-box .applet-icon,
#panel .applet-box StIcon {{
    color: #cdd6f4 !important;
}}

/* Workspace Switcher: outer shell must stay transparent and borderless */
#panel .workspace-nano-df-applet,
.workspace-nano-df-applet,
#panelLeft .applet-box:nth-child(2) {{
    background-color: transparent !important;
    border: none !important;
    box-shadow: none !important;
    padding: 0 !important;
    margin: 6px 2px !important;
    height: 28px !important;
}}

#panelCenter .applet-box .applet-label,
#panelCenter .applet-label {{
    color: #ffffff !important;
    font-weight: 600 !important;
}}

/* Per-workspace instant accent classes (switched in JS with 0ms delay, no theme reload) */
{all_ws_css}
{marker_end}"""

            if marker_start in content and marker_end in content:
                before = content.split(marker_start)[0]
                after = content.split(marker_end)[1]
                after = after.replace(".panel-top.ws-test .applet-box { border: 2px solid #ff00ff !important; }\n", "")
                after = after.replace("#panel.ws-test .applet-box { border: 2px solid #ff00ff !important; }\n", "")
                new_content = before + dynamic_section + after
            else:
                new_content = content + "\n\n" + dynamic_section

            with open(cinnamon_css, "w") as f:
                f.write(new_content)

            # Reload Cinnamon theme ONCE when cache is generated/updated
            if dbus:
                try:
                    bus = dbus.SessionBus()
                    cin = bus.get_object('org.Cinnamon', '/org/Cinnamon')
                    cin.ReloadTheme(dbus_interface='org.Cinnamon')
                except Exception:
                    pass
        except Exception as e:
            print(f"Error updating workspaces cinnamon css: {e}", file=sys.stderr)

    def update_workspaces_palette_cache(self):
        try:
            mapping = self.load_workspaces_config()
            all_palettes = {}
            for ws_idx, wp_path in mapping.items():
                wp_exp = os.path.expanduser(wp_path)
                if os.path.exists(wp_exp):
                    _, pal = self.get_optimized_and_palette(wp_exp)
                    all_palettes[ws_idx] = {
                        "wallpaper": wp_exp,
                        "primary": pal["primary"],
                        "border": pal["border_active"]
                    }
            cache_file = os.path.join(SHARED_THEME_DIR, "workspaces_palette.json")
            with open(cache_file, "w") as f:
                json.dump(all_palettes, f, indent=2)

            # Generate all per-workspace CSS rules once
            self.update_workspaces_cinnamon_css(all_palettes)
        except Exception as e:
            print(f"Error updating workspaces palette cache: {e}", file=sys.stderr)

    def on_config_changed(self, monitor, file, other_file, event_type):
        if event_type in (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CREATED):
            self.update_workspaces_palette_cache()
            if self.wnck_screen:
                self.wnck_screen.force_update()
                curr = self.wnck_screen.get_active_workspace()
                if curr:
                    idx = str(curr.get_number())
                    mapping = self.load_workspaces_config()
                    target_wp = mapping.get(idx)
                    if target_wp:
                        target_wp = os.path.expanduser(target_wp)
                        if os.path.exists(target_wp):
                            self.set_desktop_background(target_wp)

    def update_cava_theme(self, palette):
        try:
            cava_config_path = os.path.expanduser("~/.config/cava/config")
            if not os.path.exists(cava_config_path):
                return

            pri = palette.get("primary", "#f5c2e7")
            sec = palette.get("secondary", "#cba6f7")

            with open(cava_config_path, "r") as f:
                lines = f.readlines()

            new_lines = []
            in_color_section = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("[") and stripped.endswith("]"):
                    if stripped == "[color]":
                        in_color_section = True
                        new_lines.append(line)
                        new_lines.append("gradient = 1\n")
                        new_lines.append("gradient_count = 2\n")
                        new_lines.append(f"gradient_color_1 = '{sec}'\n")
                        new_lines.append(f"gradient_color_2 = '{pri}'\n")
                        continue
                    else:
                        in_color_section = False

                if in_color_section:
                    if any(stripped.startswith(k) for k in ("gradient", "gradient_count", "gradient_color_", "foreground", "background")):
                        continue
                new_lines.append(line)

            if not any("[color]" in l for l in lines):
                new_lines.append("\n[color]\n")
                new_lines.append("gradient = 1\n")
                new_lines.append("gradient_count = 2\n")
                new_lines.append(f"gradient_color_1 = '{sec}'\n")
                new_lines.append(f"gradient_color_2 = '{pri}'\n")

            with open(cava_config_path, "w") as f:
                f.writelines(new_lines)

            # Instantly reload CAVA colors via SIGUSR2 without disrupting audio
            subprocess.run(["pkill", "-USR2", "cava"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"Error updating Cava theme: {e}", file=sys.stderr)

    def update_shared_theme(self, palette):
        try:
            with open(SHARED_COLORS_FILE, "w") as f:
                json.dump(palette, f, indent=2)

            css_content = f"""/* Generated by Bento Wallpaper Theme Engine */
@define-color accent_color {palette['primary']};
@define-color accent_secondary {palette['secondary']};
@define-color accent_fg {palette['on_primary']};
@define-color accent_subtle {palette['accent_subtle']};
@define-color accent_border {palette['border_active']};
"""
            with open(SHARED_CSS_FILE, "w") as f:
                f.write(css_content)

            # Synchronize CAVA visualizer gradient colors
            self.update_cava_theme(palette)

            # Note: No ReloadTheme() called here! Workspace class is switched via JS (0ms lag).
            if self.theme_service:
                self.theme_service.ThemeChanged(SHARED_COLORS_FILE)
        except Exception as e:
            print(f"Error writing shared theme: {e}", file=sys.stderr)

    def set_desktop_background(self, new_wp_path):
        if not new_wp_path:
            return
        new_wp_path = os.path.expanduser(new_wp_path)
        if not os.path.exists(new_wp_path) or self.active_wallpaper == new_wp_path:
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
            if target_wp:
                target_wp = os.path.expanduser(target_wp)
                if os.path.exists(target_wp):
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
