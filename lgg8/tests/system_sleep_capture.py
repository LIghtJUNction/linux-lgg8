"""Offline construction and parsing for a future manual-wake freeze test.

No function here talks to a phone. Markers and logs are unauthenticated;
returning from the sysfs write, even alongside suspend logs, is not proof of
physical platform sleep. A runner must independently manage user coordination,
USB identity, deadlines, recovery, and post-wake input capture.
"""
import re
import shlex


_NONCE = re.compile(r'[A-F0-9]{24}')


def plan(nonce):
    if not isinstance(nonce, str) or not _NONCE.fullmatch(nonce):
        raise ValueError('invalid nonce')
    path = '/run/system-freeze-' + nonce
    marker = 'SYSFREEZE_' + nonce
    body = (
        "if /bin/busybox grep -q '\\[none\\]' /sys/power/pm_test && "
        "/bin/busybox grep -qw freeze /sys/power/state; then "
        f"printf '{marker}_READY\\n'; "
        "printf 'freeze\\n' > /sys/power/state; r=$?; "
        f"printf '{marker}_RETURN_%s\\n' \"$r\"; "
        "else " + f"printf '{marker}_PRECHECK_FAILED\\n'; fi; "
        f"printf '{marker}_LOG_BEGIN\\n'; "
        "/bin/busybox dmesg | /bin/busybox grep -E "
        "'PM: suspend|2-0028|sw42000' | /bin/busybox tail -n 100; "
        f"printf '{marker}_LOG_END\\n'; "
        f"printf '{marker}_DONE\\n'"
    )
    launch = (f"umask 077; test ! -e {path} && "
              f"/bin/busybox setsid /bin/busybox sh -c {shlex.quote(body)} "
              f"</dev/null >{path} 2>&1 &\n")
    return {'path': path, 'prefix': marker, 'launch': launch.encode('ascii')}


def parse(data, nonce):
    """Parse complete whole-line markers; never elevate them to sleep proof."""
    if not isinstance(nonce, str) or not _NONCE.fullmatch(nonce):
        raise ValueError('invalid nonce')
    prefix = ('SYSFREEZE_' + nonce).encode('ascii')
    lines = data.replace(b'\r', b'').split(b'\n')[:-1]
    ready, done = prefix + b'_READY', prefix + b'_DONE'
    failed = prefix + b'_PRECHECK_FAILED'
    returns = [line for line in lines if re.fullmatch(re.escape(prefix) + rb'_RETURN_[0-9]+', line)]
    begin, end = prefix + b'_LOG_BEGIN', prefix + b'_LOG_END'
    if done not in lines:
        return None
    successful = (lines.count(done) == lines.count(ready) == 1 and failed not in lines and
                  returns == [prefix + b'_RETURN_0'] and lines.count(begin) == lines.count(end) == 1 and
                  lines.index(ready) < lines.index(returns[0]) < lines.index(begin) <
                  lines.index(end) < lines.index(done) and
                  lines.index(end) - lines.index(begin) <= 101)
    logs = ([line[:512].decode('utf-8', 'replace') for line in
             lines[lines.index(begin) + 1:lines.index(end)]] if successful else [])
    return {'status': 'PASS' if successful else 'FAILED', 'logs': logs,
            'write_returned_zero': successful, 'real_sleep_verified': False,
            'touch_after_resume_verified': False, 'capture_authenticated': False}
