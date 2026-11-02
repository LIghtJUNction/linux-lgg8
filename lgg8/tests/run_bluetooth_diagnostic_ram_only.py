#!/usr/bin/env python3
"""Bounded UART diagnostics; does not turn incomplete Bluetooth evidence into PASS."""
import run_bluetooth_ram_only as bt

base = bt.base
CANDIDATE = base.ROOT / 'out/lgg8-connectivity-20261102/bt-diag-boot'
IMAGE_SHA = '6fc3d9621fd617f6b209f3ce6420f6a52851df50ff401bf2dd16915db65f0035'
MANIFEST_SHA = '5e48bae930a02fbf2126a8b50d4ac7a457fa1c14ea58437973778f0dde30b045'
DIAGNOSTIC = r'''set -eu
if ! /bin/busybox grep -qs ' /sys/kernel/debug debugfs ' /proc/mounts; then
    /bin/busybox mount -t debugfs none /sys/kernel/debug
fi
printf 'UART_TTY\n'
for file in /proc/tty/driver/*; do
    test -f "$file" || continue
    printf '%s\n' "$file"
    /bin/busybox cat "$file"
done
printf 'UART_PINMUX\n'
for file in /sys/kernel/debug/pinctrl/*/pinmux-pins; do
    test -f "$file" || continue
    /bin/busybox grep -E '^pin (43|44|45|46) ' "$file" || :
done
printf 'UART_CLOCKS\n'
test ! -f /sys/kernel/debug/clk/clk_summary ||
    /bin/busybox grep -E 'qupv3_wrap1_(s5_clk|s_ahb_clk)' /sys/kernel/debug/clk/clk_summary || :
'''


def tasks(probe_path='/run/wdt-' + 'A' * 24):
    original = bt.tasks(probe_path)
    return original[:5] + [('uart_diagnostic', ['/bin/busybox', 'sh', '-c', DIAGNOSTIC], None)] + original[5:]


def capture_script(legacy, prefix, argv):
    result = bt.capture_script(legacy, prefix, argv)
    if argv == ['/bin/busybox', 'sh', '-c', DIAGNOSTIC]:
        needle = b'/bin/busybox timeout -s KILL 1 '
        if result.count(needle) != 1:
            raise ValueError('pinned timeout envelope changed')
        result = result.replace(needle, b'/bin/busybox timeout -s KILL 4 ')
    return result


def configure():
    bt.configure()
    base.CANDIDATE, base.IMAGE_SHA, base.MANIFEST_SHA = CANDIDATE, IMAGE_SHA, MANIFEST_SHA
    base.RECORD_PREFIX = 'bluetooth-uart-diag'
    base.REQUESTED_SCOPE = 'own UART initial RX/TX diagnostics and Bluetooth controller acceptance'
    base.tasks, base.capture_script = tasks, capture_script


if __name__ == '__main__':
    configure()
    base.main()
