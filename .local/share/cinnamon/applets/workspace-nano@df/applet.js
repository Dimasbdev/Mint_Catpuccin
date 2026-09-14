const Main = imports.ui.main;
const Applet = imports.ui.applet;
const St = imports.gi.St;
const Clutter = imports.gi.Clutter;
const GLib = imports.gi.GLib;
const Gio = imports.gi.Gio;

let _cachedPalette = null;
let _cachedColors = null;

function invalidatePaletteCache() {
    _cachedPalette = null;
    _cachedColors = null;
}

function getThemeColors(ws_index, forceReload) {
    try {
        if (forceReload) {
            invalidatePaletteCache();
        }
        if (!_cachedPalette) {
            let palettePath = GLib.get_home_dir() + '/.cache/bento/workspaces_palette.json';
            if (GLib.file_test(palettePath, GLib.FileTest.EXISTS)) {
                let [okP, pContent] = GLib.file_get_contents(palettePath);
                if (okP) {
                    let pStr = imports.byteArray ? imports.byteArray.toString(pContent) : pContent.toString();
                    _cachedPalette = JSON.parse(pStr);
                }
            }
        }
        if (_cachedPalette && ws_index !== undefined && ws_index !== null) {
            let wsKey = ws_index.toString();
            if (_cachedPalette[wsKey]) {
                return {
                    primary: _cachedPalette[wsKey].primary,
                    border: _cachedPalette[wsKey].border || 'rgba(245, 194, 231, 0.45)'
                };
            }
        }
        if (!_cachedColors) {
            let path = GLib.get_home_dir() + '/.cache/bento/colors.json';
            if (GLib.file_test(path, GLib.FileTest.EXISTS)) {
                let [ok, content] = GLib.file_get_contents(path);
                if (ok) {
                    let str = imports.byteArray ? imports.byteArray.toString(content) : content.toString();
                    _cachedColors = JSON.parse(str);
                }
            }
        }
        if (_cachedColors && _cachedColors.primary) {
            return {
                primary: _cachedColors.primary,
                border: _cachedColors.border_active || 'rgba(245, 194, 231, 0.45)'
            };
        }
    } catch (e) {
        global.logError('getThemeColors error: ' + e);
    }
    return {
        primary: '#f5c2e7',
        border: 'rgba(245, 194, 231, 0.45)'
    };
}

function isScreenLocked() {
    try {
        let lockFile = '/tmp/bento-lock-1000.locked';
        return GLib.file_test(lockFile, GLib.FileTest.EXISTS);
    } catch (e) {
        return false;
    }
}

function initWorkspaceOsdDynamicTheming() {
    try {
        let WorkspaceOsd = imports.ui.workspaceOsd;
        if (!WorkspaceOsd || !WorkspaceOsd.WorkspaceOsd || WorkspaceOsd.WorkspaceOsd._dynamicThemed) return;
        WorkspaceOsd.WorkspaceOsd._dynamicThemed = true;

        let origRedisplay = WorkspaceOsd.WorkspaceOsd.prototype._redisplay;
        WorkspaceOsd.WorkspaceOsd.prototype._redisplay = function() {
            origRedisplay.call(this);
            if (this._activeWorkspaceIndex !== undefined && this._activeWorkspaceIndex !== null) {
                // Ensure fresh palette is loaded
                invalidatePaletteCache();
                let theme = getThemeColors(this._activeWorkspaceIndex);
                let pri = theme.primary || '#f5c2e7';
                let border = theme.border || 'rgba(245, 194, 231, 0.45)';

                if (this._vbox) {
                    for (let c = 0; c < 8; c++) {
                        this._vbox.remove_style_class_name('ws-' + c);
                    }
                    this._vbox.add_style_class_name('ws-' + this._activeWorkspaceIndex);
                    this._vbox.style = 'color: ' + pri + ' !important; border: 1px solid ' + border + ' !important; background-color: rgba(24, 24, 37, 0.95) !important; border-radius: 9999px !important; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.45) !important; padding: 12px 36px 0 36px;';
                }
                if (this._label) {
                    this._label.style = 'color: ' + pri + ' !important; font-weight: 800 !important;';
                }
                if (this._list) {
                    let children = this._list.get_children ? this._list.get_children() : [];
                    for (let i = 0; i < children.length; i++) {
                        if (i === this._activeWorkspaceIndex) {
                            children[i].style = 'background-color: ' + pri + ' !important; border-radius: 32px; padding: 5.3333333333px; margin: 10.6666666667px;';
                        } else {
                            children[i].style = 'background-color: rgba(239, 241, 245, 0.35) !important; border-radius: 32px; padding: 2.6666666667px; margin: 13.3333333333px;';
                        }
                    }
                }
            }
        };
    } catch (e) {
        global.logError('Failed to initialize WorkspaceOsd dynamic theming: ' + e);
    }
}

