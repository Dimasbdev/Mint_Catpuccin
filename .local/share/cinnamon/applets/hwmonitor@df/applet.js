const Applet = imports.ui.applet;
const GLib = imports.gi.GLib;
const Mainloop = imports.mainloop;
const Util = imports.misc.util;

function HWMonitorApplet(metadata, orientation, panel_height, instance_id) {
    this._init(metadata, orientation, panel_height, instance_id);
}

HWMonitorApplet.prototype = {
    __proto__: Applet.TextApplet.prototype,

    _init: function(metadata, orientation, panel_height, instance_id) {
        Applet.TextApplet.prototype._init.call(this, orientation, panel_height, instance_id);

        this._last_idle = 0;
        this._last_total = 0;
        this._decoder = new TextDecoder();

        // Cari sensor suhu CPU yang paling akurat (x86_pkg_temp atau default zone0)
        this._temp_path = "/sys/class/thermal/thermal_zone0/temp";
        for (let i = 0; i <= 8; i++) {
            let [ok, content] = GLib.file_get_contents(`/sys/class/thermal/thermal_zone${i}/type`);
            if (ok && this._decoder.decode(content).trim() === "x86_pkg_temp") {
                this._temp_path = `/sys/class/thermal/thermal_zone${i}/temp`;
                break;
            }
        }

        this.set_applet_label(" --°C  󰍛 --%");
        this.set_applet_tooltip("Monitor Suhu & RAM\nKlik untuk membuka Btop");

        this._update();
    },

    _update: function() {
        try {
            // 1. Suhu Laptop (CPU Temperature)
            let temp_str = "--°C";
            let [ok_temp, temp_content] = GLib.file_get_contents(this._temp_path);
            if (ok_temp) {
                let temp_text = this._decoder.decode(temp_content);
                let raw_temp = parseInt(temp_text.trim(), 10);
                temp_str = `${Math.round(raw_temp / 1000)}°C`;
            }

            // 2. RAM Usage
            let ram_pct = 0;
            let ram_used_gb = "0";
            let ram_total_gb = "0";
            let [ok_mem, mem_content] = GLib.file_get_contents("/proc/meminfo");
            if (ok_mem) {
                let mem_text = this._decoder.decode(mem_content);
                let lines = mem_text.split("\n");
                let mem = {};
                for (let l of lines) {
                    let p = l.split(":");
                    if (p.length === 2) {
                        mem[p[0].trim()] = parseInt(p[1].trim().split(/\s+/)[0], 10);
                    }
                }
                if (mem["MemTotal"] && mem["MemAvailable"]) {
                    let total_kb = mem["MemTotal"];
                    let avail_kb = mem["MemAvailable"];
                    let used_kb = total_kb - avail_kb;
                    ram_pct = Math.round((used_kb / total_kb) * 100);
                    ram_used_gb = (used_kb / (1024 * 1024)).toFixed(1);
                    ram_total_gb = (total_kb / (1024 * 1024)).toFixed(1);
                }
            }

            // 3. CPU Load % (untuk info di tooltip)
            let cpu_pct = 0;
            let [ok_stat, stat_content] = GLib.file_get_contents("/proc/stat");
            if (ok_stat) {
                let text = this._decoder.decode(stat_content);
                let first_line = text.split("\n")[0];
                let parts = first_line.trim().split(/\s+/).slice(1).map(Number);
                let idle = parts[3];
                let total = parts.reduce((a, b) => a + b, 0);

                if (this._last_total > 0) {
                    let idle_delta = idle - this._last_idle;
                    let total_delta = total - this._last_total;
                    if (total_delta > 0) {
                        cpu_pct = Math.round(100 * (1 - idle_delta / total_delta));
                        if (cpu_pct < 0) cpu_pct = 0;
                        if (cpu_pct > 100) cpu_pct = 100;
                    }
                }
                this._last_idle = idle;
                this._last_total = total;
            }

            this.set_applet_label(` ${temp_str}   󰍛 ${ram_pct}%`);
            this.set_applet_tooltip(`Suhu Laptop: ${temp_str}\nRAM: ${ram_used_gb} GB / ${ram_total_gb} GB (${ram_pct}%)\nBeban CPU: ${cpu_pct}%\n\nKlik untuk membuka Btop`);
        } catch (e) {
            global.logError("HWMonitorApplet error: " + e);
        }

        this._timeout = Mainloop.timeout_add_seconds(2, () => {
            this._update();
            return false;
        });
    },

    on_applet_clicked: function() {
        Util.spawnCommandLine("kitty -e btop");
    },

    on_applet_removed_from_panel: function() {
        if (this._timeout) {
            Mainloop.source_remove(this._timeout);
            this._timeout = null;
        }
    }
};

function main(metadata, orientation, panel_height, instance_id) {
    return new HWMonitorApplet(metadata, orientation, panel_height, instance_id);
}
