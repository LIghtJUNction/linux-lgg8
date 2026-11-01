import unittest
from pm_devices_capture import command, parse


class DevicesTest(unittest.TestCase):
    def setUp(self):
        self.cmd, self.prefix = command('A' * 24)
    def line(self, name):
        return (self.prefix + '_' + name + '\r\n').encode()
    def test_success_is_only_device_callback_test(self):
        result = parse(self.cmd + self.line('SELECTED') + self.line('RETURN_0') + self.line('RESET_0'), self.prefix)
        self.assertEqual(result['status'], 'PASS')
        self.assertFalse(result['real_sleep_verified'])
        self.assertFalse(result['touch_after_resume_verified'])
    def test_echo_or_fail_never_pass(self):
        self.assertIsNone(parse(self.cmd, self.prefix))
        for data in (self.line('SELECT_FAILED') + self.line('RESET_0'),
                     self.line('SELECTED') + self.line('RETURN_1') + self.line('RESET_0'),
                     self.line('SELECTED') + self.line('RETURN_0') + self.line('RESET_1'),
                     self.line('SELECTED') + self.line('RETURN_0') + self.line('RETURN_0') + self.line('RESET_0'),
                     self.line('SELECTED') + self.line('SELECTED') + self.line('RETURN_0') + self.line('RESET_0'),
                     self.line('RETURN_0') + self.line('SELECTED') + self.line('RESET_0'),
                     self.line('SELECTED') + self.line('RESET_0') + self.line('RETURN_0')):
            self.assertEqual(parse(data, self.prefix)['status'], 'FAILED')
    def test_path_and_nonce_are_fixed(self):
        self.assertIn(b'/sys/power/pm_test', self.cmd)
        self.assertIn(b'/sys/power/state', self.cmd)
        with self.assertRaises(ValueError):
            command('AA;reboot')


if __name__ == '__main__':
    unittest.main()
