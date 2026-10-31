"""Exercise the actual TCPM setter with controlled callback outcomes."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class CurrentLimitTest(unittest.TestCase):
    def test_callback_outcomes(self):
        source = (ROOT / "drivers/usb/typec/tcpm/tcpm.c").read_text()
        start = source.index("static int tcpm_set_current_limit(")
        end = source.index("\nstatic int tcpm_set_charge(", start)
        setter = source[start:end]
        harness = r'''
#include <assert.h>
#include <errno.h>
typedef unsigned int u32;
struct tcpc_dev { int (*set_current_limit)(struct tcpc_dev *, u32, u32); };
struct tcpm_port { u32 supply_voltage, current_limit; void *psy; struct tcpc_dev *tcpc; };
static int notifications;
#define tcpm_log(...) ((void)0)
static void power_supply_changed(void *p) { (void)p; notifications++; }
static int accept(struct tcpc_dev *t, u32 a, u32 b)
{ (void)t; (void)a; (void)b; return 0; }
static int reject(struct tcpc_dev *t, u32 a, u32 b)
{ (void)t; (void)a; (void)b; return -EIO; }
'''+ setter + r'''
int main(void)
{
    struct tcpc_dev t = { reject };
    struct tcpm_port p = { 5000, 500, 0, &t };
    assert(tcpm_set_current_limit(&p, 3000, 9000) == -EIO);
    assert(p.current_limit == 500 && p.supply_voltage == 5000 && notifications == 0);
    t.set_current_limit = accept;
    assert(tcpm_set_current_limit(&p, 3000, 9000) == 0);
    assert(p.current_limit == 3000 && p.supply_voltage == 9000 && notifications == 1);
    t.set_current_limit = 0;
    assert(tcpm_set_current_limit(&p, 500, 5000) == -EOPNOTSUPP);
    assert(p.current_limit == 500 && p.supply_voltage == 5000 && notifications == 2);
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="lgg8-tcpm-", dir="/dev/shm") as tmp:
            directory = Path(tmp)
            test_source = directory / "test.c"
            binary = directory / "test"
            test_source.write_text(harness)
            env = {**os.environ, "TMPDIR": "/dev/shm"}
            subprocess.run(["cc", "-Wall", "-Wextra", "-Werror", str(test_source),
                            "-o", str(binary)], check=True, env=env)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
