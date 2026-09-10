const Applet = imports.ui.applet;
const Util = imports.misc.util;

function PowerButtonApplet(metadata, orientation, panel_height, instance_id) {
    this._init(metadata, orientation, panel_height, instance_id);
}

PowerButtonApplet.prototype = {
    __proto__: Applet.IconApplet.prototype,

    _init: function(metadata, orientation, panel_height, instance_id) {
        Applet.IconApplet.prototype._init.call(this, orientation, panel_height, instance_id);
        this.set_applet_icon_symbolic_name("system-shutdown-symbolic");
        this.set_applet_tooltip("Power / Session Options");
    },

    on_applet_clicked: function(event) {
        Util.spawnCommandLine("/home/df/.local/bin/bento-power");
    }
};

function main(metadata, orientation, panel_height, instance_id) {
    return new PowerButtonApplet(metadata, orientation, panel_height, instance_id);
}
