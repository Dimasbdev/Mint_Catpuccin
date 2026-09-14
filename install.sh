#!/usr/bin/env bash

# ==============================================================================
#  Mint-Catppuccin Dotfiles Installer
#  Linux Mint Cinnamon Ricing Setup (Catppuccin Flamingo + Bento UI Modules)
# ==============================================================================

set -e

DOTFILES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="$HOME/.dotfiles_backup/$(date +%Y%m%d_%H%M%S)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

print_banner() {
    clear 2>/dev/null || true
    echo -e "${MAGENTA}${BOLD}"
    cat << "BANNER"
  __  __ _       _          ____      _                              _        
 |  \/  (_)_ __ | |_       / ___|__ _| |_ _ __  _   _  ___ ___ _ __ (_)_ __   
 | |\/| | | '_ \| __|____ | |   / _` | __| '_ \| | | |/ __/ __| '_ \| | '_ \  
 | |  | | | | | | ||_____|| |__| (_| | |_| |_) | |_| | (_| (__| | | | | | | | 
 |_|  |_|_|_| |_|\__|      \____\__,_|\__| .__/ \__,_|\___\___|_| |_|_|_| |_| 
                                         |_|                                   
BANNER
    echo -e "${CYAN}    Linux Mint Cinnamon Rice • Catppuccin Flamingo • Bento UI Modules${NC}"
    echo -e "${BLUE}======================================================================${NC}\n"
}

info() { echo -e "${CYAN}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${RED}[WARN]${NC} $1"; }

backup_item() {
    local target="$1"
    if [ -e "$target" ] || [ -L "$target" ]; then
        mkdir -p "$BACKUP_DIR"
        local rel_path="${target#$HOME/}"
        local dest_dir="$BACKUP_DIR/$(dirname "$rel_path")"
        mkdir -p "$dest_dir"
        cp -a "$target" "$dest_dir/"
    fi
}

install_packages() {
    info "Memeriksa paket dependensi sistem..."
    local PKGS=(
        plank
        kitty
        fastfetch
        btop
        cava
        tty-clock
        python3-gi
        python3-gi-cairo
        python3-pil
        python3-xlib
        python3-dbus
        gir1.2-gtk-3.0
        gir1.2-webkit2-4.1
        gir1.2-wnck-3.0
        wmctrl
        x11-utils
        pulseaudio-utils
        dconf-cli
        xclip
        playerctl
        curl
        git
        rsync
        gcc
        fonts-firacode
        fonts-inter
        papirus-icon-theme
    )

    local MISSING=()
    for pkg in "${PKGS[@]}"; do
        if ! dpkg -l | grep -q -w "ii  $pkg"; then
            MISSING+=("$pkg")
        fi
    done

    if [ ${#MISSING[@]} -gt 0 ]; then
        info "Paket berikut perlu di-install: ${MISSING[*]}"
        read -rp "Install paket dependensi sekarang dengan sudo apt? (y/N): " ans
        if [[ "$ans" =~ ^[Yy]$ ]]; then
            sudo apt update
            sudo apt install -y "${MISSING[@]}"
            success "Paket dependensi berhasil di-install."
        else
            warn "Melewati instalasi dependensi. Beberapa fitur ricing mungkin memerlukan paket tersebut."
        fi
    else
        success "Semua paket dependensi utama sudah terpasang."
    fi
}

deploy_configs() {
    info "Memasang konfigurasi ke $HOME..."
    mkdir -p "$HOME/.config" "$HOME/.local/bin" "$HOME/.local/share" "$HOME/.themes"

    # Backup & deploy .config
    for item in "$DOTFILES_DIR/.config"/*; do
        local name="$(basename "$item")"
        backup_item "$HOME/.config/$name"
        if [ -d "$item" ]; then
            mkdir -p "$HOME/.config/$name"
            rsync -a --delete "$item/" "$HOME/.config/$name/"
        else
            cp -a "$item" "$HOME/.config/$name"
        fi
        success "Terkonfigurasi: ~/.config/$name"
    done

    # Fix absolute paths to current user's $HOME in autostart, systemd, and plank launchers
    for dir in "$HOME/.config/autostart" "$HOME/.config/systemd/user" "$HOME/.config/plank/dock1/launchers"; do
        if [ -d "$dir" ]; then
            for f in "$dir"/*; do
                if [ -f "$f" ]; then
                    sed -i "s|__HOME__|$HOME|g; s|/home/df/|$HOME/|g" "$f"
                fi
            done
        fi
    done

    # Backup & deploy .config/starship.toml
    if [ -f "$DOTFILES_DIR/.config/starship.toml" ]; then
        backup_item "$HOME/.config/starship.toml"
        cp "$DOTFILES_DIR/.config/starship.toml" "$HOME/.config/starship.toml"
        success "Terkonfigurasi: ~/.config/starship.toml"
    fi

    # Backup & deploy .local/bin
    if [ -d "$DOTFILES_DIR/.local/bin" ]; then
        for script in "$DOTFILES_DIR/.local/bin"/*; do
            local sname="$(basename "$script")"
            backup_item "$HOME/.local/bin/$sname"
            cp -a "$script" "$HOME/.local/bin/$sname"
            chmod +x "$HOME/.local/bin/$sname"
        done
        # Compile bento-sock-send C helper if gcc is available
        if command -v gcc >/dev/null 2>&1 && [ -f "$DOTFILES_DIR/.local/bin/bento-sock-send.c" ]; then
            gcc -O3 "$DOTFILES_DIR/.local/bin/bento-sock-send.c" -o "$HOME/.local/bin/bento-sock-send" 2>/dev/null || true
            chmod +x "$HOME/.local/bin/bento-sock-send" 2>/dev/null || true
        fi
        # Compile and install lavat (terminal lava lamp) if missing
        if ! command -v lavat >/dev/null 2>&1 && command -v gcc >/dev/null 2>&1; then
            (
                TMP_DIR="$(mktemp -d)"
                git clone --depth 1 https://github.com/AngelJumbo/lavat "$TMP_DIR" >/dev/null 2>&1 && \
                make -C "$TMP_DIR" >/dev/null 2>&1 && \
                cp "$TMP_DIR/lavat" "$HOME/.local/bin/lavat" && chmod +x "$HOME/.local/bin/lavat"
                rm -rf "$TMP_DIR"
            ) || true
        fi
        success "Skrip terpasang di ~/.local/bin/ (Module launchers, utilities)"
    fi

    # Backup & deploy .local/share/bento-*
    for app in "$DOTFILES_DIR/.local/share"/bento-*; do
        if [ -d "$app" ]; then
            local aname="$(basename "$app")"
            backup_item "$HOME/.local/share/$aname"
            mkdir -p "$HOME/.local/share/$aname"
            rsync -a --exclude="*.db" --exclude="*.sqlite*" --exclude="__pycache__" "$app/" "$HOME/.local/share/$aname/"
            success "Desktop modules terpasang: ~/.local/share/$aname"
        fi
    done

    # Deploy Cinnamon applets
    if [ -d "$DOTFILES_DIR/.local/share/cinnamon/applets" ]; then
        mkdir -p "$HOME/.local/share/cinnamon/applets"
        for applet in "$DOTFILES_DIR/.local/share/cinnamon/applets"/*; do
            local apname="$(basename "$applet")"
            backup_item "$HOME/.local/share/cinnamon/applets/$apname"
            rsync -a "$applet/" "$HOME/.local/share/cinnamon/applets/$apname/"
            success "Cinnamon Applet terpasang: $apname"
        done
    fi

    # Deploy GTK theme
    if [ -d "$DOTFILES_DIR/themes/Catppuccin-Flamingo-Dark" ]; then
        mkdir -p "$HOME/.themes"
        backup_item "$HOME/.themes/Catppuccin-Flamingo-Dark"
        rsync -a "$DOTFILES_DIR/themes/Catppuccin-Flamingo-Dark/" "$HOME/.themes/Catppuccin-Flamingo-Dark/"
        success "GTK Theme terpasang: ~/.themes/Catppuccin-Flamingo-Dark"
    fi

    # Deploy icons & cursor theme
    if [ -d "$DOTFILES_DIR/.icons" ]; then
        mkdir -p "$HOME/.icons"
        cp -a "$DOTFILES_DIR/.icons"/* "$HOME/.icons/" 2>/dev/null || true
        success "Cursor theme terpasang: ~/.icons/"
    fi

    # Deploy Wallpapers
    mkdir -p "$HOME/.cache/bento-wallpaper/optimized" "$HOME/Pictures/Wallpapers"
    if [ -d "$DOTFILES_DIR/assets/wallpapers" ]; then
        cp -a "$DOTFILES_DIR/assets/wallpapers"/* "$HOME/Pictures/Wallpapers/" 2>/dev/null || true
        cp -a "$DOTFILES_DIR/assets/wallpapers"/default.jpg "$HOME/.cache/bento-wallpaper/optimized/135449b36a8398ec09a9d3337f84607a.jpg" 2>/dev/null || true
        cp -a "$DOTFILES_DIR/assets/wallpapers"/ws_* "$HOME/.cache/bento-wallpaper/optimized/" 2>/dev/null || true
        success "Wallpaper terpasang di ~/Pictures/Wallpapers/ & cache Bento"
    fi

    # Enable systemd user services if available
    if command -v systemctl >/dev/null 2>&1; then
        systemctl --user daemon-reload 2>/dev/null || true
        for svc in "$HOME/.config/systemd/user"/*.service; do
            if [ -f "$svc" ]; then
                local svc_name="$(basename "$svc")"
                systemctl --user enable "$svc_name" 2>/dev/null || true
            fi
        done
        systemctl --user start kitty-daemon.service 2>/dev/null || true
        success "Systemd user services terpasang & aktif (termasuk kitty-daemon)"
    fi

    if [ -d "$BACKUP_DIR" ]; then
        info "Backup file sebelumnya tersimpan aman di: $BACKUP_DIR"
    fi
}

apply_dconf() {
    info "Menerapkan pengaturan Cinnamon & Interface via dconf..."
    if command -v dconf >/dev/null 2>&1; then
        if [ -f "$DOTFILES_DIR/dconf/cinnamon.dconf" ]; then
            sed -e "s|__HOME__|$HOME|g" -e "s|/home/df/|$HOME/|g" "$DOTFILES_DIR/dconf/cinnamon.dconf" | dconf load /org/cinnamon/
            success "Pengaturan Cinnamon diterapkan (panel, applets, themes)."
        fi
        if [ -f "$DOTFILES_DIR/dconf/gnome-interface.dconf" ]; then
            sed -e "s|__HOME__|$HOME|g" -e "s|/home/df/|$HOME/|g" "$DOTFILES_DIR/dconf/gnome-interface.dconf" | dconf load /org/gnome/desktop/interface/
            success "Pengaturan GNOME/GTK Interface diterapkan."
        fi
        if [ -f "$DOTFILES_DIR/dconf/plank.dconf" ]; then
            sed -e "s|__HOME__|$HOME|g" -e "s|/home/df/|$HOME/|g" "$DOTFILES_DIR/dconf/plank.dconf" | dconf load /net/launchpad/plank/
            success "Pengaturan Plank dock diterapkan."
        fi
    else
        warn "dconf tidak ditemukan! Silakan install dconf-cli terlebih dahulu."
    fi
}

main() {
    print_banner
    echo -e "Pilih opsi instalasi:"
    echo "  1) Full Install (Rekomendasi: Dependensi + Konfigurasi + dconf Cinnamon)"
    echo "  2) Konfigurasi Saja (Deploy file .config, .local/share, .local/bin)"
    echo "  3) Dconf Saja (Restore tema, panel, dan shortcut Cinnamon)"
    echo "  4) Install Paket Dependensi Saja"
    echo "  5) Keluar"
    echo ""
    read -rp "Pilihan Anda [1-5]: " choice

    case "$choice" in
        1)
            install_packages
            deploy_configs
            apply_dconf
            echo ""
            success "Instalasi selesai! Disarankan untuk me-restart Cinnamon (Alt+F2 -> ketik 'r' -> Enter) atau relog."
            ;;
        2)
            deploy_configs
            success "Konfigurasi berhasil dipasang."
            ;;
        3)
            apply_dconf
            success "Pengaturan dconf berhasil dipulihkan."
            ;;
        4)
            install_packages
            ;;
        5)
            echo "Dibatalkan."
            exit 0
            ;;
        *)
            warn "Pilihan tidak valid!"
            exit 1
            ;;
    esac
}

main "$@"
