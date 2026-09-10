const Main = imports.ui.main;
const Applet = imports.ui.applet;
const St = imports.gi.St;
const Clutter = imports.gi.Clutter;
const GLib = imports.gi.GLib;
const Gio = imports.gi.Gio;

function getThemeColors(ws_index) {
    try {
        let palettePath = GLib.get_home_dir() + '/.cache/bento/workspaces_palette.json';
        if (ws_index !== undefined && ws_index !== null) {
            let [okP, pContent] = GLib.file_get_contents(palettePath);
            if (okP) {
                let pStr = imports.byteArray ? imports.byteArray.toString(pContent) : pContent.toString();
                let pData = JSON.parse(pStr);
                let wsKey = ws_index.toString();
                if (pData && pData[wsKey]) {
                    return {
                        primary: pData[wsKey].primary,
                        border: pData[wsKey].border || 'rgba(245, 194, 231, 0.45)'
                    };
                }
            }
        }
        let path = GLib.get_home_dir() + '/.cache/bento/colors.json';
        let [ok, content] = GLib.file_get_contents(path);
        if (ok) {
            let str = imports.byteArray ? imports.byteArray.toString(content) : content.toString();
            let data = JSON.parse(str);
            if (data && data.primary) {
                return {
                    primary: data.primary,
                    border: data.border_active || 'rgba(245, 194, 231, 0.45)'
                };
            }
        }
    } catch (e) {}
    return {
        primary: '#f5c2e7',
        border: 'rgba(245, 194, 231, 0.45)'
    };
}

function WorkspaceNanoApplet(metadata, orientation, panel_height, instance_id) {
    this._init(metadata, orientation, panel_height, instance_id);
}

WorkspaceNanoApplet.prototype = {
    __proto__: Applet.Applet.prototype,

    _init: function(metadata, orientation, panel_height, instance_id) {
        Applet.Applet.prototype._init.call(this, orientation, panel_height, instance_id);
        this.metadata = metadata;
        let active_idx = global.workspace_manager.get_active_workspace_index();
        this._currentTheme = getThemeColors(active_idx);

        // Strip any outer capsule styling from this.actor completely
        this.actor.style = "background-color: transparent !important; border: none !important; box-shadow: none !important; padding: 0 !important; margin: 6px 2px !important; height: 28px !important;";

        this.capsule = new St.BoxLayout({
            y_align: Clutter.ActorAlign.CENTER,
            style: "spacing: 3px;"
        });

        this.items = [];
        this.actor.add_actor(this.capsule);

        this._rebuild();

        this._wsChangedId = global.workspace_manager.connect('active-workspace-changed', () => {
            this._update();
        });
        this._wsNumChangedId = global.workspace_manager.connect('notify::n-workspaces', () => this._rebuild());

        try {
            let colorsFile = Gio.File.new_for_path(GLib.get_home_dir() + '/.cache/bento/colors.json');
            this._themeMonitor = colorsFile.monitor_file(Gio.FileMonitorFlags.NONE, null);
            this._themeMonitor.connect('changed', (mon, file, other_file, event_type) => {
                if (this._updateTimer) {
                    GLib.source_remove(this._updateTimer);
                }
                this._updateTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 20, () => {
                    this._updateTimer = null;
                    this._update();
                    return GLib.SOURCE_REMOVE;
                });
            });
        } catch (e) {}
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
                let ws = global.workspace_manager.get_workspace_by_index(idx);
                if (ws) ws.activate(global.get_current_time());
            });

            this.items.push({ btn: btn, bin: bin, lbl: lbl });
            this.capsule.add_actor(btn);
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
        this.capsule.style = 'spacing: 3px; border: 1px solid ' + theme.border + ' !important; border-radius: 9999px; padding: 2px 6px; background-color: rgba(24, 24, 37, 0.85);';

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
        if (this._themeMonitor) {
            this._themeMonitor.cancel();
            this._themeMonitor = null;
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
