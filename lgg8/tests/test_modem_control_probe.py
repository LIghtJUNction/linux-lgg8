"""Exercise the exact native QMI reply parser with malformed wire messages."""
from pathlib import Path
import subprocess
import tempfile
import unittest


class ProbeTest(unittest.TestCase):
    def test_native_parser_and_arm64_parser_agree(self):
        source = Path(__file__).with_name('modem_control_probe.c').resolve()
        harness = r'''
#define main probe_network_main
#include "SOURCE"
#undef main
#include <assert.h>
int main(void) {
    unsigned char good[] = {2,1,0,0x23,0,12,0, 2,4,0,0,0,0,0, 1,2,0,'v','1'};
    unsigned char bad[sizeof(good)];
    char revision[16];
    assert(!revision_reply(good, sizeof(good), revision, sizeof(revision)));
    assert(!strcmp(revision, "v1"));
    for (size_t n=0; n<sizeof(good); n++)
        assert(revision_reply(good, n, revision, sizeof(revision)));
    const unsigned int offsets[] = {0,1,3,5,8,10,14,15,17};
    for (size_t i=0; i<sizeof(offsets)/sizeof(offsets[0]); i++) {
        memcpy(bad, good, sizeof(good)); bad[offsets[i]] = 0xff;
        assert(revision_reply(bad, sizeof(bad), revision, sizeof(revision)));
    }
    assert(revision_reply(good, sizeof(good), revision, 2));
    unsigned char uim[] = {2,2,0,0x2f,0,25,0, 2,4,0,0,0,0,0, 0x10,15,0,
                           255,255,255,255,255,255,255,255,1,0,0,0,0,0,0};
    unsigned char states[8]; unsigned int count;
    assert(!uim_reply(uim, sizeof(uim), states, &count));
    assert(count == 1 && states[0] == 0);
    for (size_t n=0; n<sizeof(uim); n++)
        assert(uim_reply(uim, n, states, &count));
    uim[sizeof(uim)-1] = 1;
    assert(uim_reply(uim, sizeof(uim), states, &count));
    unsigned char app[31] = {0};
    app[8] = 1; app[9] = 1; app[14] = 1; app[21] = 2;
    assert(!card_status(app, sizeof(app), states, &count));
    assert(states[0] == 1);
    app[21] = 255;
    assert(card_status(app, sizeof(app), states, &count));
    return 0;
}
'''.replace('SOURCE', str(source))
        with tempfile.TemporaryDirectory(prefix='modem-qmi-parser-') as temporary:
            root = Path(temporary)
            (root / 'test.c').write_text(harness)
            for compiler, flags, command in [('cc', ['-fsanitize=address,undefined'], []),
                                              ('aarch64-linux-gnu-gcc', ['-static'], ['qemu-aarch64'])]:
                binary = root / compiler
                subprocess.run([compiler, '-Os', '-Wall', '-Wextra', '-Werror', *flags,
                                str(root / 'test.c'), '-o', str(binary)], check=True, timeout=30)
                subprocess.run([*command, str(binary)], check=True, timeout=5)


if __name__ == '__main__':
    unittest.main()
