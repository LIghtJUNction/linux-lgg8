import os
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class Sw42000ParserTest(unittest.TestCase):
    def test_wire_format_and_release_rules(self):
        output_dir = ROOT / "out/lgg8/validation"
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="sw42000-parser-", dir=output_dir) as work:
            binary = pathlib.Path(work) / "sw42000_parser_test"
            env = os.environ.copy()
            env.update(TMPDIR=work, TMP=work, TEMP=work)
            subprocess.run(
                [
                    "cc",
                    "-pipe",
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    str(ROOT / "lgg8/tests/sw42000_parser_test.c"),
                    "-o",
                    str(binary),
                ],
                check=True,
                cwd=ROOT,
                env=env,
            )
            result = subprocess.run(
                [str(binary)], check=True, capture_output=True, text=True, env=env
            )
            self.assertIn("SW42000 parser checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
