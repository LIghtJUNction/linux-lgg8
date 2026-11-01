import subprocess
import unittest
from pm_devices_detached import plan, valid_snapshot


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

    def test_port_binding_must_match_linux_fingerprint(self):
        before = {'status':'present', 'port':'1-2', 'vid':'1004', 'pid':'4ee7', 'serial':'S', 'devnum':'43'}
        self.assertTrue(valid_snapshot(before, {**before, 'devnum':'44'}))
        for changed in ({'port':'1-3'}, {'pid':'631f'}, {'serial':'other'}, {'status':'absent'}, {'vid':None}):
            self.assertFalse(valid_snapshot(before, {**before, **changed}))


if __name__ == '__main__':
    unittest.main()
