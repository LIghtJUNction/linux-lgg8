#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
set -eu
backend=${1:-drm}
case "$backend" in drm|headless) ;; *) echo "Invalid explicit backend: $backend"; exit 2;; esac
set --
stage() { printf '%s\n' "$1" > /run/desktop-stage; }
stage 1
export XDG_RUNTIME_DIR=/run/user/0
export WAYLAND_DISPLAY=wayland-0
export LIBSEAT_BACKEND=seatd
export SEATD_SOCK=/run/seatd.sock
export LC_ALL=C LANG=C HOME=/root
mkdir -p "$XDG_RUNTIME_DIR" /run/udev /run/dbus /tmp
chmod 0700 "$XDG_RUNTIME_DIR"
chmod 1777 /tmp
echo "LGG8_DESKTOP_START backend=$backend"
cat /etc/alpine-release
uname -m

cat > /run/weston.ini <<'INI'
[core]
shell=desktop-shell.so
renderer=pixman
idle-time=0
require-input=false
require-outputs=any
xwayland=false
color-management=false
[shell]
background-color=0xff183040
panel-position=top
locking=false
[keyboard]
keymap_layout=us
[terminal]
font=Liberation Mono
font-size=16
[input-method]
path=
INI
stage 2

# Phone DRM never falls back to headless; only the explicit test profile does.
if [ "$backend" = drm ]; then
    stage 3
    if [ -x /sbin/udevd ]; then /sbin/udevd --daemon > /run/udev.log 2>&1; fi
    udevadm trigger --action=add --subsystem-match=drm >> /run/udev.log 2>&1 || true
    udevadm trigger --action=add --subsystem-match=input >> /run/udev.log 2>&1 || true
    udevadm settle --timeout=3 >> /run/udev.log 2>&1 || true
    # Embedded targets may have no virtual-terminal driver.
    export SEATD_VTBOUND=0
    # seatd 0.9.3 uses its compiled /run/seatd.sock; it has no -s option.
    seatd > /run/seatd.log 2>&1 &
    seatd_pid=$!
    stage 4
    n=0
    until [ -S "$SEATD_SOCK" ]; do
        kill -0 "$seatd_pid" 2>/dev/null || { stage 90; echo LGG8_SEATD_EXITED; exit 5; }
        n=$((n + 1)); [ "$n" -lt 4 ] || { stage 91; echo LGG8_SEATD_SOCKET_TIMEOUT; exit 6; }
        sleep 1
    done
    stage 5
    first_status=
    dsi_status=
    first_card=
    dsi_card=
    connected_statuses=
    for f in /sys/class/drm/card*-*/status; do
        [ -f "$f" ] || continue
        [ "$(cat "$f")" = connected ] || continue
        connector=${f%/status}; connector=${connector##*/}; connector=${connector#card*-}
        echo "LGG8_CONNECTED_OUTPUT $connector"
        card=${f#/sys/class/drm/}; card=${card%%-*}
        connected_statuses="$connected_statuses $f"
        if [ -z "$first_status" ]; then
            first_status=$f
            first_card=$card
        fi
        case "$connector" in
            DSI-*)
                if [ -z "$dsi_status" ]; then
                    dsi_status=$f
                    dsi_card=$card
                fi
                ;;
        esac
    done
    selected_status=$dsi_status
    selected_card=$dsi_card
    [ -n "$selected_status" ] || {
        selected_status=$first_status
        selected_card=$first_card
    }
    if [ -n "$selected_status" ]; then
        set -- "--drm-device=$selected_card"
        for f in $connected_statuses; do
            connector=${f%/status}; connector=${connector##*/}; connector=${connector#card*-}
            mode=off
            [ "$f" = "$selected_status" ] && mode=preferred
            printf '\n[output]\nname=%s\nmode=%s\n' "$connector" "$mode" >> /run/weston.ini
            [ "$mode" = preferred ] && echo "LGG8_SELECTED_OUTPUT $connector"
        done
    fi
    selected=${selected_status%/status}; selected=${selected##*/}; selected=${selected#card*-}
    [ -n "$selected" ] || echo "LGG8_NO_CONNECTED_DRM_OUTPUT"
fi

weston --backend="$backend" --renderer=pixman --shell=desktop-shell.so "$@" \
    --socket="$WAYLAND_DISPLAY" --config=/run/weston.ini --log=/run/weston.log \
    > /run/weston.stdout 2>&1 &
weston_pid=$!
printf '%s\n' "$weston_pid" > /run/desktop-weston.pid
stage 6
trap 'kill "$weston_pid" 2>/dev/null || true; exit 0' TERM INT
n=0
until [ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ]; do
    kill -0 "$weston_pid" 2>/dev/null || { stage 92; cat /run/weston.stdout; exit 3; }
    n=$((n + 1)); [ "$n" -lt 12 ] || { stage 93; echo LGG8_SOCKET_TIMEOUT; exit 4; }
    sleep 1
done
stage 7
echo "LGG8_WAYLAND_SOCKET_READY backend=$backend compositor_pid=$weston_pid"
WAYLAND_DEBUG=1 weston-terminal --shell=/usr/local/bin/lgg8-terminal \
    --font='Liberation Mono' --font-size=16 > /run/client.log 2>&1 &
terminal_pid=$!
stage 8
echo "LGG8_TERMINAL_STARTED pid=$terminal_pid"
while kill -0 "$weston_pid" 2>/dev/null; do
    sleep 2
    kill -0 "$terminal_pid" 2>/dev/null || { stage 94; echo LGG8_TERMINAL_EXITED; break; }
done
wait "$weston_pid"
