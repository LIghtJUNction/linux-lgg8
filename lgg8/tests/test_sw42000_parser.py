import pathlib
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class Sw42000ParserTest(unittest.TestCase):
    def test_wire_format_and_release_rules(self):
        output_dir = ROOT / "out/lgg8/validation"
        output_dir.mkdir(parents=True, exist_ok=True)
        binary = output_dir / "sw42000_parser_test"

        try:
            subprocess.run(
                [
                    "cc",
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
            )
            result = subprocess.run(
                [str(binary)], check=True, capture_output=True, text=True
            )
            self.assertIn("SW42000 parser checks passed", result.stdout)
        finally:
            binary.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
