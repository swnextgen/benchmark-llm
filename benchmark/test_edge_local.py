"""Offline regression checks: python3 -m unittest discover -s benchmark -p 'test_edge_local.py'."""

import json
import os
from pathlib import Path
import pty
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import edge_benchmark as edge


class EdgeLocalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.model = self.root / "local model.gguf"
        self.model.write_text("test fixture")
        self.binary = self.root / "llama-completion"
        self.binary.write_text(f"#!{sys.executable}\nprint('READY')\n")
        self.binary.chmod(0o755)

    def test_cli_defaults_and_local_preflight(self):
        args = edge.parse_args(["--model", str(self.model), "--binary", str(self.binary)])
        self.assertEqual((args.runner_mode, args.threads, args.ctx), ("completion", 8, 4096))
        self.assertEqual(args.niah_contexts, "512,1024,2048")
        self.assertEqual(edge.parse_args(["-c", "32768"]).niah_contexts, "4096,8192,16384")
        self.assertEqual(edge.parse_args(["--niah-contexts", "100,200"]).niah_contexts, "100,200")
        self.assertEqual(edge.parse_args(["--runner-mode", "openai"]).runner_mode, "openai")
        with patch.object(edge, "OpenAIChatRunner", side_effect=AssertionError("Unexpected API call")):
            edge.preflight(args)

    def test_missing_model_or_nonexecutable_binary_is_rejected(self):
        with self.assertRaisesRegex(SystemExit, "Model file"):
            edge.LlamaRunner(str(self.binary), str(self.root / "missing.gguf"))
        self.binary.chmod(0o644)
        with self.assertRaisesRegex(SystemExit, "not executable"):
            edge.LlamaRunner(str(self.binary), str(self.model))

    def test_direct_command_writes_local_report(self):
        for mode in ("both", "performance", "tasks"):
            with self.subTest(mode=mode):
                result_dir = self.root / mode
                command = [sys.executable, str(Path(edge.__file__).resolve()), "--model", str(self.model),
                           "--binary", str(self.binary), "-t", "8", "-c", "4096", "--result-dir", str(result_dir)]
                if mode != "both":
                    command += ["--benchmark-type", mode]
                result = subprocess.run(
                    command, env=dict(os.environ, MPLBACKEND="Agg", MPLCONFIGDIR=str(self.root / "mpl")),
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(next(result_dir.glob("*-result.json")).read_text())
                self.assertEqual(report["platform"]["runner_mode"], "completion")
                self.assertEqual(report["platform"]["ctx"], 4096)
                self.assertEqual(bool(report["coding"]), mode != "performance")
                self.assertEqual(set(report["niah"]), set() if mode == "tasks" else {"512", "1024", "2048"})
                self.assertTrue((result_dir / "dashboard.html").is_file())
                self.assertTrue((result_dir / "benchmark-end-epoch").is_file())

    def test_completion_arguments_output_and_failure_cleanup(self):
        runner = edge.LlamaRunner(str(self.binary), str(self.model), threads=6, ctx=8192)
        response = dict(returncode=0, elapsed=1, stdout="READY", stderr="engine log", output="READY\nengine log")
        with patch.object(edge, "run_command", return_value=response) as run:
            self.assertEqual(runner.generate("test prompt")["response"], "READY")
        command = run.call_args.args[0]
        for flag, value in (("-m", str(self.model)), ("-t", "6"), ("-c", "8192")):
            self.assertEqual(command[command.index(flag) + 1], value)
        self.assertFalse(Path(command[command.index("-f") + 1]).exists())
        with patch.object(edge, "run_command", return_value=dict(response, returncode=2)) as run:
            with self.assertRaisesRegex(RuntimeError, "exit 2"):
                runner.generate("bad request")
        command = run.call_args.args[0]
        self.assertFalse(Path(command[command.index("-f") + 1]).exists())

    def prepare_wrapper(self):
        bench = self.root / "benchmark"
        bench.mkdir()
        shutil.copyfile(Path(edge.__file__).with_name("run.sh"), bench / "run.sh")
        self.calls = self.root / "python-calls.jsonl"
        binaries = self.root / "bin"
        binaries.mkdir()
        python = binaries / "python3"
        python.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "with open(os.environ['EDGE_TEST_CALLS'], 'a') as f:\n"
            "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "if sys.argv[1:2] == ['-c']: print('1 6')\n"
        )
        python.chmod(0o755)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("EDGE_", "OPENAI_", "BENCHMARK_", "BENCH_CONFIG"))}
        self.env.update(PATH=f"{binaries}:{os.environ['PATH']}", BENCH_CONFIG="/dev/null",
                        EDGE_TEST_CALLS=str(self.calls), BENCHMARK_PROFILE="edge", BENCHMARK_TYPE="both",
                        EDGE_MODEL=str(self.model), EDGE_BINARY=str(self.binary),
                        OPENAI_BASE_URL="http://unused.invalid/v1", OPENAI_MODEL="unused-api-model",
                        OPENAI_MODEL_DISPLAY_NAME="Unused API name", OPENAI_API_KEY="do-not-save")

    def run_wrapper(self, answers=None):
        command = ["bash", str(self.root / "benchmark/run.sh")]
        if answers is None:
            return subprocess.run(command, cwd=self.root, env=self.env, stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, timeout=10)
        master, slave = pty.openpty()
        try:
            proc = subprocess.Popen(command, cwd=self.root, env=self.env, stdin=slave,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            try:
                os.write(master, answers.encode())
                output, _ = proc.communicate(timeout=10)
                return subprocess.CompletedProcess(command, proc.returncode, output)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate()
        finally:
            os.close(master)
            os.close(slave)

    def final_arguments(self):
        return json.loads(self.calls.read_text().splitlines()[-1])

    def test_edge_menu_asks_only_for_local_paths(self):
        self.prepare_wrapper()
        self.env.update(BENCHMARK_PROFILE="advanced", BENCHMARK_TYPE="quick")
        result = self.run_wrapper(f"1\n{self.model}\n{self.binary}\n")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Model path (GGUF)", result.stdout)
        self.assertIn("llama-completion path", result.stdout)
        for prompt in ("OpenAI API URL", "Model ID", "Display model name", "Benchmark content:"):
            self.assertNotIn(prompt, result.stdout)
        args = self.final_arguments()
        for flag, value in (("--runner-mode", "completion"), ("--benchmark-type", "both"),
                            ("--model", str(self.model)), ("--binary", str(self.binary)),
                            ("--display-name", self.model.name), ("-t", "8"), ("-c", "4096")):
            self.assertEqual(args[args.index(flag) + 1], value)
        self.assertNotIn("--api-base-url", args)

    def test_noninteractive_run_and_resume_preserve_local_settings(self):
        self.prepare_wrapper()
        self.env.update(EDGE_THREADS="3", EDGE_CONTEXT_TOKENS="8192")
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        saved = next((self.root / "benchmark-results").glob("*/resume.env"))
        self.assertNotIn("do-not-save", saved.read_text())
        self.assertNotIn("EDGE_BASE_URL", saved.read_text())
        self.env.update(EDGE_THREADS="8", EDGE_CONTEXT_TOKENS="4096", EDGE_MODEL="wrong.gguf", EDGE_BINARY="wrong-binary")
        result = self.run_wrapper("1\n")
        self.assertEqual(result.returncode, 0, result.stdout)
        args = self.final_arguments()
        self.assertIn("--resume", args)
        for flag, value in (("--model", str(self.model)), ("--binary", str(self.binary)),
                            ("--result-dir", str(saved.parent)), ("-t", "3"), ("-c", "8192")):
            self.assertEqual(args[args.index(flag) + 1], value)


if __name__ == "__main__":
    unittest.main()
