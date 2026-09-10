const Applet = imports.ui.applet;
const St = imports.gi.St;
const Clutter = imports.gi.Clutter;

function WorkspaceMiniApplet(metadata, orientation, panel_height, instance_id) {
    this._init(metadata, orientation, panel_height, instance_id);
}

WorkspaceMiniApplet.prototype = {
    __proto__: Applet.Applet.prototype,

    _init: function(metadata, orientation, panel_height, instance_id) {
        Applet.Applet.prototype._init.call(this, orientation, panel_height, instance_id);
        this.metadata = metadata;
        this.orientation = orientation;

        this.actor.style = "padding: 0; margin: 0;";

        this.capsule = new St.BoxLayout({
            style_class: "noctalia-outer-capsule",
            y_align: Clutter.ActorAlign.CENTER,
            style: "spacing: 3px; padding: 0 2px;"
        });

        this.items = [];
        this.actor.add_actor(this.capsule);

        this._rebuild();

        this._wsChangedId = global.workspace_manager.connect('active-workspace-changed', () => this._update());
        this._wsNumChangedId = global.workspace_manager.connect('notify::n-workspaces', () => this._rebuild());
    },

    _rebuild: function() {
        this.capsule.destroy_all_children();
        this.items = [];

        let num_ws = global.workspace_manager.n_workspaces;

        for (let i = 0; i < num_ws; i++) {
            let btn = new St.Button({
                reactive: true,
                can_focus: true,
                style: "padding: 0; margin: 0; border: none; background: transparent;",
                y_align: Clutter.ActorAlign.CENTER,
                x_align: Clutter.ActorAlign.CENTER
            });

            let bin = new St.Bin({
                x_align: St.Align.MIDDLE,
                y_align: St.Align.MIDDLE
            });

            let lbl = new St.Label({
                text: (i + 1).toString(),
                style: "font-family: Inter, sans-serif; font-size: 9px; font-weight: bold;"
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

    _update: function() {
        let active_idx = global.workspace_manager.get_active_workspace_index();

        for (let i = 0; i < this.items.length; i++) {
            let item = this.items[i];
            if (i === active_idx) {
                // Petite 16x16 circular pink badge with plenty of breathing room
                item.bin.style = "background-color: #f5c2e7; border-radius: 9999px; width: 16px; height: 16px; margin: 0 2px;";
                item.lbl.style = "color: #11111b; font-size: 9px; font-weight: 900;";
            } else {
                // Inactive workspace
                item.bin.style = "background-color: transparent; width: 14px; height: 16px; margin: 0 1px;";
                item.lbl.style = "color: #a6adc8; font-size: 9px; font-weight: 600;";
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
    }
};

function main(metadata, orientation, panel_height, instance_id) {
    return new WorkspaceMiniApplet(metadata, orientation, panel_height, instance_id);
}
