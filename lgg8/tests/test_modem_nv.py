"""Private snapshots must be stable and seed archives must match their receipts."""
import base64
import hashlib
import json
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import bootimg
import modem_nv_initramfs as archive
import modem_nv_snapshot as reader
from mkinitramfs import entry


class NvTest(unittest.TestCase):
    def test_changed_phone_cannot_publish_verified_snapshot(self):
        data = bytes(range(256))
        value = hashlib.sha256(data).hexdigest()
        for changed in (False, True):
            hash_calls = []

            def run(argv, **kwargs):
                command = argv[-1]
                if command.startswith('blockdev --getsize64 '):
                    output = b'256\r\n'
                elif command.startswith('sha256sum '):
                    hash_calls.append(command)
                    digest = '0' * 64 if changed and len(hash_calls) == 2 else value
                    output = ''.join(digest + '  /dev/block/by-name/' + n + '\r\n' for n in reader.NAMES).encode()
                elif command.startswith('base64 /dev/block/by-name/'):
                    output = base64.b64encode(data) + b'\r\n'
                else:
                    raise AssertionError('unexpected phone operation: ' + command)
                return SimpleNamespace(returncode=0, stdout=output, stderr=b'')

            with self.subTest(changed=changed), tempfile.TemporaryDirectory(prefix='efs-test-') as tmp:
                dest = Path(tmp) / 'snapshot'
                with patch.object(reader.subprocess, 'run', side_effect=run):
                    if changed:
                        with self.assertRaisesRegex(ValueError, 'changed during snapshot'):
                            reader.snapshot('test-phone', dest)
                        self.assertFalse((dest / 'verified.json').exists())
                    else:
                        self.assertTrue(reader.snapshot('test-phone', dest)['copy_verified'])
                        self.assertEqual((dest / 'modemst1').read_bytes(), data)
                        self.assertEqual(stat.S_IMODE(dest.stat().st_mode), 0o700)

    def test_seed_encoding_round_trip_and_changed_copy_rejection(self):
        with tempfile.TemporaryDirectory(prefix='efs-archive-') as tmp:
            root = Path(tmp)
            files = {}
            for name in archive.MAPPING:
                data = (name + '\0\r\n').encode()
                (root / name).write_bytes(data)
                files[name] = bootimg.describe(data)
            (root / 'verified.json').write_text(json.dumps({'copy_verified': True,
                'before_local_after_sha256_match': True, 'files': files}))
            base = root / 'base.gz'
            base.write_bytes(bootimg.gzip_member(entry('TRAILER!!!', 0), 0))
            decoded = []
            for encoding in ('gzip', 'xz'):
                result = bootimg.initramfs_cpio(archive.build(base, root, encoding))
                decoded.append(result)
                for name, target in archive.MAPPING.items():
                    self.assertEqual(result['opt/lgg8-rmtfs-input/' + target],
                                     (stat.S_IFREG | 0o600, (root / name).read_bytes()))
            self.assertEqual(*decoded)
            (root / 'modemst1').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'EFS file changed'):
                archive.build(base, root, 'xz')


if __name__ == '__main__':
    unittest.main()
