#!/usr/bin/env bash
# DeskBeam Linux launcher (UBUNTU_PORT_PLAN.md P0/P4)
#
# One-time system deps:
#   sudo apt install ffmpeg python3-xlib x11-xserver-utils python3-venv
# Run inside an Xorg session (Wayland is not supported — see plan §5):
#   ./start.sh            # foreground
#   systemctl --user ...  # or install deskbeam.service
set -e
cd "$(dirname "$0")"

[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate

python -c 'import websockets, av, numpy, Xlib' 2>/dev/null \
  || pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements-linux.txt

export DISPLAY="${DISPLAY:-:0}"
# GDM-managed sessions keep the X authority file here; required when
# launching over SSH or from systemd rather than inside the session.
if [ -z "$XAUTHORITY" ] && [ -f "/run/user/$(id -u)/gdm/Xauthority" ]; then
  export XAUTHORITY="/run/user/$(id -u)/gdm/Xauthority"
fi
exec python server.py "$@"
