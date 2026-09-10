<div align="center">

# 🍃 mint-catppuccin

**Aesthetic Linux Mint Cinnamon Rice • Catppuccin Flamingo Dark**

[![Linux Mint](https://img.shields.io/badge/Linux%20Mint-22.x%20(Zena)-87CF3E?style=flat-square&logo=linux-mint&logoColor=white)](https://linuxmint.com/)
[![Desktop](https://img.shields.io/badge/Desktop-Cinnamon-35D499?style=flat-square)](https://github.com/linuxmint/cinnamon)
[![Theme](https://img.shields.io/badge/Theme-Catppuccin%20Flamingo-F2CDCD?style=flat-square&logo=catppuccin&logoColor=1E1E2E)](https://github.com/catppuccin/catppuccin)
[![Terminal](https://img.shields.io/badge/Terminal-Kitty-202646?style=flat-square&logo=kitty&logoColor=white)](https://sw.kovidgoyal.net/kitty/)
[![Shell Prompt](https://img.shields.io/badge/Prompt-Starship-DD0B78?style=flat-square&logo=starship&logoColor=white)](https://starship.rs/)
[![License](https://img.shields.io/badge/License-MIT-blue?style=flat-square)](LICENSE)

*Kumpulan dotfiles dan konfigurasi ricing personal untuk Linux Mint Cinnamon bernuansa Catppuccin.*

[Fitur](#-fitur-utama) • [Spesifikasi](#-spesifikasi-ricing) • [Instalasi](#-instalasi) • [Struktur](#-struktur-repositori) • [Pintasan](#-shortcut--perintah)

</div>

---

## 📸 Showcase

> Simpan screenshot desktop Anda di folder `assets/screenshots/` dan tampilkan di sini.

<div align="center">

| 🖥️ Wallpaper Default |
|:---:|
| ![Wallpaper](assets/wallpapers/default.jpg) |

</div>

---

## ✨ Fitur Utama

- **🎨 Tema Catppuccin Flamingo:** Tema GTK dan panel Cinnamon `Catppuccin-Flamingo-Dark`, ikon `Papirus-Dark`, dan kursor `catppuccin-mocha-flamingo`.
- **🧩 Custom Cinnamon Applets (`@df`):**
  - `menu-search@df`: Menu launcher pencarian cepat pada panel.
  - `workspace-nano@df`: Switcher workspace minimalis berbentuk pill.
  - `hwmonitor@df`: Monitor penggunaan CPU dan RAM langsung di panel.
  - `storage-monitor@df`: Indikator pemakaian penyimpanan disk.
  - `power-button@df`: Tombol menu power di ujung panel.
- **🖥️ Desktop UI & Utility Modules:**
  - **Control Center**: Panel quick settings untuk audio, display, dan status baterai.
  - **Clipboard Manager**: Pengelola riwayat salinan teks dan gambar berbasis grid.
  - **Floating OSD**: Indikator pop-up volume dan brightness mengambang.
  - **Lock Screen & Power Menu**: Layar kunci dan dialog shutdown / reboot / suspend.
  - **Wallpaper Switcher**: Daemon pengatur wallpaper dinamis per-workspace.
- **💻 Terminal & CLI Tools:**
  - **Kitty**: Konfigurasi terminal emulator dengan tema gelap.
  - **Starship**: Prompt shell modern dengan tema Catppuccin.
  - **Fastfetch**: Konfigurasi tampilan info sistem.
  - **Btop**: Monitor sistem interaktif bertema Catppuccin.
  - **Cava**: Audio visualizer bar.
  - **Sptlrx**: Tampilan lirik lagu sinkron via MPRIS.
- **⚓ Dock:** Konfigurasi Plank dock di bagian bawah layar.

---

## 🛠 Spesifikasi Ricing

| Komponen | Pilihan / Konfigurasi |
| :--- | :--- |
| **Distro** | Linux Mint 22.x (Zena) |
| **Desktop** | Cinnamon |
| **GTK Theme** | Catppuccin-Flamingo-Dark |
| **Icon Theme** | Papirus-Dark |
| **Cursor** | catppuccin-mocha-flamingo-cursors |
| **Terminal** | Kitty |
| **Shell & Prompt** | Bash + Starship |
| **Fetch Tool** | Fastfetch |
| **System Monitor** | btop |
| **Audio Visualizer** | Cava |
| **Lyrics Display** | Sptlrx |
| **Dock** | Plank |

---

## 📦 Instalasi

### 1. Clone Repositori
```bash
git clone https://github.com/<username>/mint-catppuccin.git
cd mint-catppuccin
```

### 2. Jalankan Installer
```bash
./install.sh
```

Menu instalasi menyediakan:
1. **Full Install:** Cek dependensi paket, backup file lama ke `~/.dotfiles_backup/`, pasang konfigurasi `.config` dan `.local`, tema GTK, serta restore pengaturan dconf.
2. **Konfigurasi Saja:** Hanya menyalin file konfigurasi tanpa mengubah paket sistem.
3. **Dconf Saja:** Hanya restore pengaturan panel Cinnamon, shortcut, dan tema.

### 3. Terapkan Perubahan
Setelah selesai, muat ulang Cinnamon:
- Tekan `Alt + F2`, ketik `r`, lalu tekan `Enter`.
- Atau logout dan login kembali.

---

## 📂 Struktur Repositori

```text
mint-catppuccin/
├── .config/
│   ├── autostart/             # Autostart modul desktop & Plank
│   ├── bento-wallpaper/       # Pemetaan wallpaper per-workspace
│   ├── btop/                  # Konfigurasi btop & tema Catppuccin
│   ├── cava/                  # Konfigurasi audio visualizer cava
│   ├── fastfetch/             # Konfigurasi fastfetch
│   ├── kitty/                 # Konfigurasi Kitty terminal & tema
│   ├── plank/                 # Pengaturan dock Plank & launchers
│   ├── sptlrx/                # Konfigurasi lirik musik sptlrx
│   └── starship.toml          # Prompt Starship
├── .local/
│   ├── bin/                   # Skrip utilitas & launcher modul UI
│   └── share/
│       ├── clip/control/lock/osd/power/toast/wallpaper  # Modul antarmuka desktop
│       └── cinnamon/applets/  # Custom Cinnamon applets (@df)
├── dconf/
│   ├── cinnamon.dconf         # Pengaturan panel, applet, dan tema Cinnamon
│   ├── gnome-interface.dconf  # Pengaturan tema GTK, font, dan kursor
│   └── plank.dconf            # Pengaturan dock Plank
├── themes/
│   └── Catppuccin-Flamingo-Dark/  # Tema GTK lengkap
├── assets/
│   ├── wallpapers/            # Wallpaper default & per-workspace
│   └── icons/                 # Aset gambar / ikon pendukung
├── install.sh                 # Skrip instalasi interaktif
├── .gitignore                 # Filter cache, riwayat db, dan file temporary
├── LICENSE                    # Lisensi MIT
└── README.md                  # Dokumentasi repositori
```

---

## ⌨️ Shortcut & Perintah

| Modul / Aksi | Perintah Eksekusi |
| :--- | :--- |
| **Control Center** | `caelestia-control` |
| **Clipboard History** | `caelestia-clip` |
| **Lock Screen** | `caelestia-lock` |
| **Power Menu** | `caelestia-power` |
| **Wallpaper Switcher**| `caelestia-wallpaper` |
| **Auto Tiling Toggle**| `cinnamon-autotile.py` |
| **Terminal Kitty** | `kitty-fast` |

*Catatan:* Anda dapat mengatur tombol pintasan keyboard (*Keyboard Shortcuts*) melalui **System Settings > Keyboard > Shortcuts > Custom Shortcuts**.

---

## 🔒 Privasi & Keamanan
- Riwayat salinan clipboard pribadi (`clipboard.db`) otomatis diabaikan via `.gitignore`.
- Cache Python (`__pycache__`) dan file temporary tidak disertakan dalam repositori.

---

## 📄 Lisensi
Proyek ini dilisensikan di bawah [MIT License](LICENSE).
