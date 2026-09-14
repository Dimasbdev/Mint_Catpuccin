#!/usr/bin/env python3
"""
Lightweight Clipboard Listener Daemon (No WebKit)
Monitors clipboard changes and records text and images to SQLite.
"""
import os, sys, time, sqlite3, hashlib
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib

DATA_DIR = os.path.expanduser("~/.local/share/bento-clip")
IMG_DIR = os.path.join(DATA_DIR, "images")
DB_PATH = os.path.join(DATA_DIR, "clipboard.db")

os.makedirs(IMG_DIR, exist_ok=True)

def recover_corrupt_db():
    try:
        if os.path.exists(DB_PATH):
            backup_path = f"{DB_PATH}.corrupt.{int(time.time())}"
            os.rename(DB_PATH, backup_path)
    except Exception:
        pass
    _create_tables()

def _create_tables():
    try:
        conn = sqlite3.connect(DB_PATH)
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
        conn.close()
    except Exception:
        pass

def get_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA schema_version;')
        return conn
    except sqlite3.DatabaseError:
        recover_corrupt_db()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

def init_db():
    try:
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
    except sqlite3.DatabaseError:
        recover_corrupt_db()

init_db()

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

class ClipboardDaemon:
    def __init__(self):
        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.clipboard.connect("owner-change", self.on_clipboard_owner_change)

    def on_clipboard_owner_change(self, clipboard, event):
        GLib.timeout_add(80, self.process_new_clipboard_item)

    def process_new_clipboard_item(self):
        try:
            if self.clipboard.wait_is_image_available():
                pixbuf = self.clipboard.wait_for_image()
                if pixbuf:
                    self.store_image_item(pixbuf)
                    return False
        except Exception:
            pass

        try:
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
            row = conn.execute('SELECT id, pinned FROM clipboard WHERE hash = ?', (h,)).fetchone()
            if row:
                conn.execute('UPDATE clipboard SET timestamp = ? WHERE id = ?', (now, row['id']))
            else:
                conn.execute('''
                    INSERT INTO clipboard (type, content, preview, char_count, hash, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (item_type, text, preview, len(text), h, now))

                conn.execute('''
                    DELETE FROM clipboard WHERE id NOT IN (
                        SELECT id FROM clipboard ORDER BY pinned DESC, timestamp DESC LIMIT 120
                    ) AND pinned = 0
                ''')
            conn.commit()

    def store_image_item(self, pixbuf):
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
                ''', (img_path, img_path, pixbuf.get_width(), pixbuf.get_height(), h, now))

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

def main():
    daemon = ClipboardDaemon()
    Gtk.main()

if __name__ == "__main__":
    main()
