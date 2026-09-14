#!/usr/bin/env bash
# ==============================================================================
#  Bento Catppuccin Pipes Screensaver (pipes.sh)
#  Aesthetic preset with smooth 60fps, pastel palette, and multi-pipe flow
# ==============================================================================

CMD=""
if command -v pipes >/dev/null 2>&1; then
    CMD="pipes"
elif [ -x /usr/games/pipes ]; then
    CMD="/usr/games/pipes"
fi

if [ -z "$CMD" ]; then
    echo "pipes tidak ditemukan. Install dengan: sudo apt install pipes-sh"
    exit 1
fi

# Presets:
# -f 60    : Smooth 60 FPS animation
# -p 3     : 3 concurrent animated pipes
# -t 0     : Classic heavy pipe style
# -c 4 -c 5 -c 6 -c 3 : Catppuccin pastel palette (Blue, Flamingo, Teal, Peach)
# -R       : Random start positions & directions
# -K       : Keep color and pipe style when hitting screen edges
# -r 3000  : Reset screen after 3000 steps to maintain clean canvas
exec "$CMD" \
    -f 60 \
    -p 3 \
    -t 0 \
    -c 4 \
    -c 5 \
    -c 6 \
    -c 3 \
    -R \
    -K \
    -r 3000 \
    "$@"
