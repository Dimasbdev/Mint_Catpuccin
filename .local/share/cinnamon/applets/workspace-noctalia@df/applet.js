const Applet = imports.ui.applet;
const St = imports.gi.St;
const Clutter = imports.gi.Clutter;

function WorkspaceNoctaliaApplet(metadata, orientation, panel_height, instance_id) {
    this._init(metadata, orientation, panel_height, instance_id);
}

WorkspaceNoctaliaApplet.prototype = {
    __proto__: Applet.Applet.prototype,

    _init: function(metadata, orientation, panel_height, instance_id) {
        Applet.Applet.prototype._init.call(this, orientation, panel_height, instance_id);
        this.metadata = metadata;
        this.orientation = orientation;

        this.actor.style = "padding: 0; margin: 0;";

        this.capsule = new St.BoxLayout({
            style_class: "noctalia-ws-capsule",
            y_align: Clutter.ActorAlign.CENTER,
            style: "spacing: 2px;"
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

            let lbl = new St.Label({
                text: (i + 1).toString(),
                y_align: Clutter.ActorAlign.CENTER,
                x_align: Clutter.ActorAlign.CENTER
            });

            btn.set_child(lbl);

            let idx = i;
            btn.connect('clicked', () => {
                let ws = global.workspace_manager.get_workspace_by_index(idx);
                if (ws) ws.activate(global.get_current_time());
            });

            this.items.push({ btn: btn, lbl: lbl });
            this.capsule.add_actor(btn);
        }

        this._update();
    },

    _update: function() {
        let active_idx = global.workspace_manager.get_active_workspace_index();

        for (let i = 0; i < this.items.length; i++) {
            let item = this.items[i];
            if (i === active_idx) {
                // Active workspace: 20x20 round pink badge with centered number
                item.btn.style = "padding: 0; margin: 0 2px; border: none; background: transparent;";
                item.lbl.style = "background-color: #f5c2e7; color: #11111b; width: 20px; height: 20px; border-radius: 9999px; text-align: center; font-family: Inter, sans-serif; font-size: 10px; font-weight: bold; padding-top: 3px;";
            } else {
                // Inactive workspace: sleek number
                item.btn.style = "padding: 0; margin: 0 1px; border: none; background: transparent;";
                item.lbl.style = "background-color: transparent; color: #a6adc8; width: 16px; height: 20px; text-align: center; font-family: Inter, sans-serif; font-size: 10px; font-weight: 600; padding-top: 3px;";
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
    return new WorkspaceNoctaliaApplet(metadata, orientation, panel_height, instance_id);
}
