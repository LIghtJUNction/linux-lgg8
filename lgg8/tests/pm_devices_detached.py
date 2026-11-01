"""Build a detached, /run-only device-PM result writer; no I/O here.

The result survives gadget disconnect only if Linux and its tmpfs survive.
The caller must verify /run is tmpfs and revalidate the physical USB binding.
"""
import re
import shlex


def plan(nonce):
    if re.fullmatch(r'[A-F0-9]{24}', nonce) is None:
        raise ValueError('invalid nonce')
    path = '/run/pmdev-' + nonce
    marker = 'PMDEV_' + nonce
    # No caller-controlled shell fragments. A separate session and redirected
    # stdio let the test continue if the ACM gadget disconnects. Marker lines
    # report sysfs results; they do not prove actual callback execution.
    body = ("if printf 'devices\\n' > /sys/power/pm_test && "
            "/bin/busybox grep -q '\\[devices\\]' /sys/power/pm_test; then "
            f"printf '{marker}_SELECTED\\n'; "
            "printf 'freeze\\n' > /sys/power/state; r=$?; "
            f"printf '{marker}_RETURN_%s\\n' \"$r\"; "
            f"else printf '{marker}_SELECT_FAILED\\n'; fi; "
            "printf 'none\\n' > /sys/power/pm_test; r=$?; "
            f"printf '{marker}_RESET_%s\\n' \"$r\"")
    launch = (f"umask 077; test ! -e {path} && "
              f"/bin/busybox setsid /bin/busybox sh -c {shlex.quote(body)} "
              f"</dev/null >{path} 2>&1 &\n")
    return {'path': path, 'prefix': marker, 'launch': launch.encode('ascii')}


def valid_snapshot(before, after):
    return (before.get('status') == after.get('status') == 'present' and
            all(before.get(k) == after.get(k) and before.get(k) is not None
                for k in ('port', 'vid', 'pid', 'serial')) and before.get('port') == '1-2')
