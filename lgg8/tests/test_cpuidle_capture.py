"""Validate paired idle counters without a phone."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_cpuidle_ram_only as idle


def sample():
    lines = []
    for index in range(2):
        lines += [f'SAMPLE|{index}', 'DRIVER|psci_idle', f'UPTIME|{10 + index}.00']
        for cpu in range(8):
            lines += [f'STATE|{cpu}|state0|WFI|{100 + index}|{10000 + index * 100}|0',
                      f'STATE|{cpu}|state1|CPU_SLEEP|{20 + index}|{20000 + index * 8000}|0']
    return ('\n'.join(lines) + '\nEND\n').encode()


class IdleTest(unittest.TestCase):
    def test_all_cores_have_advancing_deeper_idle_counters(self):
        report = idle.parse_idle(sample())
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(len(report['cores']), 8)
        self.assertEqual(report['interval_seconds'], 1.0)
        self.assertFalse(report['measured_power_savings'])
        stalled = sample().replace(b'CPU_SLEEP|21|28000', b'CPU_SLEEP|20|20000')
        self.assertEqual(idle.parse_idle(stalled)['status'], 'FAILED')

    def test_invalid_or_missing_evidence_cannot_pass(self):
        invalid = [sample().replace(b'psci_idle', b'none'),
                   sample().replace(b'CPU_SLEEP|21|28000', b'CPU_SLEEP|19|19000'),
                   sample().replace(b'CPU_SLEEP|21|28000|0', b'CPU_SLEEP|21|28000|1'),
                   sample().replace(b'STATE|7|state1|CPU_SLEEP|21|28000|0\n', b''),
                   sample().replace(b'UPTIME|11.00', b'UPTIME|10.01'),
                   sample().replace(b'SAMPLE|1', b'SAMPLE|0'),
                   sample().replace(b'END\n', b''), sample() + b'extra\n']
        for payload in invalid:
            with self.subTest(payload=payload[-100:]), self.assertRaises(ValueError):
                idle.parse_idle(payload)

    @unittest.skipUnless(idle.base.touch.LEGACY.is_file(), 'requires retained C234 helper')
    def test_real_frame_timeout_and_output(self):
        legacy = idle.base.touch.pinned_legacy()
        with patch.dict(idle.base.__dict__):
            idle.configure()
            prefix = 'C234_' + 'D' * 24 + '_idle'
            command = idle.capture_script(legacy, prefix, idle.IDLE_ARGV)
            self.assertIn(b'timeout -s KILL 3 ', command)
            subprocess.run(['/bin/busybox', 'sh', '-n'], input=command, check=True)
            with tempfile.TemporaryDirectory(prefix='cpuidle-frame-') as tmp:
                data = Path(tmp) / 'sample'
                data.write_bytes(sample())
                quoted = idle.base.shlex.join(idle.IDLE_ARGV).encode()
                command = command.replace(quoted, ('/bin/busybox cat ' + str(data)).encode())
                command = command.replace(('/run/' + prefix).encode(),
                                          str(Path(tmp) / 'capture').encode())
                output = subprocess.check_output(['/bin/busybox', 'sh', '-c', command], timeout=5)
                frame = legacy.parse_frame(output, prefix)
                self.assertEqual(frame['exit_code'], 0)
                self.assertTrue(frame['payload_integrity_verified'])
                self.assertEqual(idle.parse_idle(frame['stdout'])['status'], 'PASS')
            names = [key for key, _, _ in idle.tasks()]
            self.assertLess(names.index('idle_pair'), names.index('cpu_execution'))


if __name__ == '__main__':
    unittest.main()
