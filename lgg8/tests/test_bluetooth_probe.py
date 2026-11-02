"""Reject unrelated, corrupt or failed management command completions."""
from pathlib import Path
import subprocess
import tempfile
import unittest


class BluetoothTest(unittest.TestCase):
    def test_native_and_arm64_reply_validation(self):
        source = Path(__file__).with_name('bluetooth_probe.c').resolve()
        code = r'''
#define main network_main
#include "SOURCE"
#undef main
#include <assert.h>
int main(void) {
    unsigned char good[] = {1,0,255,255,7,0,3,0,0,1,0,0,0};
    assert(complete_reply(good, sizeof(good), 3, 65535) == 4);
    for (size_t n=0; n<sizeof(good); n++)
        assert(complete_reply(good, n, 3, 65535) < 0);
    assert(complete_reply(good, sizeof(good), 4, 65535) == -EAGAIN);
    assert(complete_reply(good, sizeof(good), 3, 0) == -EAGAIN);
    good[8] = 1;
    assert(complete_reply(good, sizeof(good), 3, 65535) == -EIO);
    return 0;
}
'''.replace('SOURCE', str(source))
        with tempfile.TemporaryDirectory(prefix='bluetooth-wire-') as tmp:
            root = Path(tmp)
            (root / 'test.c').write_text(code)
            for cc, flags, prefix in [('cc', ['-fsanitize=address,undefined'], []),
                                      ('aarch64-linux-gnu-gcc', ['-static'], ['qemu-aarch64'])]:
                binary = root / cc
                subprocess.run([cc, '-Wall', '-Wextra', '-Werror', '-Os', *flags,
                                str(root / 'test.c'), '-o', str(binary)], check=True)
                subprocess.run([*prefix, str(binary)], check=True, timeout=10)


if __name__ == '__main__':
    unittest.main()
