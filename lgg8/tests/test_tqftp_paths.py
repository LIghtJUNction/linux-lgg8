"""Exercise upstream file translation against synthetic firmware and RAM roots."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / 'out/lgg8-tqftp-20261102/vendor/tqftpserv'
HARNESS = r'''
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include "translate.h"
int main(void) {
    const char *ro[] = {"/readonly/firmware/image/wlanmdsp.mbn",
                       "/readonly/vendor/firmware_mnt/image/wlanmdsp.mbn"};
    char buf[32];
    int fd;
    for (unsigned i = 0; i < 2; i++) {
        fd = translate_open(ro[i], O_RDONLY);
        assert(fd >= 0 && read(fd, buf, sizeof(buf)) == 11);
        assert(!memcmp(buf, "FW-FIXTURE\n", 11)); close(fd);
        fd = translate_open(ro[i], O_WRONLY | O_CREAT);
        assert(fd >= 0 && write(fd, "X", 1) == -1 && errno == EBADF);
        close(fd);
    }
    fd = translate_open("/readwrite/server_check.txt", O_WRONLY | O_CREAT);
    assert(fd >= 0 && write(fd, "RAM", 3) == 3); close(fd);
    fd = translate_open("/readwrite/server_check.txt", O_RDONLY);
    assert(fd >= 0 && read(fd, buf, sizeof(buf)) == 3);
    assert(!memcmp(buf, "RAM", 3)); close(fd);
    const char *bad[] = {"/readwrite/../escape", "/readwrite//escape",
                        "/readonly/firmware/image/../escape",
                        "/readonly/vendor/firmware_mnt/image//escape"};
    for (unsigned i = 0; i < 4; i++) {
        assert(translate_open(bad[i], O_RDONLY) == -1 && errno == EACCES);
    }
    puts("TQFTP_PATHS_OK");
    return 0;
}
'''


@unittest.skipUnless(VENDOR.is_dir() and shutil.which('qemu-aarch64'), 'requires retained upstream and ARM64 QEMU')
class TranslationTest(unittest.TestCase):
    def test_readonly_firmware_ram_writes_and_traversal_rejection(self):
        with tempfile.TemporaryDirectory(prefix='lgg8-tqftp-test-') as temp:
            root = Path(temp)
            firmware = root / 'firmware/qcom/lg/alphalm'
            firmware.mkdir(parents=True)
            fixture = firmware / 'wlanmdsp.mbn'
            fixture.write_bytes(b'FW-FIXTURE\n')
            remote = root / 'remoteproc/remoteproc0'
            remote.mkdir(parents=True)
            (remote / 'firmware').write_text('qcom/lg/alphalm/modem.mdt\n')
            (root / 'fwpath').write_text('\n')
            # Redirect only environment paths, leaving translation and I/O logic intact.
            source = (VENDOR / 'translate.c').read_text()
            replacements = {
                '"/lib/firmware/"': str(root / 'firmware') + '/',
                '"/var/lib/tqftpserv"': str(root / 'ram'),
                '"/sys/class/remoteproc"': str(root / 'remoteproc'),
                '"/sys/module/firmware_class/parameters/path"': str(root / 'fwpath')}
            for old, new in replacements.items():
                self.assertEqual(source.count(old), 1)
                source = source.replace(old, json.dumps(new))
            (root / 'translate.c').write_text(source)
            (root / 'harness.c').write_text(HARNESS)
            for cc, flags, prefix in [('gcc', ['-fsanitize=address,undefined', '-g'], []),
                                      ('aarch64-linux-gnu-gcc', ['-static'], ['qemu-aarch64'])]:
                binary = root / cc
                command = [cc, '-O1', '-Wall', '-Wextra', *flags, '-I' + str(VENDOR),
                           str(root / 'translate.c'), str(root / 'harness.c'), '-o', str(binary)]
                subprocess.run(command, check=True, capture_output=True)
                env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=1:abort_on_error=1'}
                result = subprocess.run(prefix + [str(binary)], env=env, check=True,
                                        capture_output=True, timeout=15)
                self.assertEqual(result.stdout, b'TQFTP_PATHS_OK\n')
                self.assertEqual(fixture.read_bytes(), b'FW-FIXTURE\n')
                self.assertEqual((root / 'ram/server_check.txt').read_bytes(), b'RAM')


if __name__ == '__main__':
    unittest.main()