function initLockscreenWorkspaceGuard() {
    try {
        let wm = Main.wm;
        if (!wm || wm._lockGuarded) return;
        wm._lockGuarded = true;

        let proto = Object.getPrototypeOf(wm);

        wm.actionMoveWorkspaceLeft = function() {
            if (isScreenLocked()) return;
            proto.actionMoveWorkspaceLeft.call(this);
        };

        wm.actionMoveWorkspaceRight = function() {
            if (isScreenLocked()) return;
            proto.actionMoveWorkspaceRight.call(this);
        };

        wm.actionMoveWorkspaceUp = function() {
            if (isScreenLocked()) return;
            proto.actionMoveWorkspaceUp.call(this);
        };

        wm.actionMoveWorkspaceDown = function() {
            if (isScreenLocked()) return;
            proto.actionMoveWorkspaceDown.call(this);
        };
    } catch (e) {
        global.logError('Failed to initialize lockscreen workspace guard: ' + e);
    }
}

function WorkspaceNanoApplet(metadata, orientation, panel_height, instance_id) {
    this._init(metadata, orientation, panel_height, instance_id);
}

WorkspaceNanoApplet.prototype = {
    __proto__: Applet.Applet.prototype,

    _init: function(metadata, orientation, panel_height, instance_id) {
        Applet.Applet.prototype._init.call(this, orientation, panel_height, instance_id);
        this.metadata = metadata;
        invalidatePaletteCache();
        let active_idx = global.workspace_manager.get_active_workspace_index();
        this._currentTheme = getThemeColors(active_idx);

        initWorkspaceOsdDynamicTheming();
        initLockscreenWorkspaceGuard();

        // Strip any outer capsule styling from this.actor completely
        this.actor.style = "background-color: transparent !important; border: none !important; box-shadow: none !important; padding: 0 !important; margin: 6px 2px !important; height: 28px !important;";

        this.capsule = new St.BoxLayout({
            y_align: Clutter.ActorAlign.CENTER,
            style: "spacing: 3px;"
        });

        this.items = [];
        this.actor.add(this.capsule, { y_align: St.Align.MIDDLE, y_fill: false });

        this._rebuild();

        this._wsChangedId = global.workspace_manager.connect('active-workspace-changed', () => {
            this._update();
        });
        this._wsNumChangedId = global.workspace_manager.connect('notify::n-workspaces', () => this._rebuild());

        this._setupFileMonitors();
    },

    _setupFileMonitors: function() {
        try {
            let paletteFile = Gio.File.new_for_path(GLib.get_home_dir() + '/.cache/bento/workspaces_palette.json');
            this._paletteMonitor = paletteFile.monitor_file(Gio.FileMonitorFlags.NONE, null);
            this._paletteMonitor.connect('changed', (mon, file, other_file, event_type) => {
                invalidatePaletteCache();
                this._scheduleUpdate();
            });
        } catch (e) {
            global.logError('Palette monitor error: ' + e);
        }

        try {
            let colorsFile = Gio.File.new_for_path(GLib.get_home_dir() + '/.cache/bento/colors.json');
            this._colorsMonitor = colorsFile.monitor_file(Gio.FileMonitorFlags.NONE, null);
            this._colorsMonitor.connect('changed', (mon, file, other_file, event_type) => {
                invalidatePaletteCache();
                this._scheduleUpdate();
            });
        } catch (e) {
            global.logError('Colors monitor error: ' + e);
        }
    },

    _scheduleUpdate: function() {
        if (this._updateTimer) {
            GLib.source_remove(this._updateTimer);
        }
        this._updateTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 20, () => {
            this._updateTimer = null;
            this._update();
            return GLib.SOURCE_REMOVE;
        });
    },

    _rebuild: function() {
        this.capsule.destroy_all_children();
        this.items = [];

        let num_ws = global.workspace_manager.n_workspaces;

        for (let i = 0; i < num_ws; i++) {
            let btn = new St.Button({
                reactive: true,
                can_focus: true,
                y_align: Clutter.ActorAlign.CENTER
            });

            let bin = new St.Bin({
                x_align: St.Align.MIDDLE,
                y_align: St.Align.MIDDLE
            });

            let lbl = new St.Label({
                text: (i + 1).toString()
            });

            bin.set_child(lbl);
            btn.set_child(bin);

            let idx = i;
            btn.connect('clicked', () => {
                if (isScreenLocked()) return;
                let ws = global.workspace_manager.get_workspace_by_index(idx);
                if (ws) ws.activate(global.get_current_time());
            });

            this.items.push({ btn: btn, bin: bin, lbl: lbl });
            this.capsule.add(btn, { y_align: St.Align.MIDDLE, y_fill: false });
        }

        this._update();
    },

    _updatePanelClass: function(active_idx) {
        try {
            let panel = this.panel;
            if (!panel && Main.panelManager && Main.panelManager.panels) {
                for (let p of Main.panelManager.panels) {
                    if (p) { panel = p; break; }
                }
            }
            if (panel && panel.actor) {
                for (let i = 0; i < 8; i++) {
                    if (i !== active_idx) {
                        panel.actor.remove_style_class_name('ws-' + i);
                    }
                }
                panel.actor.add_style_class_name('ws-' + active_idx);
            }
            if (Main.uiGroup) {
                for (let i = 0; i < 8; i++) {
                    if (i !== active_idx) {
                        Main.uiGroup.remove_style_class_name('ws-' + i);
                    }
                }
                Main.uiGroup.add_style_class_name('ws-' + active_idx);
            }

            // Also tag all applet popup menus and sound player widgets with ws-<active_idx>
            let panels = (Main.panelManager && Main.panelManager.panels) ? Main.panelManager.panels : (panel ? [panel] : []);
            for (let p of panels) {
                if (!p) continue;
                let boxes = [p._leftBox, p._centerBox, p._rightBox];
                for (let box of boxes) {
                    if (!box || !box.get_children) continue;
                    let children = box.get_children();
                    for (let child of children) {
                        let applet = child._applet || child._delegate;
                        if (!applet) continue;
                        if (applet.menu) {
                            if (applet.menu.actor) {
                                for (let i = 0; i < 8; i++) {
                                    if (i !== active_idx) applet.menu.actor.remove_style_class_name('ws-' + i);
                                }
                                applet.menu.actor.add_style_class_name('ws-' + active_idx);
                            }
                            if (applet.menu.box) {
                                for (let i = 0; i < 8; i++) {
                                    if (i !== active_idx) applet.menu.box.remove_style_class_name('ws-' + i);
                                }
                                applet.menu.box.add_style_class_name('ws-' + active_idx);
                            }
                        }
                        if (applet._players) {
                            for (let pkey in applet._players) {
                                let pl = applet._players[pkey];
                                if (pl && pl.vertBox) {
                                    for (let i = 0; i < 8; i++) {
                                        if (i !== active_idx) pl.vertBox.remove_style_class_name('ws-' + i);
                                    }
                                    pl.vertBox.add_style_class_name('ws-' + active_idx);
                                }
                            }
                        }
                    }
                }
            }
        } catch (e) {
            global.logError('Error updating panel ws class: ' + e);
        }
    },

    _update: function() {
        let active_idx = global.workspace_manager.get_active_workspace_index();
        let theme = getThemeColors(active_idx);
        this._currentTheme = theme;

        this._updatePanelClass(active_idx);

        // Strip any outer capsule from this.actor completely
        this.actor.style = 'background-color: transparent !important; border: none !important; box-shadow: none !important; padding: 0 !important; margin: 6px 2px !important; height: 28px !important;';

        // Style the single inner workspace capsule with dynamic border
        this.capsule.style = 'spacing: 3px; border: 1px solid ' + theme.border + ' !important; border-radius: 9999px; padding: 0 8px; background-color: rgba(24, 24, 37, 0.85); height: 28px !important;';

        for (let i = 0; i < this.items.length; i++) {
            let item = this.items[i];
            if (i === active_idx) {
                item.btn.style = 'padding: 0; margin: 0; border: none; background: transparent;';
                item.bin.style = 'background-color: ' + theme.primary + ' !important; border-radius: 9999px; width: 16px; height: 16px;';
                item.lbl.style = 'color: #11111b !important; font-family: Inter, sans-serif; font-size: 9px; font-weight: 900;';
            } else {
                item.btn.style = 'padding: 0; margin: 0; border: none; background: transparent;';
                item.bin.style = 'background-color: transparent; width: 12px; height: 16px;';
                item.lbl.style = 'color: #a6adc8; font-family: Inter, sans-serif; font-size: 9px; font-weight: 600;';
            }
        }
    },

    on_applet_removed_from_panel: function() {
        if (this._wsChangedId) {
            global.workspace_manager.disconnect(this._wsChangedId);
            this._wsChangedId = null;
        }
        if (this._wsNumChangedId) {
            global.workspace_manager.disconnect(this._wsNumChangedId);
            this._wsNumChangedId = null;
        }
        if (this._paletteMonitor) {
            this._paletteMonitor.cancel();
            this._paletteMonitor = null;
        }
        if (this._colorsMonitor) {
            this._colorsMonitor.cancel();
            this._colorsMonitor = null;
        }
        if (this._updateTimer) {
            GLib.source_remove(this._updateTimer);
            this._updateTimer = null;
        }
    }
};

function main(metadata, orientation, panel_height, instance_id) {
    return new WorkspaceNanoApplet(metadata, orientation, panel_height, instance_id);
}
