"""Reject malformed MDT inputs and firmware that escapes the MPSS region."""
import importlib.util
import base64
from pathlib import Path
import struct
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('modem_firmware', Path(__file__).resolve().parents[1] / 'tools/modem_firmware.py')
firmware = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(firmware)


def metadata(address=0x1000, size=4, memory=4096, flags=1 << 27):
    ident = b'\x7fELF\x01\x01\x01' + b'\0' * 9
    header = struct.pack('<16sHHIIIIIHHHHHH', ident, 2, 164, 1, 0, 52, 0, 0, 52, 32, 2, 0, 0, 0)
    load = struct.pack('<8I', 1, 0x1000, address, address, size, memory, flags, 4096)
    hashed = struct.pack('<8I', 1, 0, 0xffffffff, 0xffffffff, 128, 128, 2 << 24, 0)
    return header + load + hashed


class FirmwareTest(unittest.TestCase):
    def test_root_terminal_translation_cannot_corrupt_encoded_bytes(self):
        data = bytes(range(256)) * 7
        encoded = base64.encodebytes(data).replace(b'\n', b'\r\n')
        self.assertEqual(firmware.decode_transport(encoded), data)
        with self.assertRaises(ValueError):
            firmware.decode_transport(encoded + b'root# ')

    def test_relocation_and_fixed_address(self):
        with tempfile.TemporaryDirectory(prefix='modem-mdt-') as temp:
            root = Path(temp)
            (root / 'modem.b00').write_bytes(b'data')
            for data, relocated in [(metadata(), True), (metadata(address=firmware.MEM_BASE, flags=0), False)]:
                (root / 'modem.mdt').write_bytes(data)
                result = firmware.audit(root)
                self.assertEqual(result['status'], 'PASS')
                self.assertEqual(result['relocatable'], relocated)
                self.assertEqual(result['load_span'], 4096)
                self.assertFalse(result['signature_authenticated'])

    def test_bad_bounds_missing_segments_and_invalid_headers(self):
        with tempfile.TemporaryDirectory(prefix='modem-mdt-') as temp:
            root = Path(temp)
            (root / 'modem.b00').write_bytes(b'data')
            for data in [b'bad', metadata()[:60], metadata(size=5), metadata(size=5, memory=4),
                         metadata(flags=0), metadata(memory=firmware.MEM_SIZE + 1),
                         metadata(address=0xfffffff0), metadata().replace(b'\x7fELF\x01', b'\x7fELF\x02', 1)]:
                with self.subTest(data=data[:20]):
                    (root / 'modem.mdt').write_bytes(data)
                    with self.assertRaises(ValueError):
                        firmware.audit(root)
            (root / 'modem.mdt').write_bytes(metadata())
            (root / 'modem.b00').unlink()
            with self.assertRaises(ValueError):
                firmware.audit(root)


if __name__ == '__main__':
    unittest.main()
