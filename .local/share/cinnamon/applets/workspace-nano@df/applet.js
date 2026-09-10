const Main = imports.ui.main;
const Applet = imports.ui.applet;
const St = imports.gi.St;
const Clutter = imports.gi.Clutter;
const GLib = imports.gi.GLib;
const Gio = imports.gi.Gio;

function getThemeColors() {
    try {
        let path = GLib.get_home_dir() + '/.cache/bento/colors.json';
        let [ok, content] = GLib.file_get_contents(path);
        if (ok) {
            let str = imports.byteArray ? imports.byteArray.toString(content) : content.toString();
            let data = JSON.parse(str);
            if (data && data.primary) {
                return {
                    primary: data.primary,
                    border: data.border_active || 'rgba(245, 194, 231, 0.32)'
                };
            }
        }
    } catch (e) {}
    return {
        primary: '#f5c2e7',
        border: 'rgba(245, 194, 231, 0.32)'
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
        this._currentTheme = getThemeColors();

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
                if (event_type === Gio.FileMonitorEvent.CHANGED ||
                    event_type === Gio.FileMonitorEvent.CHANGES_DONE_HINT ||
                    event_type === Gio.FileMonitorEvent.CREATED) {
                    if (this._updateTimer) {
                        GLib.source_remove(this._updateTimer);
                    }
                    this._updateTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 15, () => {
                        this._updateTimer = null;
                        this._update();
                        return GLib.SOURCE_REMOVE;
                    });
                }
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

    _styleChildIconsAndLabels: function(actor, color) {
        if (!actor) return;
        let isIcon = (actor.has_style_class_name && (
            actor.has_style_class_name('applet-icon') ||
            actor.has_style_class_name('system-status-icon')
        )) || (actor.toString && actor.toString().indexOf('StIcon') !== -1);

        if (isIcon) {
            actor.style = color ? ('color: ' + color + ' !important;') : '';
        } else if (actor.has_style_class_name && actor.has_style_class_name('applet-label')) {
            let t = this._currentTheme || getThemeColors();
            actor.style = color ? ('color: ' + t.primary + ' !important; font-weight: 700;') : 'color: #ffffff !important; font-weight: 600;';
        }

        if (actor.get_children) {
            for (let c of actor.get_children()) {
                this._styleChildIconsAndLabels(c, color);
            }
        }
    },

    _installHover: function(actor) {
        if (!actor || actor._hoverHandlerInstalled) return;
        actor._hoverHandlerInstalled = true;

        actor.connect('notify::hover', () => {
            let t = this._currentTheme || getThemeColors();
            if (actor.hover) {
                actor.style = 'border: 1px solid ' + t.primary + ' !important; background-color: rgba(36, 36, 54, 0.95) !important;';
                this._styleChildIconsAndLabels(actor, t.primary);
            } else {
                actor.style = 'border: 1px solid ' + t.border + ' !important; background-color: rgba(24, 24, 37, 0.85) !important;';
                this._styleChildIconsAndLabels(actor, null);
            }
        });
    },

    _hookCalendarMenu: function(calApplet, theme) {
        if (!calApplet || !calApplet.menu) return;
        let self = this;
        let stylePopup = () => {
            let curTheme = self._currentTheme || theme;
            let findAndStyle = (actor) => {
                if (!actor) return;
                if (actor.has_style_class_name) {
                    if (actor.has_style_class_name('calendar-today')) {
                        actor.style = 'background-color: ' + curTheme.primary + ' !important; color: #11111b !important; border-radius: 9999px !important;';
                    } else if (actor.has_style_class_name('calendar-today-day-label') || actor.has_style_class_name('calendar-events-date-label')) {
                        actor.style = 'color: ' + curTheme.primary + ' !important;';
                    }
                }
                if (actor.get_children) {
                    for (let c of actor.get_children()) findAndStyle(c);
                }
            };
            findAndStyle(calApplet.menu.actor);
        };

        if (!calApplet._dynamicThemeHooked) {
            calApplet._dynamicThemeHooked = true;
            calApplet.menu.connect('open-state-changed', (menu, isOpen) => {
                if (isOpen) {
                    stylePopup();
                    GLib.timeout_add(GLib.PRIORITY_DEFAULT, 40, () => {
                        stylePopup();
                        return GLib.SOURCE_REMOVE;
                    });
                }
            });
        }
        if (calApplet.menu.isOpen) {
            stylePopup();
        }
    },

    _updatePanelCapsules: function(theme) {
        try {
            this._currentTheme = theme;
            let panel = this.panel;
            if (!panel && Main.panelManager && Main.panelManager.panels) {
                for (let p of Main.panelManager.panels) {
                    if (p) { panel = p; break; }
                }
            }
            if (!panel) return;

            let baseCapsuleStyle = 'border: 1px solid ' + theme.border + ' !important; background-color: rgba(24, 24, 37, 0.85) !important;';

            let styleActor = (actor) => {
                if (actor === this.actor) return;

                let isSystray = (actor.has_style_class_name && actor.has_style_class_name('systray')) ||
                                (actor.style_class && actor.style_class.indexOf('systray') !== -1);

                if (isSystray) {
                    actor.style = 'border: none !important; background: transparent !important; margin: 0; padding: 0;';
                    let subBoxes = actor.get_children ? actor.get_children() : [];
                    for (let sBox of subBoxes) {
                        if (sBox && sBox.get_children) {
                            for (let bin of sBox.get_children()) {
                                this._installHover(bin);
                                if (bin.hover) {
                                    bin.style = 'border: 1px solid ' + theme.primary + ' !important; background-color: rgba(36, 36, 54, 0.95) !important; border-radius: 9999px !important; height: 28px !important; padding: 0 8px !important; margin: 6px 2px !important;';
                                    this._styleChildIconsAndLabels(bin, theme.primary);
                                } else {
                                    bin.style = baseCapsuleStyle + ' border-radius: 9999px !important; height: 28px !important; padding: 0 8px !important; margin: 6px 2px !important;';
                                    this._styleChildIconsAndLabels(bin, null);
                                }
                            }
                        }
                    }
                } else if (actor.has_style_class_name && actor.has_style_class_name('applet-box')) {
                    this._installHover(actor);
                    if (actor.hover) {
                        actor.style = 'border: 1px solid ' + theme.primary + ' !important; background-color: rgba(36, 36, 54, 0.95) !important;';
                        this._styleChildIconsAndLabels(actor, theme.primary);
                    } else {
                        actor.style = baseCapsuleStyle;
                        this._styleChildIconsAndLabels(actor, null);
                    }

                    // Special handling for Calendar
                    if (actor._applet && actor._applet._applet_label) {
                        actor._applet._applet_label._isCalendarLabel = true;
                        actor._applet._applet_label.style = 'color: #ffffff !important; font-weight: 600;';
                        this._hookCalendarMenu(actor._applet, theme);
                    }
                }
            };

            for (let box of [panel._leftBox, panel._centerBox, panel._rightBox]) {
                if (!box) continue;
                for (let child of box.get_children()) {
                    styleActor(child);
                }
            }
        } catch (e) {
            global.logError('Error in _updatePanelCapsules: ' + e);
        }
    },

    _update: function() {
        let active_idx = global.workspace_manager.get_active_workspace_index();
        let theme = getThemeColors();
        this._currentTheme = theme;

        // Strip any outer capsule from this.actor completely
        this.actor.style = 'background-color: transparent !important; border: none !important; box-shadow: none !important; padding: 0 !important; margin: 6px 2px !important; height: 28px !important;';

        // Style the single inner workspace capsule
        this.capsule.style = 'spacing: 3px; border: 1px solid ' + theme.border + '; border-radius: 9999px; padding: 2px 6px; background-color: rgba(24, 24, 37, 0.85);';

        this._updatePanelCapsules(theme);

        for (let i = 0; i < this.items.length; i++) {
            let item = this.items[i];
            if (i === active_idx) {
                item.btn.style = 'padding: 0; margin: 0; border: none; background: transparent;';
                item.bin.style = 'background-color: ' + theme.primary + '; border-radius: 9999px; width: 16px; height: 16px;';
                item.lbl.style = 'color: #11111b; font-family: Inter, sans-serif; font-size: 9px; font-weight: 900;';
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
