"""Run upstream's shadow-storage implementation against a disposable image."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / 'out/lgg8-rmtfs-20261102/vendor'
HARNESS = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "rmtfs.h"
int main(int argc, char **argv) {
    assert(argc == 2);
    char path[4096], before[512], after[512], content[512];
    memset(before, 0x5a, sizeof(before));
    snprintf(path, sizeof(path), "%s/modem_fs1", argv[1]);
    int fd = open(path, O_RDWR | O_CREAT | O_EXCL, 0600);
    assert(fd >= 0 && write(fd, before, sizeof(before)) == sizeof(before));
    close(fd);
    assert(storage_init(argv[1], true, false) == 0);
    struct rmtfd *r = storage_open(0, "/boot/modem_fs1", "");
    assert(r);
    assert(storage_pread(r, content, sizeof(content), 0) == sizeof(content));
    assert(!memcmp(content, before, sizeof(content)));
    memset(content, 0xa5, sizeof(content));
    assert(storage_pwrite(r, content, sizeof(content), 0) == sizeof(content));
    assert(storage_sync(r) == 0);
    assert(storage_pread(r, after, sizeof(after), 0) == sizeof(after));
    assert(!memcmp(content, after, sizeof(after)));
    storage_close(r);
    r = storage_open(0, "/boot/modem_fs1", "");
    assert(r && storage_pread(r, after, sizeof(after), 0) == sizeof(after));
    assert(!memcmp(before, after, sizeof(after)));
    storage_exit();
    fd = open(path, O_RDONLY);
    assert(fd >= 0 && read(fd, after, sizeof(after)) == sizeof(after));
    assert(!memcmp(before, after, sizeof(before)));
    close(fd);
    puts("RMTFS_SHADOW_PRESERVES_SOURCE");
    return 0;
}
'''


class ShadowTest(unittest.TestCase):
    @unittest.skipUnless((VENDOR / 'rmtfs/storage.c').is_file(), 'requires pinned upstream checkout')
    def test_real_storage_writes_only_shadow_on_native_and_arm64(self):
        for compiler, emulator, flags in [('cc', [], ['-fsanitize=address,undefined']),
                                           ('aarch64-linux-gnu-gcc', ['qemu-aarch64'], ['-static'])]:
            with self.subTest(compiler=compiler), tempfile.TemporaryDirectory(prefix='rmtfs-shadow-') as tmp:
                p = Path(tmp)
                (p / 'test.c').write_text(HARNESS)
                command = [compiler, '-g', '-O1', *flags,
                           '-I' + str(VENDOR / 'qrtr/include'), '-I' + str(VENDOR / 'rmtfs'),
                           str(p / 'test.c'), str(VENDOR / 'rmtfs/storage.c'), '-o', str(p / 'test')]
                subprocess.run(command, check=True, capture_output=True)
                output = subprocess.check_output([*emulator, str(p / 'test'), str(p)], timeout=10)
                self.assertIn(b'RMTFS_SHADOW_PRESERVES_SOURCE', output)


if __name__ == '__main__':
    unittest.main()
