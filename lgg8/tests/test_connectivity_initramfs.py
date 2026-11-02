"""Firmware augmentation must preserve private inputs and reject changed copies."""
import json
import lzma
from pathlib import Path
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import bootimg
import connectivity_initramfs
from mkinitramfs import entry


class ConnectivityArchiveTest(unittest.TestCase):
    def fixture(self, root):
        original = entry('dev', stat.S_IFDIR | 0o755, ino=1)
        original += entry('dev/console', stat.S_IFCHR | 0o600, ino=2, rdev=(5, 1))
        original += entry('opt/private-shadow', stat.S_IFREG | 0o600, b'PRIVATE-FIXTURE', ino=3)
        raw = original + entry('TRAILER!!!', 0, ino=4)
        base = root / 'base.xz'
        base.write_bytes(lzma.compress(raw, check=lzma.CHECK_CRC32))
        extra, board = root / 'extra', root / 'board'
        extra.mkdir(); board.mkdir()
        (extra / 'modem_pr').mkdir()
        files = {'wlanmdsp.mbn': b'WLAN-FIXTURE', 'modem_pr/config': b'CONFIG-FIXTURE'}
        for name, data in files.items():
            (extra / name).write_bytes(data)
        (extra / 'verified.json').write_text(json.dumps({
            'copy_verified': True, 'files': {n: bootimg.describe(d) for n, d in files.items()}}))
        (board / 'bdwlan.bin').write_bytes(b'BOARD-FIXTURE')
        (board / 'verified.json').write_text(json.dumps({
            'copy_verified': True, 'file': bootimg.describe(b'BOARD-FIXTURE')}))
        return base, extra, board, original

    def test_preserves_private_entries_device_headers_and_stock_board(self):
        with tempfile.TemporaryDirectory() as temp:
            base, extra, board, original = self.fixture(Path(temp))
            archive, receipt = connectivity_initramfs.build(base, bootimg.sha(base.read_bytes()), extra, board)
            self.assertTrue(lzma.decompress(archive).startswith(original))
            entries = bootimg.initramfs_cpio(archive)
            self.assertEqual(entries['opt/private-shadow'][1], b'PRIVATE-FIXTURE')
            self.assertEqual(entries['lib/firmware/ath10k/WCN3990/hw1.0/board.bin'][1], b'BOARD-FIXTURE')
            self.assertEqual(entries['lib/firmware/qcom/lg/alphalm/wlanmdsp.mbn'][1], b'WLAN-FIXTURE')
            self.assertTrue(receipt['may_contain_private_efs'])
            self.assertFalse(receipt['device_execution_verified'])

    def test_rejects_wrong_base_changed_stock_copy_and_unsafe_path(self):
        with tempfile.TemporaryDirectory() as temp:
            base, extra, board, _ = self.fixture(Path(temp))
            digest = bootimg.sha(base.read_bytes())
            with self.assertRaises(ValueError):
                connectivity_initramfs.build(base, '0' * 64, extra, board)
            (board / 'bdwlan.bin').write_bytes(b'CHANGED')
            with self.assertRaises(ValueError):
                connectivity_initramfs.build(base, digest, extra, board)
            (board / 'bdwlan.bin').write_bytes(b'BOARD-FIXTURE')
            r = extra / 'verified.json'
            r.write_text(json.dumps({'copy_verified': True, 'files': {'modem_pr/../../escape': {}}}))
            with self.assertRaises(ValueError):
                connectivity_initramfs.build(base, digest, extra, board)

    def test_optional_host_metadata_is_verified_and_restricted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base, extra, board, _ = self.fixture(root)
            host = root / 'host'
            host.mkdir()
            (host / 'regulatory.db').write_bytes(b'REGDB-FIXTURE')
            record = host / 'verified.json'
            record.write_text(json.dumps({'copy_verified': True, 'files': {
                'regulatory.db': bootimg.describe(b'REGDB-FIXTURE')}}))
            digest = bootimg.sha(base.read_bytes())
            archive, _ = connectivity_initramfs.build(base, digest, extra, board, host)
            self.assertEqual(bootimg.initramfs_cpio(archive)['lib/firmware/regulatory.db'][1], b'REGDB-FIXTURE')
            record.write_text(json.dumps({'copy_verified': True, 'files': {'../escape': {}}}))
            with self.assertRaises(ValueError):
                connectivity_initramfs.build(base, digest, extra, board, host)


if __name__ == '__main__':
    unittest.main()
