#!/usr/bin/env python3
import gi, sys
gi.require_version('Wnck', '3.0')
gi.require_version('GLib', '2.0')
from gi.repository import Wnck, GLib

GAP = 12
TOP = 46
BOTTOM = 66

is_tiling_queued = False

TILED_CLASSES = {"kitty", "alacritty", "gnome-terminal", "wezterm", "xterm", "tilix", "terminal"}
IGNORED_NAMES = {"caelestia", "lockscreen", "looking glass", "cinnamon-screensaver"}

def compute_dwindle_layout(n, screen_w, screen_h, gap=GAP, top=TOP, bottom=BOTTOM):
    if n <= 0:
        return []
    
    screen_x = gap
    screen_y = top + gap
    usable_w = screen_w - (2 * gap)
    usable_h = screen_h - top - bottom - (2 * gap)

    if n == 1:
        return [(screen_x, screen_y, usable_w, usable_h)]
    
    boxes = []
    cur_x, cur_y, cur_w, cur_h = screen_x, screen_y, usable_w, usable_h
    horizontal_split = False
    
    for i in range(n - 1):
        if not horizontal_split:
            split_w = (cur_w - gap) // 2
            boxes.append((cur_x, cur_y, split_w, cur_h))
            cur_x = cur_x + split_w + gap
            cur_w = cur_w - split_w - gap
            horizontal_split = True
        else:
            split_h = (cur_h - gap) // 2
            boxes.append((cur_x, cur_y, cur_w, split_h))
            cur_y = cur_y + split_h + gap
            cur_h = cur_h - split_h - gap
            horizontal_split = False
            
    boxes.append((cur_x, cur_y, cur_w, cur_h))
    return boxes

def is_tileable_window(w, ws):
    if not w or w.get_workspace() != ws:
        return False
    if w.get_window_type() != Wnck.WindowType.NORMAL:
        return False
    if w.is_minimized() or w.is_skip_tasklist() or w.is_skip_pager():
        return False
    
    name = (w.get_name() or "").lower()
    cname = (w.get_class_group_name() or "").lower()
    iname = (w.get_class_instance_name() or "").lower()
    
    for ign in IGNORED_NAMES:
        if ign in name or ign in cname:
            return False
            
    return any(t in cname or t in iname for t in TILED_CLASSES)

def tile_workspace():
    screen = Wnck.Screen.get_default()
    ws = screen.get_active_workspace()
    if not ws:
        return
        
    windows = [w for w in screen.get_windows() if is_tileable_window(w, ws)]
    
    n = len(windows)
    if n <= 1:
        return
        
    screen_w = screen.get_width()
    screen_h = screen.get_height()
    coords = compute_dwindle_layout(n, screen_w, screen_h)
    
    mask = (
        Wnck.WindowMoveResizeMask.X | 
        Wnck.WindowMoveResizeMask.Y | 
        Wnck.WindowMoveResizeMask.WIDTH | 
        Wnck.WindowMoveResizeMask.HEIGHT
    )
    
    for w, (x, y, width, height) in zip(windows, coords):
        if w.is_maximized():
            w.unmaximize()
            
        gx, gy, gw, gh = w.get_geometry()
        if gx == x and gy == y and gw == width and gh == height:
            continue
            
        w.set_geometry(Wnck.WindowGravity.NORTHWEST, mask, x, y, width, height)

def trigger_tile_idle():
    global is_tiling_queued
    is_tiling_queued = False
    tile_workspace()
    return False

def on_change(screen, win):
    global is_tiling_queued
    ws = screen.get_active_workspace()
    if win and not is_tileable_window(win, ws):
        return
    if not is_tiling_queued:
        is_tiling_queued = True
        GLib.idle_add(trigger_tile_idle)

def main():
    if "--daemon" in sys.argv:
        screen = Wnck.Screen.get_default()
        screen.force_update()
        
        screen.connect("window-opened", on_change)
        screen.connect("window-closed", on_change)
        
        loop = GLib.MainLoop()
        loop.run()
    else:
        tile_workspace()

if __name__ == "__main__":
    main()
