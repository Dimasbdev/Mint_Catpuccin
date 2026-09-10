const Applet = imports.ui.applet;
const St = imports.gi.St;
const Clutter = imports.gi.Clutter;

function WorkspacePillApplet(metadata, orientation, panel_height, instance_id) {
    this._init(metadata, orientation, panel_height, instance_id);
}

WorkspacePillApplet.prototype = {
    __proto__: Applet.Applet.prototype,

    _init: function(metadata, orientation, panel_height, instance_id) {
        Applet.Applet.prototype._init.call(this, orientation, panel_height, instance_id);
        this.metadata = metadata;
        this.orientation = orientation;

        this.actor.style = "padding: 0; margin: 0;";

        this.capsule = new St.BoxLayout({
            style_class: "noctalia-outer-capsule",
            y_align: Clutter.ActorAlign.CENTER
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
                style: "padding: 0; margin: 0 1px; border: none; background: transparent;",
                y_align: Clutter.ActorAlign.CENTER,
                x_align: Clutter.ActorAlign.CENTER
            });

            let box = new St.BoxLayout({
                y_align: Clutter.ActorAlign.CENTER,
                x_align: Clutter.ActorAlign.CENTER
            });

            let lbl = new St.Label({
                text: (i + 1).toString(),
                y_align: Clutter.ActorAlign.CENTER,
                x_align: Clutter.ActorAlign.CENTER
            });

            box.add_actor(lbl);
            btn.set_child(box);

            let idx = i;
            btn.connect('clicked', () => {
                let ws = global.workspace_manager.get_workspace_by_index(idx);
                if (ws) ws.activate(global.get_current_time());
            });

            this.items.push({ btn: btn, box: box, lbl: lbl });
            this.capsule.add_actor(btn);
        }

        this._update();
    },

    _update: function() {
        let active_idx = global.workspace_manager.get_active_workspace_index();

        for (let i = 0; i < this.items.length; i++) {
            let item = this.items[i];
            if (i === active_idx) {
                // Active workspace: 20x18 cute pink pill with perfectly centered black number
                item.box.style = "background-color: #f5c2e7; border-radius: 9999px; width: 22px; height: 18px; margin: 1px 2px;";
                item.lbl.style = "color: #11111b; font-family: Inter, sans-serif; font-size: 10px; font-weight: 800; text-align: center;";
            } else {
                // Inactive workspace
                item.box.style = "background-color: transparent; border-radius: 9999px; width: 18px; height: 18px; margin: 1px 1px;";
                item.lbl.style = "color: #a6adc8; font-family: Inter, sans-serif; font-size: 10px; font-weight: 600; text-align: center;";
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
    return new WorkspacePillApplet(metadata, orientation, panel_height, instance_id);
}
