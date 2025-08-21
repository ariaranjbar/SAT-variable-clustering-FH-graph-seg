import os
import tempfile
import csv
import types
from pathlib import Path
import unittest

# Ensure we can import the bench_runner module
import sys as _sys
# Repo root is three levels up from tests/: tests -> benchmarks -> scripts -> repo
_ROOT = Path(__file__).resolve().parents[3]
_sys.path.insert(0, str(_ROOT / "scripts/benchmarks"))

import bench_runner as br  # type: ignore


class TestBenchRunnerCore(unittest.TestCase):
    def test_validate_and_normalize_param_values(self):
        # enum acceptance and rejection
        pdef_enum = {"enum": ["naive", "opt"]}
        self.assertEqual(br._validate_and_normalize_param_values("impl", ["naive", "opt"], pdef_enum, True), ["naive", "opt"])
        with self.assertRaises(br.ConfigError):
            br._validate_and_normalize_param_values("impl", ["foo"], pdef_enum, True)

        # numeric min/max and int coercion
        pdef_num = {"numeric": "int", "min": 2, "max": 10}
        self.assertEqual(br._validate_and_normalize_param_values("tau", ["2", "5"], pdef_num, True), ["2", "5"])
        with self.assertRaises(br.ConfigError):
            br._validate_and_normalize_param_values("tau", ["1"], pdef_num, True)
        with self.assertRaises(br.ConfigError):
            br._validate_and_normalize_param_values("tau", ["abc"], pdef_num, True)

        # allow_inf passthrough
        pdef_inf = {"numeric": "int", "min": 2, "allow_inf": True}
        self.assertEqual(br._validate_and_normalize_param_values("tau", ["inf", "3"], pdef_inf, True), ["inf", "3"])

    def test_format_cmd_substitution_and_cleanup(self):
        tmpl = [
            "${bin}", "-i", "${input}",
            "-t", "${threads}",
            "--maxbuf", "${maxbuf}",
        ]
        infile = Path("/tmp/test.cnf")
        cmd = br._format_cmd(tmpl, {"threads": "2"}, infile, bin_path=Path("/bin/echo"))
        # maxbuf should be pruned entirely
        self.assertEqual(cmd, ["/bin/echo", "-i", str(infile), "-t", "2"])

    def test_product_sweep_with_conditions(self):
        base = {"threads": "1"}
        specs = [
            {"name": "impl", "values": ["naive", "opt"]},
            {"name": "maxbuf", "values": ["10"], "when": {"equals": {"key": "impl", "value": "opt"}}},
        ]
        combos = br._product_sweep(specs, base)
        # Expect two combos; only opt should have maxbuf
        self.assertIn({"threads": "1", "impl": "naive"}, combos)
        self.assertIn({"threads": "1", "impl": "opt", "maxbuf": "10"}, combos)


class TestRunAlgorithmSkipExisting(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.tmpdir.name) / "out"
        self.bench_dir = Path(self.tmpdir.name) / "bench"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.bench_dir.mkdir(parents=True, exist_ok=True)
        # Create a tiny fake .cnf file (content won't be read by mocked runner)
        (self.bench_dir / "toy.cnf").write_text("p cnf 1 0\n")

        # Minimal algorithm config with simple schema
        self.algo_cfg = {
            "cmd_template": ["${bin}", "-i", "${input}", "--foo", "${foo}", "--bar", "${bar}"],
            "base_params": {},
            "params": [
                {"name": "foo", "cli": "--foos", "type": "string", "default": ["A", "B"]},
                {"name": "bar", "cli": "--bars", "type": "int", "default": [1], "numeric": "int", "min": 1,
                 "when": {"equals": {"key": "foo", "value": "B"}}},
            ],
            "csv": {
                "path": "toy_results.csv",
                "header": ["file", "foo", "bar", "memlimit_mb", "x", "y"],
                "required_keys": ["x", "y", "foo"],
                "key_cols": [0, 1, 2]
            }
        }

        # Namespace-like object emulating argparse output
        self.ns = types.SimpleNamespace(
            num=1,
            bin=Path("/bin/true"),
            memlimits=[],
            cache=False,
            reuse_files=False,
            reuse_csv=None,
            skip_existing=True,
            dry_run=False,
            verbose=False,
            bench_dir=self.bench_dir,
            out_dir=self.out_dir,
            foos=["A", "B"],
            bars=[1],
        )

        # Patch the runner to avoid executing external binaries
        self._orig_runner = br.run_with_streaming

        def fake_run(cmd, infile, log_path, verbose, memlimit_mb=None):
            # Simulate tool output lines with required keys
            # Echo the chosen foo/bar if present
            foo = None
            bar = None
            for i, tok in enumerate(cmd):
                if tok == "--foo":
                    foo = cmd[i + 1]
                if tok == "--bar":
                    bar = cmd[i + 1]
            line = f"x=1 y=2 foo={foo or 'A'} bar={bar or ''}"
            return 0, [line]

        br.run_with_streaming = fake_run  # type: ignore

    def tearDown(self):
        br.run_with_streaming = self._orig_runner  # type: ignore
        self.tmpdir.cleanup()

    def test_skip_existing_prevents_duplicates(self):
        # First run: should write rows to CSV
        rc1 = br.run_algorithm_from_registry("toy", self.ns, self.algo_cfg)
        self.assertEqual(rc1, 0)
        csv_path = self.out_dir / "toy_results.csv"
        self.assertTrue(csv_path.exists())
        with csv_path.open() as f:
            rows1 = list(csv.reader(f))
        # header + two rows (foo=A without bar; foo=B with bar=1)
        self.assertGreaterEqual(len(rows1), 3)

        # Second run with same params and skip_existing: no new rows should be appended
        rc2 = br.run_algorithm_from_registry("toy", self.ns, self.algo_cfg)
        self.assertEqual(rc2, 0)
        with csv_path.open() as f:
            rows2 = list(csv.reader(f))
        self.assertEqual(len(rows1), len(rows2))


if __name__ == "__main__":
    unittest.main(verbosity=2)
