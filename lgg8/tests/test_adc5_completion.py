"""Exercise the actual ADC5 conversion functions against a fake IRQ and bus."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


TESTS = Path(__file__).resolve().parent
SOURCE = TESTS.parents[1] / "drivers/iio/adc/qcom-spmi-adc5.c"


def function(source, name):
    start = source.index("static int " + name + "(")
    end = source.index("\n}\n", start) + 3
    return source[start:end]


class Adc5CompletionTest(unittest.TestCase):
    def test_irq_and_polling_require_completed_status(self):
        source = SOURCE.read_text()
        constants = []
        for name in ("ADC5_USR_STATUS1", "ADC5_USR_STATUS1_EOC",
                     "ADC5_USR_STATUS1_REQ_STS_EOC_MASK", "ADC5_CONV_TIME_RETRY",
                     "ADC5_CONV_TIME_MIN_US", "ADC5_CONV_TIME_MAX_US", "ADC5_CONV_TIMEOUT"):
            constants.append(re.search(r"^#define " + name + r"\s+[^\n]+", source, re.M)[0])
        with tempfile.TemporaryDirectory(prefix="adc5-completion-", dir=TESTS) as temp:
            directory = Path(temp)
            (directory / "actual-adc5.h").write_text("\n".join(constants) + "\n" +
                function(source, "adc5_poll_wait_eoc") + "\n" +
                function(source, "adc5_do_conversion"))
            binary = directory / "test-adc5"
            env = os.environ.copy()
            env["TMPDIR"] = temp
            subprocess.run([os.environ.get("CC", "cc"), "-pipe", "-std=gnu11",
                            "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-O2",
                            "-I", str(directory), str(TESTS / "test_adc5_completion.c"),
                            "-o", str(binary)], check=True, env=env)
            subprocess.run([str(binary)], check=True, timeout=5)


if __name__ == "__main__":
    unittest.main()
