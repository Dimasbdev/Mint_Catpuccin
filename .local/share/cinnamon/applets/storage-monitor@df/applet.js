const Applet = imports.ui.applet;
const GLib = imports.gi.GLib;
const Mainloop = imports.mainloop;
const St = imports.gi.St;
const Util = imports.misc.util;

function StorageApplet(metadata, orientation, panel_height, instance_id) {
    this._init(metadata, orientation, panel_height, instance_id);
}

StorageApplet.prototype = {
    __proto__: Applet.TextIconApplet.prototype,

    _init: function(metadata, orientation, panel_height, instance_id) {
        Applet.TextIconApplet.prototype._init.call(this, orientation, panel_height, instance_id);

        this.set_applet_icon_symbolic_name("drive-harddisk-symbolic");
        this.set_applet_tooltip("Disk Storage Remaining");

        this._update();
    },

    _update: function() {
        try {
            let [res, out] = GLib.spawn_command_line_sync("df -h /");
            if (res) {
                let lines = out.toString().trim().split("\n");
                if (lines.length > 1) {
                    let parts = lines[1].trim().split(/\s+/);
                    if (parts.length >= 4) {
                        let avail = parts[3];
                        let used_pct = parts[4];
                        this.set_applet_label(avail);
                        this.set_applet_tooltip("Sisa Penyimpanan: " + avail + " (Terpakai: " + used_pct + ")");
                    }
                }
            }
        } catch (e) {
            global.logError("StorageApplet error: " + e);
        }

        this._timeout = Mainloop.timeout_add_seconds(10, () => {
            this._update();
            return false;
        });
    },

    on_applet_clicked: function() {
        Util.spawnCommandLine("baobab");
    },

    on_applet_removed_from_panel: function() {
        if (this._timeout) {
            Mainloop.source_remove(this._timeout);
            this._timeout = null;
        }
    }
};

function main(metadata, orientation, panel_height, instance_id) {
    return new StorageApplet(metadata, orientation, panel_height, instance_id);
}
