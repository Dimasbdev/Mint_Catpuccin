#!/usr/bin/env python3
import os, sys, time, json, sqlite3, hashlib, socket, gc, subprocess, threading
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
from gi.repository import Gtk, Gdk, WebKit2, GLib, GdkPixbuf

import Xlib.display
from Xlib.ext import xtest
from Xlib import X, XK

SOCKET_PATH = f"/tmp/bento-clip-{os.getuid()}.sock"
DATA_DIR = os.path.expanduser("~/.local/share/bento-clip")
IMG_DIR = os.path.join(DATA_DIR, "images")
DB_PATH = os.path.join(DATA_DIR, "clipboard.db")

os.makedirs(IMG_DIR, exist_ok=True)

# --- Database Management ---
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS clipboard (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                preview TEXT,
                char_count INTEGER DEFAULT 0,
                img_width INTEGER DEFAULT 0,
                img_height INTEGER DEFAULT 0,
                hash TEXT UNIQUE NOT NULL,
                timestamp INTEGER NOT NULL,
                pinned INTEGER DEFAULT 0
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_clip_time ON clipboard(timestamp DESC)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_clip_hash ON clipboard(hash)')
        conn.commit()

init_db()

def simulate_paste(target_is_terminal=False):
    disp = Xlib.display.Display()
    ctrl_kc = disp.keysym_to_keycode(XK.string_to_keysym('Control_L'))
    v_kc = disp.keysym_to_keycode(XK.string_to_keysym('v'))
    shift_kc = disp.keysym_to_keycode(XK.string_to_keysym('Shift_L'))

    xtest.fake_input(disp, X.KeyPress, ctrl_kc)
    if target_is_terminal:
        xtest.fake_input(disp, X.KeyPress, shift_kc)
    xtest.fake_input(disp, X.KeyPress, v_kc)
    disp.sync()
    time.sleep(0.03)
    xtest.fake_input(disp, X.KeyRelease, v_kc)
    if target_is_terminal:
        xtest.fake_input(disp, X.KeyRelease, shift_kc)
    xtest.fake_input(disp, X.KeyRelease, ctrl_kc)
    disp.sync()

def detect_url_or_code(text):
    stripped = text.strip()
    if stripped.startswith(('http://', 'https://', 'ftp://', 'www.')) and '\n' not in stripped and len(stripped) < 2000:
        return 'url'
    code_indicators = [
        'def ', 'function ', 'class ', 'import ', 'from ', 'const ', 'let ', 'var ',
        '=>', 'SELECT ', 'INSERT ', 'UPDATE ', 'DELETE ', '<html>', '</div>', '<?php',
        '{', '}', 'public ', 'private ', '#include', 'fn '
    ]
    if any(ind in text for ind in code_indicators) and ('\n' in text or len(text) > 40):
        return 'code'
    return 'text'

class BentoClipWindow(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("BentoClipboard")
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
            
        self.set_default_size(720, 560)
        self.set_position(Gtk.WindowPosition.CENTER)
        
        ucm = WebKit2.UserContentManager()
        ucm.register_script_message_handler("clip")
        ucm.connect("script-message-received::clip", self.on_clip_message)

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
        
        html_path = os.path.join(DATA_DIR, "index.html")
        self.webview.load_uri(f"file://{html_path}")
        
        self.add(self.webview)
        self.connect("key-press-event", self.on_key_press)
        self.connect("focus-out-event", self.on_focus_out)
        self.connect("destroy", Gtk.main_quit)

        self.is_self_copying = False
        self.last_active_window = None
        self.is_visible = False
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

        # Connect Gtk.Clipboard listener
        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.clipboard.connect("owner-change", self.on_clipboard_owner_change)

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
                root.style.setProperty('--glow', '{theme['accent_subtle']}');
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

    def on_focus_out(self, widget, event):
        if self.is_visible:
            self.hide_popup()
        return False

    def on_clipboard_owner_change(self, clipboard, event):
        if self.is_self_copying:
            return
        
        GLib.timeout_add(80, self.process_new_clipboard_item)

    def process_new_clipboard_item(self):
        try:
            # 1. Check if image
            if self.clipboard.wait_is_image_available():
                pixbuf = self.clipboard.wait_for_image()
                if pixbuf:
                    self.store_image_item(pixbuf)
                    return False
        except Exception:
            pass

        try:
            # 2. Check if text
            if self.clipboard.wait_is_text_available():
                text = self.clipboard.wait_for_text()
                if text and len(text.strip()) > 0:
                    self.store_text_item(text)
                    return False
        except Exception:
            pass

        return False

    def store_text_item(self, text):
        h = hashlib.sha256(text.encode('utf-8')).hexdigest()
        now = int(time.time())
        item_type = detect_url_or_code(text)
        preview = text[:180].replace('\r', '')
        
        with get_db() as conn:
            # Check if exists
            row = conn.execute('SELECT id, pinned FROM clipboard WHERE hash = ?', (h,)).fetchone()
            if row:
                conn.execute('UPDATE clipboard SET timestamp = ? WHERE id = ?', (now, row['id']))
            else:
                conn.execute('''
                    INSERT INTO clipboard (type, content, preview, char_count, hash, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (item_type, text, preview, len(text), h, now))
                
                # Trim older than 120 unpinned
                conn.execute('''
                    DELETE FROM clipboard WHERE id NOT IN (
                        SELECT id FROM clipboard ORDER BY pinned DESC, timestamp DESC LIMIT 120
                    ) AND pinned = 0
                ''')
            conn.commit()

        if self.is_visible:
            self.refresh_ui()

    def store_image_item(self, pixbuf):
        w = pixbuf.get_width()
        h_dim = pixbuf.get_height()
        pixels = pixbuf.get_pixels()
        h = hashlib.sha256(pixels).hexdigest()
        now = int(time.time())
        
        img_filename = f"{h}.png"
        img_path = os.path.join(IMG_DIR, img_filename)
        if not os.path.exists(img_path):
            pixbuf.savev(img_path, "png", [], [])

        with get_db() as conn:
            row = conn.execute('SELECT id FROM clipboard WHERE hash = ?', (h,)).fetchone()
            if row:
                conn.execute('UPDATE clipboard SET timestamp = ? WHERE id = ?', (now, row['id']))
            else:
                conn.execute('''
                    INSERT INTO clipboard (type, content, preview, img_width, img_height, hash, timestamp)
                    VALUES ('image', ?, ?, ?, ?, ?, ?)
                ''', (img_path, img_path, w, h_dim, h, now))
                
                # Cleanup old images
                old_rows = conn.execute('''
                    SELECT content FROM clipboard WHERE id NOT IN (
                        SELECT id FROM clipboard ORDER BY pinned DESC, timestamp DESC LIMIT 120
                    ) AND pinned = 0 AND type = 'image'
                ''').fetchall()
                for orow in old_rows:
                    try:
                        if os.path.exists(orow['content']):
                            os.unlink(orow['content'])
                    except Exception:
                        pass
                conn.execute('''
                    DELETE FROM clipboard WHERE id NOT IN (
                        SELECT id FROM clipboard ORDER BY pinned DESC, timestamp DESC LIMIT 120
                    ) AND pinned = 0
                ''')
            conn.commit()

        if self.is_visible:
            self.refresh_ui()

    def show_popup(self):
        # Capture current active window ID to return focus to
        try:
            out = subprocess.check_output(['xprop', '-root', '_NET_ACTIVE_WINDOW']).decode().strip()
            self.last_active_window = out.split()[-1]
        except Exception:
            self.last_active_window = None

        self.stick()
        self.set_keep_above(True)
        self.is_visible = True
        self.apply_theme_from_file()
        self.show_all()
        self.present()
        self.grab_focus()
        self.webview.grab_focus()
        self.refresh_ui()

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

    def refresh_ui(self):
        with get_db() as conn:
            rows = conn.execute('''
                SELECT id, type, content, preview, char_count, img_width, img_height, timestamp, pinned
                FROM clipboard ORDER BY pinned DESC, timestamp DESC LIMIT 100
            ''').fetchall()
            
            items = []
            for r in rows:
                items.append({
                    "id": r['id'],
                    "type": r['type'],
                    "content": r['content'] if r['type'] != 'image' else '',
                    "preview": r['preview'],
                    "char_count": r['char_count'],
                    "img_width": r['img_width'],
                    "img_height": r['img_height'],
                    "timestamp": r['timestamp'],
                    "pinned": bool(r['pinned'])
                })
                
        js_code = f"if (window.renderClipboard) {{ renderClipboard({json.dumps(items)}); }}"
        self.webview.run_javascript(js_code)

    def on_clip_message(self, ucm, js_result):
        val = js_result.get_js_value()
        try:
            data = json.loads(val.to_string())
            action = data.get("action")
            item_id = data.get("id")

            if action == "paste":
                self.paste_item(item_id)
            elif action == "copy":
                self.copy_item(item_id)
            elif action == "delete":
                self.delete_item(item_id)
            elif action == "toggle_pin":
                self.toggle_pin(item_id)
            elif action == "clear_all":
                self.clear_all()
            elif action == "close":
                self.hide_popup()
        except Exception as e:
            print("Clip action error:", e)

    def copy_item(self, item_id):
        with get_db() as conn:
            row = conn.execute('SELECT type, content FROM clipboard WHERE id = ?', (item_id,)).fetchone()
            if not row:
                return
            
            self.is_self_copying = True
            if row['type'] == 'image':
                if os.path.exists(row['content']):
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(row['content'])
                    self.clipboard.set_image(pixbuf)
                    self.clipboard.store()
            else:
                self.clipboard.set_text(row['content'], -1)
                self.clipboard.store()
                
            GLib.timeout_add(150, self.reset_self_copying)

    def reset_self_copying(self):
        self.is_self_copying = False
        return False

    def paste_item(self, item_id):
        # 1. Copy item to clipboard
        self.copy_item(item_id)
        
        # 2. Hide popup
        self.is_visible = False
        self.hide()
        Gdk.flush()
        if os.path.exists(SOCKET_PATH):
            try:
                os.unlink(SOCKET_PATH)
            except OSError:
                pass
        
        # 3. Detect if target was terminal
        target_is_term = False
        if self.last_active_window:
            try:
                wm_cls = subprocess.check_output(['xprop', '-id', self.last_active_window, 'WM_CLASS']).decode().lower()
                if any(t in wm_cls for t in ('kitty', 'terminal', 'alacritty', 'term')):
                    target_is_term = True
                # Re-activate the target window
                subprocess.run(['wmctrl', '-ia', self.last_active_window])
            except Exception:
                pass

        # 4. Synthesize paste after focus returned then quit
        def do_paste_and_quit():
            simulate_paste(target_is_term)
            time.sleep(0.04)
            Gtk.main_quit()
            return False

        GLib.timeout_add(100, do_paste_and_quit)

    def delete_item(self, item_id):
        with get_db() as conn:
            row = conn.execute('SELECT type, content FROM clipboard WHERE id = ?', (item_id,)).fetchone()
            if row and row['type'] == 'image':
                try:
                    if os.path.exists(row['content']):
                        os.unlink(row['content'])
                except Exception:
                    pass
            conn.execute('DELETE FROM clipboard WHERE id = ?', (item_id,))
            conn.commit()
        self.refresh_ui()

    def toggle_pin(self, item_id):
        with get_db() as conn:
            conn.execute('UPDATE clipboard SET pinned = 1 - pinned WHERE id = ?', (item_id,))
            conn.commit()
        self.refresh_ui()

    def clear_all(self):
        with get_db() as conn:
            rows = conn.execute("SELECT content FROM clipboard WHERE pinned = 0 AND type = 'image'").fetchall()
            for r in rows:
                try:
                    if os.path.exists(r['content']):
                        os.unlink(r['content'])
                except Exception:
                    pass
            conn.execute('DELETE FROM clipboard WHERE pinned = 0')
            conn.commit()
        self.refresh_ui()

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
    win = BentoClipWindow()
    srv = setup_socket_server(win)
    win.show_popup()
    Gtk.main()

if __name__ == "__main__":
    main()
