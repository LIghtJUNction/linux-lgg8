import subprocess
import unittest
from pm_devices_detached import plan, read_record, valid_snapshot


class DetachedTest(unittest.TestCase):
    def test_plan_is_shell_valid_and_fixed(self):
        p = plan('A' * 24)
        self.assertEqual(p['path'], '/run/pmdev-' + 'A' * 24)
        self.assertIn(b'busybox setsid', p['launch'])
        self.assertIn(b"/sys/power/pm_test", p['launch'])
        self.assertIn(b"/sys/power/state", p['launch'])
        subprocess.run(['/bin/busybox', 'sh', '-n'], input=p['launch'], check=True)
        with self.assertRaises(ValueError):
            plan('A' * 23 + ';')

    def test_record_read_requires_complete_exact_frames(self):
        p = plan('A' * 24)
        class Channel:
            buffer = b'old data\n'
            def __init__(self, body): self.body = body
            def send(self, data, deadline): self.command = data
            def until(self, predicate, deadline):
                token = b'PMREAD_' + b'B' * 24
                return predicate(self.buffer + self.command + self.body + b'\n' + token + b'\n')
        pfx = p['prefix'].encode()
        body = pfx + b'_SELECTED\n' + pfx + b'_RETURN_0\n' + pfx + b'_RESET_0\n'
        found = read_record(Channel(body), lambda: True, p, 1000000000, 'B' * 24)
        self.assertEqual(found['status'], 'PASS')
        self.assertIsNone(read_record(Channel(pfx + b'_SELECTED\n'), lambda: True, p, 1000000000, 'B' * 24))
        with self.assertRaises(RuntimeError):
            read_record(Channel(body), lambda: False, p, 1000000000, 'B' * 24)
        with self.assertRaises(ValueError):
            read_record(Channel(body), lambda: True, {**p, 'path':'/run/x;reboot'}, 1000000000, 'B' * 24)

    def test_port_binding_must_match_linux_fingerprint(self):
        before = {'status':'present', 'port':'1-2', 'vid':'1004', 'pid':'4ee7', 'serial':'S', 'devnum':'43'}
        self.assertTrue(valid_snapshot(before, {**before, 'devnum':'44'}))
        for changed in ({'port':'1-3'}, {'pid':'631f'}, {'serial':'other'}, {'status':'absent'}, {'vid':None}):
            self.assertFalse(valid_snapshot(before, {**before, **changed}))


if __name__ == '__main__':
    unittest.main()
