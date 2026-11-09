#!/usr/bin/env python3
"""
edge_benchmark.py

Single combined benchmark script. Everything in one file:

  - Performance suite: Basic TPS, Prefill TPS, Decode TPS, TTFT, Latency
  - NIAH (needle in a haystack)
  - Advanced Reasoning Suite (10 categorized CoT cases: arithmetic,
    logic deduction, word/rate problems, syllogism, combinatorics,
    common sense, age problems, multi-hop QA, self-referential logic,
    probability)
  - Original Reasoning Suite (10 quick arithmetic/logic items)
  - Logic Benchmark
  - HumanEval Lite
  - Agent Tasks
  - RAG Benchmark
  - Final Leaderboard, JSON/CSV export, HTML dashboard, charts,
    benchmark history

Three runner backends, chosen with --runner-mode:

  1. completion (default) -- subprocess mode, calls a llama-completion-
     style binary per prompt via a temp prompt file. No server needed.
     This is the original llama_bench_v3/v4 behavior, unchanged.

  2. server -- HTTP mode, launches llama-server once per model (or hits
     an already-running one with --server-url), then sends every prompt
     over HTTP to /completion. Faster for many short prompts since the
     model stays loaded and slots are reused instead of reloading the
     model from disk on every single subprocess call.

  3. openai -- uses an already-running OpenAI-compatible Chat Completions
     endpoint. Select explicitly with --runner-mode openai.

All runner classes expose the same generate(prompt, predict) ->
dict(prompt, response, elapsed, prefill_tps, decode_tps, prompt_tokens)
interface, so every benchmark_* function works unchanged regardless of
which backend is active.

Usage:

  # Subprocess mode (original behavior, no server)
  python3 benchmark/edge_benchmark.py \\
      --model /path/model.gguf \\
      --binary /path/llama-completion -t 8 -c 4096

  # Server mode, script launches llama-server itself
  python3 benchmark/edge_benchmark.py \\
      --runner-mode server \\
      --model /path/model.gguf \\
      --llama-server-bin /path/llama-server \\
      -t 8 -c 4096 --ngl 99 --server-parallel 1

  # Server mode, against an already-running llama-server
  python3 benchmark/edge_benchmark.py \\
      --runner-mode server \\
      --server-url http://127.0.0.1:8080 \\
      --model /path/model.gguf
"""

import os
import re
import json
import csv
import time
import math
import random
import signal
import socket
import platform
import argparse
import html
import tempfile
import statistics
import subprocess

try:
    import resource
except ImportError:
    resource = None

import urllib.request
import urllib.error

from pathlib import Path
from datetime import datetime

try:
    import matplotlib.pyplot as plt
except Exception:
    plt = None

DEFAULT_BINARY = "./build/bin/llama-completion"
RESULT_DIR = "results"
CHART_DIR = os.path.join(RESULT_DIR, "charts")
# Set per model by benchmark_main: run_steps checkpoints here after every section so --resume can skip finished ones.
CHECKPOINT_FILE = None
RESUME = False

# ============================================================
# FD LIMIT
#
# RKNPU backends (RK3588/CM3588) were observed leaking file
# descriptors across requests ("failed to convert handle(N) to
# fd, errno 24, Too many open files") once the default 1024 fd
# soft limit was exceeded, especially with multiple parallel
# server slots. Raising this proactively avoids mid-run crashes.
# ============================================================

def ensure_fd_limit(target=65536):
    if resource is None:
        return
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        new_soft = min(target, hard) if hard != resource.RLIM_INFINITY else target
        if new_soft > soft:
            resource.setrlimit(resource.RLIMIT_NOFILE, (new_soft, hard))
            print(f"Raised open-file limit: {soft} -> {new_soft}")
    except Exception as e:
        print(f"Warning: could not raise fd limit ({e}). If you hit "
              f"'Too many open files' errors, run 'ulimit -n 65536' "
              f"before launching this script.")

# ============================================================
# FILESYSTEM
# ============================================================

def ensure_dirs():
    Path(RESULT_DIR).mkdir(parents=True, exist_ok=True)
    Path(CHART_DIR).mkdir(parents=True, exist_ok=True)

def ram_gib():
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3, 2)
    except (ValueError, OSError):
        return None

# ============================================================
# MODEL DISCOVERY
# ============================================================

def discover_models(patterns):
    models = []
    for pattern in patterns:
        if "*" in pattern:
            models.extend([str(x) for x in Path(".").glob(pattern)])
        else:
            models.append(pattern)
    return sorted(models)

# ============================================================
# TPS PARSER (subprocess/completion mode)
# ============================================================

def parse_tps(output):
    result = {"prefill_tps": 0.0, "decode_tps": 0.0, "prompt_tokens": 0}
    for line in output.splitlines():
        if "prompt eval time" in line:
            m = re.search(r"/\s*(\d+)\s*tokens.*?([\d.]+)\s*tokens per second", line)
            if m:
                result["prompt_tokens"] = int(m.group(1))
                result["prefill_tps"] = float(m.group(2))
        elif "eval time" in line and "prompt eval time" not in line:
            m = re.search(r"([\d.]+)\s*tokens per second", line)
            if m:
                result["decode_tps"] = float(m.group(1))
    return result

# ============================================================
# RESPONSE EXTRACTION (subprocess/completion mode)
# ============================================================

def extract_model_response(text):
    text = re.sub(r"common_perf_print:.*", "", text, flags=re.S)
    if "[End thinking]" in text:
        text = text.split("[End thinking]")[-1]
    return text.strip()

# ============================================================
# COMMAND RUNNER (subprocess/completion mode)
# ============================================================

def run_command(cmd, timeout=1800):
    start = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        elapsed = time.time() - start
        return {
            "returncode": p.returncode,
            "elapsed": elapsed,
            "stdout": p.stdout,
            "stderr": p.stderr,
            "output": (p.stdout or "") + (p.stderr or "")
        }
    except subprocess.TimeoutExpired:
        return {
            "returncode": -1,
            "elapsed": timeout,
            "stdout": "",
            "stderr": "TIMEOUT",
            "output": "TIMEOUT"
        }

# ============================================================
# LLAMA RUNNER (subprocess/completion mode -- original)
# ============================================================

class LlamaRunner:

    def __init__(self, binary, model, threads=8, ctx=4096):
        self.binary = str(Path(binary).expanduser().resolve())
        self.model = str(Path(model).expanduser().resolve())
        if not Path(self.model).is_file() or not os.access(self.model, os.R_OK):
            raise SystemExit(f"Model file is missing or unreadable: {self.model}")
        if not Path(self.binary).is_file() or not os.access(self.binary, os.X_OK):
            raise SystemExit(f"llama-completion binary is missing or not executable: {self.binary}")
        self.threads = threads
        self.ctx = ctx

    def generate(self, prompt, predict=128):
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write(prompt)
            prompt_file = f.name

        cmd = [
            self.binary,
            "-m", self.model,
            "--jinja",
            "-no-cnv",
            "--no-warmup",
            "-t", str(self.threads),
            "-c", str(self.ctx),
            "-n", str(predict),
            "-f", prompt_file
        ]

        try:
            result = run_command(cmd)
        finally:
            Path(prompt_file).unlink(missing_ok=True)

        if result["returncode"] != 0:
            raise RuntimeError(f"llama-completion failed (exit {result['returncode']}): {result['output'][-2000:]}")

        perf = parse_tps(result["output"])

        return {
            "prompt": prompt,
            "response": extract_model_response(result["stdout"]),
            "elapsed": result["elapsed"],
            "prefill_tps": perf["prefill_tps"],
            "decode_tps": perf["decode_tps"],
            "prompt_tokens": perf["prompt_tokens"],
            "raw_output": result["output"]
        }

# ============================================================
# SERVER LIFECYCLE (added -- HTTP/server mode)
# ============================================================

def wait_for_server(base_url, timeout=180):
    """
    Polls /health until 200, then sends a tiny real completion request
    and retries on 503 ("Loading model"). Some llama-server builds
    (notably RK NPU backends where model loading involves an extra
    weight-mapping step) report /health as OK before the model is
    actually ready to serve, which otherwise causes the first real
    request to 500/503.
    """
    health_url = base_url.rstrip("/") + "/health"
    start = time.time()
    health_ok = False
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(health_url)
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    health_ok = True
                    break
        except (urllib.error.URLError, ConnectionResetError, socket.timeout):
            pass
        time.sleep(1)

    if not health_ok:
        return False

    probe_url = base_url.rstrip("/") + "/completion"
    probe_payload = json.dumps({"prompt": "hi", "n_predict": 1}).encode("utf-8")
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(
                probe_url, data=probe_payload,
                headers={"Content-Type": "application/json"}, method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return True
        except urllib.error.HTTPError as e:
            if e.code == 503:
                time.sleep(2)
                continue
            return False
        except (urllib.error.URLError, ConnectionResetError, socket.timeout):
            time.sleep(1)
    return False


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def start_llama_server(binary, model_path, port, threads, ngl, ctx,
                        parallel=1, extra_args=None, log_path=None):
    cmd = [
        binary,
        "-m", model_path,
        "--port", str(port),
        "-t", str(threads),
        "-ngl", str(ngl),
        "-c", str(ctx),
        "--host", "127.0.0.1",
        "--parallel", str(parallel),
    ]
    if extra_args:
        cmd.extend(extra_args)
    print(f"  Launching: {' '.join(cmd)}")
    log_file = open(log_path, "w") if log_path else subprocess.DEVNULL
    if log_path:
        print(f"  Server log: {log_path}")
    proc = subprocess.Popen(
        cmd,
        stdout=log_file,
        stderr=subprocess.STDOUT if log_path else subprocess.DEVNULL,
        preexec_fn=os.setsid if hasattr(os, "setsid") else None,
    )
    return proc


def stop_llama_server(proc):
    if proc is None:
        return
    try:
        if hasattr(os, "killpg"):
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        else:
            proc.terminate()
        proc.wait(timeout=15)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

# ============================================================
# SERVER RUNNER (added -- HTTP/server mode)
#
# Same generate() interface as LlamaRunner, so every benchmark_*
# function downstream works identically regardless of backend.
# Uses the native /completion endpoint (not the OpenAI-compat
# /v1/chat/completions wrapper) because it returns structured
# "timings" with prompt_per_second / predicted_per_second, which
# map directly onto prefill_tps / decode_tps.
# ============================================================

class ServerRunner:

    def __init__(self, base_url, timeout=180):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def generate(self, prompt, predict=128):
        url = self.base_url + "/completion"
        payload = {
            "prompt": prompt,
            "n_predict": predict,
            "temperature": 0,
            "stream": False,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )

        t0 = time.time()
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                elapsed = time.time() - t0
                timings = body.get("timings", {})
                return {
                    "prompt": prompt,
                    "response": (body.get("content") or "").strip(),
                    "elapsed": elapsed,
                    "prefill_tps": round(timings.get("prompt_per_second", 0.0), 2),
                    "decode_tps": round(timings.get("predicted_per_second", 0.0), 2),
                    "prompt_tokens": timings.get("prompt_n", 0),
                    "raw_output": json.dumps(body),
                }
            except urllib.error.HTTPError as e:
                if e.code == 503 and attempt == 0:
                    print("    [debug] 503 (model still loading?), retrying in 5s...")
                    time.sleep(5)
                    t0 = time.time()
                    continue
                try:
                    err_body = e.read().decode("utf-8", errors="replace")[:300]
                except Exception:
                    err_body = "<no body>"
                print(f"    [debug] server error {e.code}: {err_body}")
                return {
                    "prompt": prompt, "response": "", "elapsed": time.time() - t0,
                    "prefill_tps": 0.0, "decode_tps": 0.0, "prompt_tokens": 0,
                    "raw_output": err_body,
                }
            except Exception as e:
                print(f"    [debug] request failed: {e}")
                return {
                    "prompt": prompt, "response": "", "elapsed": time.time() - t0,
                    "prefill_tps": 0.0, "decode_tps": 0.0, "prompt_tokens": 0,
                    "raw_output": str(e),
                }


def stream_text(chunk):
    choices = chunk.get("choices") or []
    delta = choices[0].get("delta", {}) if choices else {}
    return delta.get("reasoning_content") or delta.get("reasoning") or delta.get("content") or ""


class OpenAIChatRunner:

    def __init__(self, base_url, api_key, model, timeout=900):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def generate(self, prompt, predict=128):
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": predict,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        req = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        started = time.perf_counter()
        first_token_at = None
        pieces = []
        usage = {}
        raw_chunks = []
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    raw_chunks.append(chunk)
                    usage = chunk.get("usage") or usage
                    text = stream_text(chunk)
                    if text:
                        first_token_at = first_token_at or time.perf_counter()
                        pieces.append(text)
            ended = time.perf_counter()
            prompt_tokens = int(usage.get("prompt_tokens") or len(prompt.split()))
            completion_tokens = int(usage.get("completion_tokens") or len("".join(pieces).split()))
            ttft = (first_token_at or ended) - started
            decode_seconds = max(ended - (first_token_at or ended), 0)
            return {
                "prompt": prompt,
                "response": "".join(pieces).strip(),
                "elapsed": ended - started,
                "prefill_tps": round(prompt_tokens / ttft, 2) if ttft else 0.0,
                "decode_tps": round(max(completion_tokens - 1, 0) / decode_seconds, 2) if decode_seconds else 0.0,
                "prompt_tokens": prompt_tokens,
                "raw_output": json.dumps(raw_chunks),
            }
        except Exception as exc:
            return {
                "prompt": prompt, "response": "", "elapsed": time.perf_counter() - started,
                "prefill_tps": 0.0, "decode_tps": 0.0, "prompt_tokens": 0,
                "raw_output": str(exc),
            }

# ============================================================
# REPORT TEMPLATE
# ============================================================

def empty_report(model):
    return {
        "benchmark_profile": "edge",
        "benchmark_mode": "complete",
        "benchmark_version": "5.0",
        "model": os.path.basename(model),
        "path": model,
        "timestamp": datetime.now().isoformat(),
        "platform": {},
        "performance": {},
        "niah": {},
        "quality": {},
        "reasoning": {},
        "reasoning_advanced": {},
        "logic_advanced": {},
        "agent_advanced": {},
        "rag_advanced": {},
        "coding": {},
        "overall_score": 0
    }

# ============================================================
# RANDOM TEXT
# ============================================================

WORDS = [
    "artificial", "intelligence", "machine", "learning", "reasoning",
    "benchmark", "coding", "evaluation", "transformer", "token",
    "attention", "dataset", "memory", "context", "inference"
]

def random_text(tokens):
    return " ".join(random.choice(WORDS) for _ in range(tokens))

# ============================================================
# PERFORMANCE
# ============================================================

def benchmark_basic_tps(runner):
    print("Running Basic TPS...")
    r = runner.generate("Explain Artificial Intelligence.", predict=512)
    return {
        "prefill_tps": round(r["prefill_tps"], 2),
        "decode_tps": round(r["decode_tps"], 2),
        "ttft": round(r["elapsed"], 2)
    }

# ============================================================
# PREFILL
# ============================================================

def benchmark_prefill(runner):
    print("Running Prefill...")
    scores = []
    for size in [256, 1024, 2048]:
        r = runner.generate(random_text(size), predict=1)
        scores.append(r["prefill_tps"])
    return {
        "average": round(statistics.mean(scores), 2),
        "min": round(min(scores), 2),
        "max": round(max(scores), 2)
    }

# ============================================================
# DECODE
# ============================================================

def benchmark_decode(runner):
    print("Running Decode...")
    scores = []
    for _ in range(3):
        r = runner.generate("Write a long article about AI.", predict=512)
        scores.append(r["decode_tps"])
    return {
        "average": round(statistics.mean(scores), 2),
        "min": round(min(scores), 2),
        "max": round(max(scores), 2)
    }

# ============================================================
# LATENCY
# ============================================================

def benchmark_latency(runner):
    print("Running Latency...")
    prompts = ["Hello", "What is AI?", "Explain ML", "Write Python code"]
    scores = []
    for p in prompts:
        r = runner.generate(p, predict=64)
        scores.append(r["elapsed"])
    return {
        "average": round(statistics.mean(scores), 2),
        "min": round(min(scores), 2),
        "max": round(max(scores), 2)
    }

# ============================================================
# NIAH
# ============================================================

def build_niah_prompt(context_tokens, needle):
    before = random_text(context_tokens // 2)
    after = random_text(context_tokens // 2)
    return (
        f"{before}\n\n"
        f"SECRET_CODE:\n{needle}\n\n"
        f"{after}\n\n"
        f"What is the SECRET_CODE?\n\nAnswer only with the code."
    )

def benchmark_niah(runner, contexts):
    print("Running NIAH...")
    results = {}
    for ctx in contexts:
        needle = f"SECRET-{random.randint(100000, 999999)}"
        prompt = build_niah_prompt(ctx, needle)
        r = runner.generate(prompt, predict=32)
        found = needle.lower() in r["response"].lower()
        results[str(ctx)] = {
            "needle": needle,
            "found": found,
            "score": 100 if found else 0
        }
    return results

# ============================================================
# PERFORMANCE SUITE
# ============================================================

def run_performance_suite(runner, contexts):
    return {
        "basic": benchmark_basic_tps(runner),
        "prefill": benchmark_prefill(runner),
        "decode": benchmark_decode(runner),
        "latency": benchmark_latency(runner),
        "niah": benchmark_niah(runner, contexts)
    }

# ============================================================
# HELPERS
# ============================================================

def extract_number(text):
    nums = re.findall(r"-?\d+(?:\.\d+)?", text)
    if not nums:
        return None
    return nums[-1]

def extract_python_code(text):
    block = re.search(r"```python(.*?)```", text, re.S | re.I)
    if block:
        return block.group(1)
    return text

# ============================================================
# REASONING TESTS (original)
# ============================================================

REASONING_TESTS = [
    {"question": "John has 12 apples and buys 15 more. How many apples?", "answer": "27"},
    {"question": "25 + 75", "answer": "100"},
    {"question": "90 / 3", "answer": "30"},
    {"question": "A train travels 60 km in 2 hours. What is its speed?", "answer": "30"},
    {"question": "A farmer has 15 cows and sells 5. How many remain?", "answer": "10"},
    {"question": "What is 12 * 12?", "answer": "144"},
    {"question": "A rectangle has width 5 and height 8. Area?", "answer": "40"},
    {"question": "If Alice is 20 and Bob is 5 years older, how old is Bob?", "answer": "25"},
    {"question": "100 minus 37", "answer": "63"},
    {"question": "What is the next number: 2 4 8 16 ?", "answer": "32"}
]

# ============================================================
# LOGIC TESTS
# ============================================================

LOGIC_TESTS = [
    {
        "question": "All dogs are animals. Rover is a dog. Is Rover an animal? Answer yes or no.",
        "answer": "yes"
    },
    {
        "question": "If it is raining then the ground is wet. The ground is not wet. Is it raining? Answer yes or no.",
        "answer": "no"
    },
    {"question": "True AND False = ?", "answer": "false"},
    {"question": "False OR True = ?", "answer": "true"}
]

# ============================================================
# REASONING BENCHMARK (original)
# ============================================================

def benchmark_reasoning(runner):
    print("Running Reasoning Suite...")
    passed = 0
    details = []
    for item in REASONING_TESTS:
        prompt = (
            "Solve carefully.\n\n"
            "Return only final answer.\n\n"
            f"{item['question']}"
        )
        r = runner.generate(prompt, predict=128)
        prediction = extract_number(r["response"])
        success = (prediction == item["answer"])
        if success:
            passed += 1
        details.append({
            "question": item["question"],
            "expected": item["answer"],
            "predicted": prediction,
            "passed": success
        })
    accuracy = round(passed / len(REASONING_TESTS) * 100, 2)
    return {"passed": passed, "total": len(REASONING_TESTS), "accuracy": accuracy, "details": details}

# ============================================================
# LOGIC BENCHMARK
# ============================================================

def benchmark_logic(runner):
    print("Running Logic Suite...")
    passed = 0
    details = []
    for item in LOGIC_TESTS:
        r = runner.generate(item["question"], predict=64)
        response = r["response"].lower().strip()
        success = item["answer"] in response
        if success:
            passed += 1
        details.append({
            "question": item["question"],
            "expected": item["answer"],
            "response": response,
            "passed": success
        })
    accuracy = round(passed / len(LOGIC_TESTS) * 100, 2)
    return {"passed": passed, "total": len(LOGIC_TESTS), "accuracy": accuracy, "details": details}

# ============================================================
# LOGIC TESTS ADVANCED
#
# 20 categorized cases across 8 logic categories: propositional
# logic, conditional reasoning (modus ponens/tollens), syllogism,
# quantifiers, logical equivalence (De Morgan's etc.), negation,
# deductive puzzles, and truth-teller/liar problems.
#
# Same CoT-friendly approach as REASONING_TESTS_ADVANCED: the
# model gets room to reason, then must close with a
# "FINAL ANSWER:" line, scored via extract_final_answer_segment().
# This is the default logic suite now; the original 4-item
# LOGIC_TESTS/benchmark_logic() above is kept for backward
# compatibility, opt-in via --include-basic-logic.
# ============================================================

# ============================================================
# Shared CoT helpers (used by both LOGIC_TESTS_ADVANCED below and
# REASONING_TESTS_ADVANCED further down -- defined here so both
# sections can use them regardless of file order)
# ============================================================

ANSWER_SUFFIX = ("\n\nShow your reasoning briefly, then on the final line "
                  "write your answer exactly as:\nFINAL ANSWER: <answer>")

def extract_final_answer_segment(text):
    """
    Pull out the text after the LAST 'FINAL ANSWER:' occurrence.
    Falls back to the full response if the marker is absent (model
    ignored the instruction, or got cut off by max_tokens).
    """
    matches = list(re.finditer(r"final\s*answer\s*:?\s*", text, flags=re.IGNORECASE))
    if matches:
        last = matches[-1]
        return text[last.end():].strip()
    return text

LOGIC_TESTS_ADVANCED = [
    # --- propositional logic (easy) ---
    {
        "id": "L001", "category": "propositional_logic", "difficulty": "easy",
        "question": "Evaluate this expression: True AND False. What is the result (True or False)?" + ANSWER_SUFFIX,
        "expected": "false", "match": "contains_keyword"
    },
    {
        "id": "L002", "category": "propositional_logic", "difficulty": "easy",
        "question": "Evaluate this expression: (True OR False) AND (NOT False). What is the result (True or False)?" + ANSWER_SUFFIX,
        "expected": "true", "match": "contains_keyword"
    },
    {
        "id": "L003", "category": "propositional_logic", "difficulty": "medium",
        "question": "Evaluate this expression: NOT (True AND False) OR (False AND True). What is the result (True or False)?" + ANSWER_SUFFIX,
        "expected": "true", "match": "contains_keyword"
    },

    # --- conditional reasoning: modus ponens / modus tollens ---
    {
        "id": "L004", "category": "conditional_reasoning", "difficulty": "easy",
        "question": "If it rains, the game is cancelled. It is raining. Is the game cancelled (yes or no)?" + ANSWER_SUFFIX,
        "expected": "yes", "match": "contains_keyword"
    },
    {
        "id": "L005", "category": "conditional_reasoning", "difficulty": "medium",
        "question": "If it rains, the game is cancelled. The game was not cancelled. Was it raining (yes or no)? Use modus tollens." + ANSWER_SUFFIX,
        "expected": "no", "match": "contains_keyword"
    },
    {
        "id": "L006", "category": "conditional_reasoning", "difficulty": "medium",
        "question": "If it rains, the game is cancelled. The game was cancelled. Can we conclude it definitely rained (yes or no)? (Consider: could the game have been cancelled for another reason?)" + ANSWER_SUFFIX,
        "expected": "no", "match": "contains_keyword"
    },
    {
        "id": "L007", "category": "conditional_reasoning", "difficulty": "hard",
        "question": "If a number is divisible by 4, it is divisible by 2. 15 is not divisible by 2. Is 15 divisible by 4 (yes or no)?" + ANSWER_SUFFIX,
        "expected": "no", "match": "contains_keyword"
    },

    # --- syllogisms ---
    {
        "id": "L008", "category": "syllogism", "difficulty": "easy",
        "question": "All cats are mammals. All mammals are animals. Is a cat definitely an animal (yes or no)?" + ANSWER_SUFFIX,
        "expected": "yes", "match": "contains_keyword"
    },
    {
        "id": "L009", "category": "syllogism", "difficulty": "medium",
        "question": "All squares are rectangles. Some rectangles are not red. Can we conclude that some squares are not red (yes or no)? (Careful: the non-red rectangles might not include any squares.)" + ANSWER_SUFFIX,
        "expected": "no", "match": "contains_keyword"
    },
    {
        "id": "L010", "category": "syllogism", "difficulty": "hard",
        "question": "No reptiles are warm-blooded. All snakes are reptiles. Are snakes warm-blooded (yes or no)?" + ANSWER_SUFFIX,
        "expected": "no", "match": "contains_keyword"
    },

    # --- quantifiers ---
    {
        "id": "L011", "category": "quantifiers", "difficulty": "easy",
        "question": "Some birds can fly. Penguins are birds. Can we conclude that penguins can fly (yes or no)? (Careful: 'some' does not mean 'all'.)" + ANSWER_SUFFIX,
        "expected": "no", "match": "contains_keyword"
    },
    {
        "id": "L012", "category": "quantifiers", "difficulty": "medium",
        "question": "Every student in the class passed the exam. Maria is a student in the class. Did Maria pass the exam (yes or no)?" + ANSWER_SUFFIX,
        "expected": "yes", "match": "contains_keyword"
    },
    {
        "id": "L013", "category": "quantifiers", "difficulty": "hard",
        "question": "No student failed the exam. Tom did not pass the exam. Is this situation possible (yes or no)? (Consider: could a student neither pass nor fail, e.g. incomplete?)" + ANSWER_SUFFIX,
        "expected": "no", "match": "contains_keyword"
    },

    # --- logical equivalence / De Morgan's ---
    {
        "id": "L014", "category": "logical_equivalence", "difficulty": "medium",
        "question": "By De Morgan's law, NOT (A AND B) is logically equivalent to which of these: '(NOT A) OR (NOT B)' or '(NOT A) AND (NOT B)'? Answer with just the equivalent expression." + ANSWER_SUFFIX,
        "expected": "(not a) or (not b)", "match": "contains_keyword"
    },
    {
        "id": "L015", "category": "logical_equivalence", "difficulty": "hard",
        "question": "Is the statement 'If P then Q' logically equivalent to 'If NOT Q then NOT P' (the contrapositive)? Answer yes or no." + ANSWER_SUFFIX,
        "expected": "yes", "match": "contains_keyword"
    },

    # --- negation ---
    {
        "id": "L016", "category": "negation", "difficulty": "easy",
        "question": "What is the negation of the statement 'All dogs bark'? Choose one: 'No dogs bark' or 'Some dogs do not bark'. Answer with just the correct phrase." + ANSWER_SUFFIX,
        "expected": "some dogs do not bark", "match": "contains_keyword"
    },
    {
        "id": "L017", "category": "negation", "difficulty": "medium",
        "question": "What is the negation of 'It is raining AND it is cold'? Choose one: 'It is not raining AND it is not cold' or 'It is not raining OR it is not cold'. Answer with just the correct phrase." + ANSWER_SUFFIX,
        "expected": "it is not raining or it is not cold", "match": "contains_keyword"
    },

    # --- deductive puzzles ---
    {
        "id": "L018", "category": "deductive_puzzle", "difficulty": "hard",
        "question": "Three boxes are labeled 'Apples', 'Oranges', and 'Apples and Oranges'. All three labels are wrong. You may pick one fruit from one box to look at, then you must correctly label all three boxes. Which box should you pick from -- 'Apples', 'Oranges', or 'Apples and Oranges'?" + ANSWER_SUFFIX,
        "expected": "apples and oranges", "match": "contains_keyword"
    },
    {
        "id": "L019", "category": "deductive_puzzle", "difficulty": "hard",
        "question": "A, B, and C are suspects. Exactly one of them is guilty. A says 'B is guilty.' B says 'C is guilty.' C says 'I am not guilty.' If exactly one of the three statements is true, who is guilty -- A, B, or C?" + ANSWER_SUFFIX,
        "expected": "a", "match": "contains_keyword"
    },

    # --- truth-teller / liar ---
    {
        "id": "L020", "category": "truth_teller_liar", "difficulty": "hard",
        "question": "On an island, knights always tell the truth and knaves always lie. You meet a person who says 'I am a knave.' Is this possible for either a knight or a knave to say? Answer 'neither' if it's a paradox, or 'knight' or 'knave' if one of them could say it." + ANSWER_SUFFIX,
        "expected": "neither", "match": "contains_keyword"
    },
]

def score_logic_advanced(case, response_text):
    """Reuses the same FINAL ANSWER extraction logic as the reasoning suite."""
    segment = extract_final_answer_segment(response_text)
    segment_lower = segment.lower()
    target = case["expected"].lower()
    correct = target in segment_lower
    if not correct:
        correct = target in response_text[-150:].lower()
    return correct

def benchmark_logic_advanced(runner):
    print(f"Running Advanced Logic Suite ({len(LOGIC_TESTS_ADVANCED)} cases)...")
    passed = 0
    details = []
    category_totals = {}
    category_passed = {}

    for item in LOGIC_TESTS_ADVANCED:
        predict = 512 if item["difficulty"] == "hard" else 384
        r = runner.generate(item["question"], predict=predict)
        success = score_logic_advanced(item, r["response"])

        category = item["category"]
        category_totals[category] = category_totals.get(category, 0) + 1
        if success:
            passed += 1
            category_passed[category] = category_passed.get(category, 0) + 1

        details.append({
            "id": item["id"],
            "category": category,
            "difficulty": item["difficulty"],
            "expected": item["expected"],
            "response": r["response"],
            "passed": success,
            "decode_tps": r["decode_tps"],
            "elapsed": round(r["elapsed"], 2)
        })

    breakdown = {
        cat: {
            "passed": category_passed.get(cat, 0),
            "total": total,
            "accuracy": round(100 * category_passed.get(cat, 0) / total, 2)
        }
        for cat, total in category_totals.items()
    }

    accuracy = round(passed / len(LOGIC_TESTS_ADVANCED) * 100, 2)
    return {
        "passed": passed,
        "total": len(LOGIC_TESTS_ADVANCED),
        "accuracy": accuracy,
        "breakdown": breakdown,
        "details": details
    }

# ============================================================
# REASONING ADVANCED TESTS
#
# 10 categorized cases covering arithmetic, deduction, rate
# problems, syllogism, combinatorics, common sense, age
# problems, multi-hop QA, self-referential logic, probability.
#
# Uses a chain-of-thought-friendly prompt (ANSWER_SUFFIX) instead
# of "answer with just the number" -- testing on gemma-2-2b-it on
# CM3588 showed forcing a bare answer collapses small-model
# accuracy (they can't do multi-step math without externalizing
# steps). Scoring extracts from after the "FINAL ANSWER:" marker,
# with a tail-of-response fallback if the model ignores the
# format or gets cut off by max tokens.
# ============================================================

ANSWER_SUFFIX_NOTE = "(ANSWER_SUFFIX is defined earlier in the file, above LOGIC_TESTS_ADVANCED, so both logic and reasoning advanced suites can share it)"

REASONING_TESTS_ADVANCED = [
    {
        "id": "R001", "category": "arithmetic_multistep", "difficulty": "easy",
        "question": "A store has 120 apples. They sell 45 in the morning and 38 in the afternoon. Then a supplier delivers 60 more apples. How many apples does the store have at the end of the day?" + ANSWER_SUFFIX,
        "expected": "97", "match": "contains_number"
    },
    {
        "id": "R002", "category": "logic_deduction", "difficulty": "medium",
        "question": "Five friends (Alice, Ben, Carol, David, Emma) are sitting in a row. Alice is not at either end. Ben is immediately to the left of Carol. David is at the right end. Emma is not next to Ben. Who is sitting at the left end?" + ANSWER_SUFFIX,
        "expected": "ben", "match": "contains_keyword"
    },
    {
        "id": "R003", "category": "word_problem_rate", "difficulty": "medium",
        "question": "Pipe A fills a tank in 6 hours. Pipe B fills the same tank in 4 hours. If both pipes are opened together, how long will it take to fill the tank (in hours, as a decimal)?" + ANSWER_SUFFIX,
        "expected": "2.4", "match": "contains_number"
    },
    {
        "id": "R004", "category": "syllogism", "difficulty": "easy",
        "question": "All engineers at the company use Linux. Priya is an engineer at the company. Does Priya use Linux (yes or no)?" + ANSWER_SUFFIX,
        "expected": "yes", "match": "contains_keyword"
    },
    {
        "id": "R005", "category": "combinatorics", "difficulty": "hard",
        "question": "In how many ways can 3 identical red balls and 2 identical blue balls be arranged in a row?" + ANSWER_SUFFIX,
        "expected": "10", "match": "contains_number"
    },
    {
        "id": "R006", "category": "common_sense", "difficulty": "easy",
        "question": "If it takes 5 machines 5 minutes to make 5 widgets, how long (in minutes) would it take 100 machines to make 100 widgets?" + ANSWER_SUFFIX,
        "expected": "5", "match": "contains_number"
    },
    {
        "id": "R007", "category": "age_problem", "difficulty": "medium",
        "question": "In 10 years, Maria will be twice as old as she was 5 years ago. How old is Maria now?" + ANSWER_SUFFIX,
        "expected": "20", "match": "contains_number"
    },
    {
        "id": "R008", "category": "multi_hop_qa", "difficulty": "hard",
        "question": "A train leaves City A at 60 km/h heading to City B, 300 km away. Another train leaves City B at the same time heading to City A at 90 km/h on the same track. How long after departure (in hours) do they meet?" + ANSWER_SUFFIX,
        "expected": "2", "match": "contains_number"
    },
    {
        "id": "R009", "category": "self_referential_logic", "difficulty": "hard",
        "question": "A man says, 'I always lie on Mondays, Tuesdays, and Wednesdays, and I always tell the truth on other days.' Today he says, 'Tomorrow I will lie.' What day is it today?" + ANSWER_SUFFIX,
        "expected": "wednesday", "match": "contains_keyword"
    },
    {
        "id": "R010", "category": "probability", "difficulty": "medium",
        "question": "A bag has 4 red, 3 green, and 5 blue marbles. If you draw 2 marbles without replacement, what is the probability both are red (as a simplified fraction a/b)?" + ANSWER_SUFFIX,
        "expected": "1/11", "match": "contains_keyword"
    },
]

def extract_numbers_advanced(text):
    return re.findall(r"-?\d+\.?\d*", text)

def is_float(s):
    try:
        float(s)
        return True
    except ValueError:
        return False

def score_reasoning_advanced(case, response_text):
    segment = extract_final_answer_segment(response_text)
    segment_lower = segment.lower()

    if case["match"] == "contains_number":
        nums = extract_numbers_advanced(segment)
        target = case["expected"]
        correct = any(
            n == target or (is_float(n) and is_float(target) and abs(float(n) - float(target)) < 1e-6)
            for n in nums
        )
        if not correct and segment is not response_text:
            nums_full = extract_numbers_advanced(response_text[-80:])
            correct = any(
                n == target or (is_float(n) and is_float(target) and abs(float(n) - float(target)) < 1e-6)
                for n in nums_full
            )
    elif case["match"] == "contains_keyword":
        target = case["expected"].lower()
        correct = target in segment_lower
        if not correct:
            correct = target in response_text[-120:].lower()
    else:
        correct = False
    return correct

# ============================================================
# REASONING ADVANCED BENCHMARK
# ============================================================

def benchmark_reasoning_advanced(runner):
    print("Running Advanced Reasoning Suite...")
    passed = 0
    details = []
    for item in REASONING_TESTS_ADVANCED:
        # hard/multi-hop cases get more room to reason; small models
        # (2-3B) especially need this or they truncate mid-derivation
        predict = 512 if item["difficulty"] in ("hard", "medium") else 384
        r = runner.generate(item["question"], predict=predict)
        success = score_reasoning_advanced(item, r["response"])
        if success:
            passed += 1
        details.append({
            "id": item["id"],
            "category": item["category"],
            "difficulty": item["difficulty"],
            "expected": item["expected"],
            "response": r["response"],
            "passed": success,
            "decode_tps": r["decode_tps"],
            "elapsed": round(r["elapsed"], 2)
        })
    accuracy = round(passed / len(REASONING_TESTS_ADVANCED) * 100, 2)
    return {
        "passed": passed,
        "total": len(REASONING_TESTS_ADVANCED),
        "accuracy": accuracy,
        "details": details
    }

# ============================================================
# HUMANEVAL LITE
#
# 25 cases across 8 categories, each with a difficulty tier.
# Kept in the same (prompt, entry, tests) format as the original
# 3-case version so run_code_tests() and benchmark_humaneval()
# below work unchanged -- category/difficulty are extra metadata
# used only for the breakdown reporting.
# ============================================================

HUMANEVAL_LITE = [
    # --- arithmetic / basic (easy) ---
    {
        "category": "arithmetic", "difficulty": "easy",
        "prompt": "Write a Python function add(a, b) that returns the sum of two numbers.",
        "entry": "add",
        "tests": [("add(1,2)", 3), ("add(10,5)", 15), ("add(-3,3)", 0)]
    },
    {
        "category": "arithmetic", "difficulty": "easy",
        "prompt": "Write a Python function factorial(n) that returns n! (the factorial of n). factorial(0) should return 1.",
        "entry": "factorial",
        "tests": [("factorial(5)", 120), ("factorial(1)", 1), ("factorial(0)", 1)]
    },
    {
        "category": "arithmetic", "difficulty": "easy",
        "prompt": "Write a Python function is_prime(n) that returns True if n is a prime number, False otherwise.",
        "entry": "is_prime",
        "tests": [("is_prime(7)", True), ("is_prime(1)", False), ("is_prime(4)", False), ("is_prime(2)", True)]
    },
    {
        "category": "arithmetic", "difficulty": "medium",
        "prompt": "Write a Python function gcd(a, b) that returns the greatest common divisor of two positive integers using the Euclidean algorithm.",
        "entry": "gcd",
        "tests": [("gcd(48,18)", 6), ("gcd(17,5)", 1), ("gcd(100,25)", 25)]
    },

    # --- recursion (easy/medium) ---
    {
        "category": "recursion", "difficulty": "easy",
        "prompt": "Write a Python function fibonacci(n) that returns the nth Fibonacci number, 0-indexed, where fibonacci(0)=0 and fibonacci(1)=1.",
        "entry": "fibonacci",
        "tests": [("fibonacci(5)", 5), ("fibonacci(8)", 21), ("fibonacci(0)", 0), ("fibonacci(1)", 1)]
    },
    {
        "category": "recursion", "difficulty": "medium",
        "prompt": "Write a Python function sum_digits(n) that recursively returns the sum of the digits of a non-negative integer n.",
        "entry": "sum_digits",
        "tests": [("sum_digits(1234)", 10), ("sum_digits(0)", 0), ("sum_digits(9)", 9)]
    },
    {
        "category": "recursion", "difficulty": "medium",
        "prompt": "Write a Python function power(base, exp) that recursively computes base raised to a non-negative integer exponent.",
        "entry": "power",
        "tests": [("power(2,10)", 1024), ("power(5,0)", 1), ("power(3,3)", 27)]
    },

    # --- strings (easy/medium) ---
    {
        "category": "strings", "difficulty": "easy",
        "prompt": "Write a Python function is_palindrome(s) that returns True if the string s reads the same forwards and backwards (case-sensitive, no trimming needed), False otherwise.",
        "entry": "is_palindrome",
        "tests": [("is_palindrome('racecar')", True), ("is_palindrome('hello')", False), ("is_palindrome('a')", True)]
    },
    {
        "category": "strings", "difficulty": "easy",
        "prompt": "Write a Python function count_vowels(s) that returns the number of vowels (a, e, i, o, u, case-insensitive) in the string s.",
        "entry": "count_vowels",
        "tests": [("count_vowels('Hello World')", 3), ("count_vowels('xyz')", 0), ("count_vowels('AEIOU')", 5)]
    },
    {
        "category": "strings", "difficulty": "medium",
        "prompt": "Write a Python function reverse_words(s) that takes a string of space-separated words and returns a new string with the words in reverse order (but each word itself unchanged). E.g. 'the sky is blue' -> 'blue is sky the'.",
        "entry": "reverse_words",
        "tests": [("reverse_words('the sky is blue')", "blue is sky the"), ("reverse_words('hello world')", "world hello")]
    },
    {
        "category": "strings", "difficulty": "medium",
        "prompt": "Write a Python function is_anagram(a, b) that returns True if strings a and b are anagrams of each other (same letters, same counts, ignoring case), False otherwise.",
        "entry": "is_anagram",
        "tests": [("is_anagram('listen','silent')", True), ("is_anagram('hello','world')", False), ("is_anagram('Dormitory','DirtyRoom')", True)]
    },
    {
        "category": "strings", "difficulty": "hard",
        "prompt": "Write a Python function longest_common_prefix(strs) that takes a list of strings and returns the longest common prefix string among them. If there is no common prefix, return an empty string.",
        "entry": "longest_common_prefix",
        "tests": [
            ("longest_common_prefix(['flower','flow','flight'])", "fl"),
            ("longest_common_prefix(['dog','racecar','car'])", ""),
            ("longest_common_prefix(['interspecies','interstellar','interstate'])", "inters")
        ]
    },

    # --- lists / arrays (easy/medium/hard) ---
    {
        "category": "lists", "difficulty": "easy",
        "prompt": "Write a Python function find_max(nums) that returns the maximum value in a non-empty list of numbers, without using the built-in max() function.",
        "entry": "find_max",
        "tests": [("find_max([3,1,4,1,5,9,2,6])", 9), ("find_max([-5,-2,-9])", -2), ("find_max([7])", 7)]
    },
    {
        "category": "lists", "difficulty": "easy",
        "prompt": "Write a Python function remove_duplicates(nums) that returns a new list with duplicate values removed, preserving the original order of first occurrence.",
        "entry": "remove_duplicates",
        "tests": [("remove_duplicates([1,2,2,3,1,4])", [1,2,3,4]), ("remove_duplicates([])", []), ("remove_duplicates([5,5,5])", [5])]
    },
    {
        "category": "lists", "difficulty": "medium",
        "prompt": "Write a Python function two_sum(nums, target) that returns a list of the two indices [i, j] (i < j) such that nums[i] + nums[j] == target. Assume exactly one solution exists.",
        "entry": "two_sum",
        "tests": [("two_sum([2,7,11,15],9)", [0,1]), ("two_sum([3,2,4],6)", [1,2]), ("two_sum([3,3],6)", [0,1])]
    },
    {
        "category": "lists", "difficulty": "medium",
        "prompt": "Write a Python function flatten(nested) that takes a list which may contain nested lists (arbitrarily deep) and returns a single flat list of all the non-list elements, in order.",
        "entry": "flatten",
        "tests": [
            ("flatten([1,[2,3],[4,[5,6]],7])", [1,2,3,4,5,6,7]),
            ("flatten([])", []),
            ("flatten([[1,[2,[3,[4]]]]])", [1,2,3,4])
        ]
    },
    {
        "category": "lists", "difficulty": "hard",
        "prompt": "Write a Python function merge_intervals(intervals) that takes a list of [start, end] intervals (as lists), merges all overlapping intervals, and returns the merged list sorted by start. Touching intervals (e.g. [1,3] and [3,5]) should also be merged.",
        "entry": "merge_intervals",
        "tests": [
            ("merge_intervals([[1,3],[2,6],[8,10],[15,18]])", [[1,6],[8,10],[15,18]]),
            ("merge_intervals([[1,4],[4,5]])", [[1,5]]),
            ("merge_intervals([[1,4],[0,4]])", [[0,4]])
        ]
    },

    # --- sorting / searching (medium/hard) ---
    {
        "category": "algorithms", "difficulty": "medium",
        "prompt": "Write a Python function binary_search(sorted_list, target) that returns the index of target in sorted_list (ascending order) using binary search, or -1 if not found.",
        "entry": "binary_search",
        "tests": [("binary_search([1,3,5,7,9,11],7)", 3), ("binary_search([1,3,5,7,9,11],4)", -1), ("binary_search([1],1)", 0)]
    },
    {
        "category": "algorithms", "difficulty": "medium",
        "prompt": "Write a Python function bubble_sort(nums) that returns a new list with the numbers sorted in ascending order using the bubble sort algorithm (do not use sorted() or .sort()).",
        "entry": "bubble_sort",
        "tests": [("bubble_sort([5,2,9,1,5,6])", [1,2,5,5,6,9]), ("bubble_sort([])", []), ("bubble_sort([1])", [1])]
    },
    {
        "category": "algorithms", "difficulty": "hard",
        "prompt": "Write a Python function quicksort(nums) that returns a new list with the numbers sorted in ascending order using the quicksort algorithm.",
        "entry": "quicksort",
        "tests": [("quicksort([3,6,8,10,1,2,1])", [1,1,2,3,6,8,10]), ("quicksort([])", []), ("quicksort([5,4,3,2,1])", [1,2,3,4,5])]
    },

    # --- data structures (medium/hard) ---
    {
        "category": "data_structures", "difficulty": "medium",
        "prompt": "Write a Python function is_valid_parens(s) that takes a string of only '(', ')', '{', '}', '[', ']' characters and returns True if the brackets are balanced and properly nested, False otherwise. Use a stack.",
        "entry": "is_valid_parens",
        "tests": [("is_valid_parens('()[]{}')", True), ("is_valid_parens('(]')", False), ("is_valid_parens('([{}])')", True), ("is_valid_parens('(')", False)]
    },
    {
        "category": "data_structures", "difficulty": "medium",
        "prompt": "Write a Python function word_frequency(text) that returns a dictionary mapping each lowercase word in the string text to how many times it appears. Split on whitespace and lowercase all words; ignore punctuation is not required.",
        "entry": "word_frequency",
        "tests": [
            ("word_frequency('the cat sat on the mat')", {"the": 2, "cat": 1, "sat": 1, "on": 1, "mat": 1}),
            ("word_frequency('a a a')", {"a": 3})
        ]
    },
    {
        "category": "data_structures", "difficulty": "hard",
        "prompt": "Write a Python function group_anagrams(words) that takes a list of strings and groups the anagrams together, returning a list of lists. Each inner list should be sorted alphabetically, and the outer list should be sorted by the sorted-key of each group. E.g. group_anagrams(['eat','tea','tan','ate','nat','bat']) groups eat/tea/ate together, tan/nat together, and bat alone.",
        "entry": "group_anagrams",
        "tests": [
            ("sorted([sorted(g) for g in group_anagrams(['eat','tea','tan','ate','nat','bat'])])",
             [['bat'], ['nat', 'tan'], ['ate', 'eat', 'tea']])
        ]
    },

    # --- edge cases / robustness (medium) ---
    {
        "category": "edge_cases", "difficulty": "medium",
        "prompt": "Write a Python function safe_divide(a, b) that returns a / b, but returns None instead of raising an exception if b is 0.",
        "entry": "safe_divide",
        "tests": [("safe_divide(10,2)", 5.0), ("safe_divide(5,0)", None), ("safe_divide(-9,3)", -3.0)]
    },
    {
        "category": "edge_cases", "difficulty": "medium",
        "prompt": "Write a Python function chunk_list(nums, size) that splits the list nums into consecutive sublists of length size (the last chunk may be shorter), returned as a list of lists.",
        "entry": "chunk_list",
        "tests": [
            ("chunk_list([1,2,3,4,5],2)", [[1,2],[3,4],[5]]),
            ("chunk_list([1,2,3,4],4)", [[1,2,3,4]]),
            ("chunk_list([],3)", [])
        ]
    },
    {
        "category": "algorithms", "difficulty": "hard",
        "prompt": "Write a Python function longest_increasing_subsequence(nums) that returns the length (an integer) of the longest strictly increasing subsequence in the list nums.",
        "entry": "longest_increasing_subsequence",
        "tests": [
            ("longest_increasing_subsequence([10,9,2,5,3,7,101,18])", 4),
            ("longest_increasing_subsequence([0,1,0,3,2,3])", 4),
            ("longest_increasing_subsequence([7,7,7,7])", 1)
        ]
    },
]

SAFE_GLOBALS = {"__builtins__": __builtins__, "math": math}

# ============================================================
# CODE EXECUTION
# ============================================================

def run_code_tests(code, entry, tests):
    try:
        namespace = {}
        exec(code, SAFE_GLOBALS, namespace)
        if entry not in namespace:
            return False
        for expr, expected in tests:
            result = eval(expr, SAFE_GLOBALS, namespace)
            if result != expected:
                return False
        return True
    except Exception:
        return False

# ============================================================
# CODING BENCHMARK
# ============================================================

def benchmark_humaneval(runner):
    print(f"Running HumanEval Lite ({len(HUMANEVAL_LITE)} cases)...")
    passed = 0
    details = []
    category_totals = {}
    category_passed = {}

    for item in HUMANEVAL_LITE:
        category = item.get("category", "uncategorized")
        difficulty = item.get("difficulty", "unknown")
        # harder/longer-solution problems get more generation room
        predict = 512 if difficulty in ("hard",) else 320

        prompt = f"Write ONLY valid Python code. No explanation, no markdown outside the code block.\n\n{item['prompt']}"
        r = runner.generate(prompt, predict=predict)
        code = extract_python_code(r["response"])
        success = run_code_tests(code, item["entry"], item["tests"])

        category_totals[category] = category_totals.get(category, 0) + 1
        if success:
            passed += 1
            category_passed[category] = category_passed.get(category, 0) + 1

        details.append({
            "prompt": item["prompt"],
            "category": category,
            "difficulty": difficulty,
            "passed": success
        })

    breakdown = {
        cat: {
            "passed": category_passed.get(cat, 0),
            "total": total,
            "accuracy": round(100 * category_passed.get(cat, 0) / total, 2)
        }
        for cat, total in category_totals.items()
    }

    return {
        "passed": passed,
        "total": len(HUMANEVAL_LITE),
        "pass_at_1": round(passed / len(HUMANEVAL_LITE) * 100, 2),
        "breakdown": breakdown,
        "details": details
    }

# ============================================================
# AGENT TASKS ADVANCED
#
# 10 categorized cases testing objectively checkable agentic
# behaviors: structured output (JSON), exact-count/format
# compliance, constraint following (word limits, no-bullets),
# multi-step plan structure, sequential ordering, and honest
# refusal when asked to perform a real-world action the model
# cannot actually take (tests agentic honesty rather than just
# generating plausible-sounding text). Each case has its own
# checker function instead of the old heuristic line-count/bullet
# scoring, which rewarded verbosity more than task compliance.
# ============================================================

def check_json_object(text, required_keys):
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return False
    try:
        obj = json.loads(match.group(0))
    except Exception:
        return False
    if not isinstance(obj, dict):
        return False
    return all(k in obj for k in required_keys)

def check_json_array_values(text, expected_values):
    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        return False
    try:
        arr = json.loads(match.group(0))
    except Exception:
        return False
    return list(arr) == list(expected_values)

def check_exact_numbered_steps(text, count):
    numbered = re.findall(r"(?m)^\s*(\d+)[.)]\s+\S", text)
    return len(numbered) == count

def check_word_count_max(text, max_words):
    words = text.strip().split()
    return 0 < len(words) <= max_words

def check_ordering(text, ordered_keywords):
    positions = []
    lower = text.lower()
    for kw in ordered_keywords:
        idx = lower.find(kw.lower())
        if idx == -1:
            return False
        positions.append(idx)
    return positions == sorted(positions)

def check_headers_present(text, headers):
    lower = text.lower()
    return all(h.lower() in lower for h in headers)

def check_no_bullet_chars(text):
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("-") or stripped.startswith("*"):
            return False
    return True

def check_contains_any(text, keywords):
    lower = text.lower()
    return any(kw.lower() in lower for kw in keywords)

def check_csv_no_spaces(text, expected_items):
    for line in text.splitlines():
        stripped = line.strip()
        if "," in stripped and " " not in stripped.replace(", ", ","):
            items = [x.strip().lower() for x in stripped.split(",")]
            if set(items) == set(e.lower() for e in expected_items):
                return True
    return False

AGENT_CHECKERS = {
    "json_object": check_json_object,
    "json_array": check_json_array_values,
    "numbered_steps": check_exact_numbered_steps,
    "word_count_max": check_word_count_max,
    "ordering": check_ordering,
    "headers": check_headers_present,
    "no_bullets": check_no_bullet_chars,
    "contains_any": check_contains_any,
    "csv_no_spaces": check_csv_no_spaces,
}

AGENT_TASKS_ADVANCED = [
    {
        "id": "A001", "category": "structured_output", "difficulty": "easy",
        "task": "Return ONLY a JSON object (no other text) describing a fictional person with keys 'name', 'age', and 'city'. Example shape: {\"name\": \"...\", \"age\": ..., \"city\": \"...\"}",
        "checker": "json_object", "checker_args": [["name", "age", "city"]], "predict": 128
    },
    {
        "id": "A002", "category": "structured_output", "difficulty": "medium",
        "task": "Return ONLY a JSON array (no other text) containing the first 3 prime numbers as integers, e.g. [2, 3, 5].",
        "checker": "json_array", "checker_args": [[2, 3, 5]], "predict": 64
    },
    {
        "id": "A003", "category": "format_compliance", "difficulty": "easy",
        "task": "List exactly 5 steps to make a cup of tea. Number each step 1 through 5, one step per line. Do not include any extra commentary before or after the list.",
        "checker": "numbered_steps", "checker_args": [5], "predict": 256
    },
    {
        "id": "A004", "category": "constraint_following", "difficulty": "medium",
        "task": "Summarize what photosynthesis is in exactly one sentence of no more than 20 words.",
        "checker": "word_count_max", "checker_args": [20], "predict": 96
    },
    {
        "id": "A005", "category": "sequential_ordering", "difficulty": "medium",
        "task": "Write out the correct order of these baking steps as a short paragraph or list, in the order they should actually happen: baking, decorating, preheating the oven, mixing the batter, cooling.",
        "checker": "ordering", "checker_args": [["preheat", "mix", "bak", "cool", "decorat"]], "predict": 256
    },
    {
        "id": "A006", "category": "multi_step_plan", "difficulty": "medium",
        "task": "Write a short project plan for launching a mobile app. Structure it with exactly these three section headers: 'Goal:', 'Steps:', and 'Risks:'.",
        "checker": "headers", "checker_args": [["Goal:", "Steps:", "Risks:"]], "predict": 400
    },
    {
        "id": "A007", "category": "constraint_following", "difficulty": "medium",
        "task": "Write a 4-step deployment checklist using ONLY numbered steps (1., 2., 3., 4.). Do not use any bullet points or dashes anywhere in your response.",
        "checker": "no_bullets", "checker_args": [], "predict": 256
    },
    {
        "id": "A008", "category": "agentic_honesty", "difficulty": "hard",
        "task": "Please actually book a flight for me from New York to London for tomorrow and send me the confirmation email.",
        "checker": "contains_any",
        "checker_args": [["cannot", "can't", "unable", "don't have the ability", "do not have the ability",
                           "no access", "not able to", "i'm not able", "i am not able", "don't have access",
                           "do not have access"]],
        "predict": 200
    },
    {
        "id": "A009", "category": "format_compliance", "difficulty": "medium",
        "task": "List exactly these three fruits as comma-separated values with no spaces after the commas: apple, banana, cherry",
        "checker": "csv_no_spaces", "checker_args": [["apple", "banana", "cherry"]], "predict": 64
    },
    {
        "id": "A010", "category": "structured_output", "difficulty": "hard",
        "task": "Return ONLY a JSON object (no other text) representing a to-do item with keys 'task', 'priority' (one of \"low\", \"medium\", \"high\"), and 'done' (a boolean). Make it about buying groceries with high priority, not yet done.",
        "checker": "json_object", "checker_args": [["task", "priority", "done"]], "predict": 128
    },
]

def benchmark_agent_advanced(runner):
    print(f"Running Advanced Agent Suite ({len(AGENT_TASKS_ADVANCED)} cases)...")
    passed = 0
    details = []
    category_totals = {}
    category_passed = {}

    for item in AGENT_TASKS_ADVANCED:
        r = runner.generate(item["task"], predict=item["predict"])
        checker_fn = AGENT_CHECKERS[item["checker"]]
        try:
            success = checker_fn(r["response"], *item["checker_args"])
        except Exception:
            success = False

        category = item["category"]
        category_totals[category] = category_totals.get(category, 0) + 1
        if success:
            passed += 1
            category_passed[category] = category_passed.get(category, 0) + 1

        details.append({
            "id": item["id"],
            "category": category,
            "difficulty": item["difficulty"],
            "response": r["response"],
            "passed": success,
            "decode_tps": r["decode_tps"],
            "elapsed": round(r["elapsed"], 2)
        })

    breakdown = {
        cat: {
            "passed": category_passed.get(cat, 0),
            "total": total,
            "accuracy": round(100 * category_passed.get(cat, 0) / total, 2)
        }
        for cat, total in category_totals.items()
    }

    accuracy = round(passed / len(AGENT_TASKS_ADVANCED) * 100, 2)
    return {
        "passed": passed,
        "total": len(AGENT_TASKS_ADVANCED),
        "score": accuracy,
        "breakdown": breakdown,
        "details": details
    }

# ============================================================
# RAG ADVANCED
#
# 12 categorized cases testing realistic retrieval-augmented QA
# behavior beyond simple lookup: multi-hop combination of facts
# within context, ignoring distractors, numerical/temporal
# extraction, refusing to answer when the context doesn't contain
# the answer (tests hallucination resistance), and context
# overriding the model's prior world knowledge (tests whether the
# model actually reads the context vs. pattern-matching from
# training data). Uses the same CoT + FINAL ANSWER approach as
# the reasoning/logic advanced suites.
# ============================================================

RAG_TESTS_ADVANCED = [
    {
        "id": "G001", "category": "simple_extraction", "difficulty": "easy",
        "context": "The Eiffel Tower was completed in 1889 and is located in Paris, France.",
        "question": "In what year was the Eiffel Tower completed?",
        "expected": ["1889"], "match": "contains_any"
    },
    {
        "id": "G002", "category": "numerical_extraction", "difficulty": "easy",
        "context": "The company reported quarterly revenue of $4.2 million, up from $3.1 million the previous quarter.",
        "question": "What was the quarterly revenue in dollars?",
        "expected": ["4.2 million", "$4.2 million", "4200000", "4,200,000"], "match": "contains_any"
    },
    {
        "id": "G003", "category": "multi_hop_context", "difficulty": "medium",
        "context": "Maria works at TechCorp. TechCorp's headquarters is in Berlin. Berlin is the capital of Germany.",
        "question": "In which country is the city where Maria works located?",
        "expected": ["germany"], "match": "contains_any"
    },
    {
        "id": "G004", "category": "distractor_robustness", "difficulty": "medium",
        "context": "Alice was born in 1990. Her sister Beth was born in 1988. Their brother Carl was born in 1995. Alice moved to Canada in 2015.",
        "question": "What year was Carl born?",
        "expected": ["1995"], "match": "contains_any"
    },
    {
        "id": "G005", "category": "negation_context", "difficulty": "medium",
        "context": "The new policy does not apply to employees hired before 2020. It applies to all employees hired in 2020 or later.",
        "question": "Does the policy apply to an employee hired in 2019?",
        "expected": ["no", "does not", "not apply"], "match": "contains_any"
    },
    {
        "id": "G006", "category": "no_answer_in_context", "difficulty": "hard",
        "context": "The bakery sells croissants, baguettes, and sourdough bread. It opens at 7 AM on weekdays.",
        "question": "What time does the bakery open on Sundays?",
        "expected": ["not mentioned", "not stated", "doesn't say", "does not say", "cannot determine", "unknown", "not specified", "no information", "not provided", "isn't stated", "is not stated"],
        "match": "contains_any"
    },
    {
        "id": "G007", "category": "context_overrides_knowledge", "difficulty": "hard",
        "context": "In this fictional story, the sky on planet Zorath is green, not blue, due to a unique atmospheric gas.",
        "question": "According to the passage, what color is the sky on planet Zorath?",
        "expected": ["green"], "match": "contains_any"
    },
    {
        "id": "G008", "category": "list_extraction", "difficulty": "medium",
        "context": "The recipe requires the following ingredients: flour, sugar, eggs, butter, and vanilla extract.",
        "question": "How many ingredients does the recipe require?",
        "expected": ["5", "five"], "match": "contains_any"
    },
    {
        "id": "G009", "category": "temporal_reasoning_context", "difficulty": "hard",
        "context": "The project started on March 1st and was completed on March 15th of the same year.",
        "question": "How many days did the project take?",
        "expected": ["14"], "match": "contains_any"
    },
    {
        "id": "G010", "category": "entity_disambiguation", "difficulty": "medium",
        "context": "John Smith is a doctor at City Hospital. John Adams is a teacher at Lincoln High School.",
        "question": "What is the profession of the John who works at City Hospital?",
        "expected": ["doctor"], "match": "contains_any"
    },
    {
        "id": "G011", "category": "summarization_constraint", "difficulty": "medium",
        "context": "Photosynthesis is the process by which plants convert sunlight, water, and carbon dioxide into glucose and oxygen. It occurs primarily in the chloroplasts of plant cells.",
        "question": "In one sentence, what does photosynthesis convert sunlight, water, and carbon dioxide into (name both products)?",
        "expected": ["glucose", "oxygen"], "match": "contains_all"
    },
    {
        "id": "G012", "category": "long_context_needle", "difficulty": "hard",
        "context": ("The company was founded in 2001 by two engineers. It initially focused on hardware manufacturing "
                     "before pivoting to software in 2005. Over the next decade it expanded into cloud services, "
                     "acquiring three smaller startups along the way. The secret internal project codename for "
                     "their flagship product was 'Project Falcon'. The company went public in 2018 and now employs "
                     "over 5,000 people across 12 countries, with its largest office located in Singapore."),
        "question": "What was the internal codename for the company's flagship product?",
        "expected": ["project falcon", "falcon"], "match": "contains_any"
    },
]

def score_rag_advanced(case, response_text):
    segment = extract_final_answer_segment(response_text)
    segment_lower = segment.lower()
    tail_lower = response_text[-150:].lower()

    if case["match"] == "contains_any":
        targets = [e.lower() for e in case["expected"]]
        correct = any(t in segment_lower for t in targets)
        if not correct:
            correct = any(t in tail_lower for t in targets)
    elif case["match"] == "contains_all":
        targets = [e.lower() for e in case["expected"]]
        correct = all(t in segment_lower for t in targets)
        if not correct:
            correct = all(t in tail_lower for t in targets)
    else:
        correct = False
    return correct

def benchmark_rag_advanced(runner):
    print(f"Running Advanced RAG Suite ({len(RAG_TESTS_ADVANCED)} cases)...")
    passed = 0
    details = []
    category_totals = {}
    category_passed = {}

    for item in RAG_TESTS_ADVANCED:
        predict = 384 if item["difficulty"] == "hard" else 320
        prompt = (
            f"Context:\n\n{item['context']}\n\n"
            f"Question:\n\n{item['question']}\n\n"
            "Base your answer only on the information in the context above. "
            "If the context does not contain the answer, say so explicitly."
            + ANSWER_SUFFIX
        )
        r = runner.generate(prompt, predict=predict)
        success = score_rag_advanced(item, r["response"])

        category = item["category"]
        category_totals[category] = category_totals.get(category, 0) + 1
        if success:
            passed += 1
            category_passed[category] = category_passed.get(category, 0) + 1

        details.append({
            "id": item["id"],
            "category": category,
            "difficulty": item["difficulty"],
            "expected": item["expected"],
            "response": r["response"],
            "passed": success,
            "decode_tps": r["decode_tps"],
            "elapsed": round(r["elapsed"], 2)
        })

    breakdown = {
        cat: {
            "passed": category_passed.get(cat, 0),
            "total": total,
            "accuracy": round(100 * category_passed.get(cat, 0) / total, 2)
        }
        for cat, total in category_totals.items()
    }

    accuracy = round(passed / len(RAG_TESTS_ADVANCED) * 100, 2)
    return {
        "passed": passed,
        "total": len(RAG_TESTS_ADVANCED),
        "score": accuracy,
        "breakdown": breakdown,
        "details": details
    }

# ============================================================
# OVERALL SCORE
# ============================================================

def calculate_overall_score(report):
    scores = []
    if "reasoning" in report and report["reasoning"]:
        scores.append(report["reasoning"]["accuracy"])
    if "reasoning_advanced" in report and report["reasoning_advanced"]:
        scores.append(report["reasoning_advanced"]["accuracy"])
    if "logic" in report and report["logic"]:
        scores.append(report["logic"]["accuracy"])
    if "logic_advanced" in report and report["logic_advanced"]:
        scores.append(report["logic_advanced"]["accuracy"])
    if report.get("coding"):
        scores.append(report["coding"]["pass_at_1"])
    if "agent_advanced" in report and report["agent_advanced"]:
        scores.append(report["agent_advanced"]["score"])
    if "rag_advanced" in report and report["rag_advanced"]:
        scores.append(report["rag_advanced"]["score"])
    if not scores:
        return 0
    return round(statistics.mean(scores), 2)

# ============================================================
# PERFORMANCE SCORE
# ============================================================

def calculate_performance_score(report):
    basic = report.get("performance", {}).get("basic")
    if not basic:
        return 0
    prefill = basic["prefill_tps"]
    decode = basic["decode_tps"]
    return round(prefill * 0.4 + decode * 0.6, 2)

# ============================================================
# FINAL SCORE
# ============================================================

def calculate_final_score(report):
    quality = calculate_overall_score(report)
    perf = calculate_performance_score(report)
    if not perf:
        return quality
    if not quality:
        return perf
    return round(quality * 0.70 + perf * 0.30, 2)

# ============================================================
# LEADERBOARD
# ============================================================

def build_leaderboard(reports):
    rows = []
    for report in reports:
        rows.append({
            "model": report["model"],
            "quality": calculate_overall_score(report),
            "performance": calculate_performance_score(report),
            "final": calculate_final_score(report)
        })
    rows.sort(key=lambda x: x["final"], reverse=True)
    return rows

def print_leaderboard(reports):
    board = build_leaderboard(reports)
    print()
    print("=" * 90)
    print("FINAL LEADERBOARD")
    print("=" * 90)
    print(f"{'Rank':<6}{'Model':<35}{'Quality':<12}{'Performance':<15}{'Final':<10}")
    print("-" * 90)
    for idx, row in enumerate(board, start=1):
        print(f"{idx:<6}{row['model']:<35}{row['quality']:<12}{row['performance']:<15}{row['final']:<10}")

# ============================================================
# JSON EXPORT
# ============================================================

def safe_model_name(name):
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(name)).strip("-.") or "model"


def save_json(reports):
    outfile = os.path.join(RESULT_DIR, "report.json")
    with open(outfile, "w") as f:
        json.dump(reports, f, indent=2)
    print(f"Saved {outfile}")
    for report in reports:
        safe_name = safe_model_name(report["model"])
        model_file = os.path.join(RESULT_DIR, f"{safe_name}-result.json")
        with open(model_file, "w") as f:
            json.dump(report, f, indent=2)
        print(f"Import-ready JSON: {model_file}")

# ============================================================
# CSV EXPORT
# ============================================================

def save_csv(reports):
    outfile = os.path.join(RESULT_DIR, "leaderboard.csv")
    leaderboard = build_leaderboard(reports)
    with open(outfile, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Rank", "Model", "Quality", "Performance", "Final Score"])
        for idx, row in enumerate(leaderboard, start=1):
            writer.writerow([idx, row["model"], row["quality"], row["performance"], row["final"]])
    print(f"Saved {outfile}")

# ============================================================
# HISTORY
# ============================================================

def update_history(reports):
    history_file = os.path.join(RESULT_DIR, "benchmark_history.json")
    history = []
    if os.path.exists(history_file):
        try:
            with open(history_file) as f:
                history = json.load(f)
        except Exception:
            history = []
    history.extend(reports)
    with open(history_file, "w") as f:
        json.dump(history, f, indent=2)
    print(f"Updated {history_file}")

# ============================================================
# MODEL SUMMARY
# ============================================================

def print_model_summary(report):
    print()
    print("=" * 80)
    print(report["model"])
    print("=" * 80)
    basic = report.get("performance", {}).get("basic")
    if basic:
        print("Prefill TPS:", basic["prefill_tps"])
        print("Decode TPS:", basic["decode_tps"])
        print("TTFT:", basic["ttft"])
    if "reasoning" in report and report["reasoning"]:
        print("Reasoning:", report["reasoning"]["accuracy"])
    if "reasoning_advanced" in report and report["reasoning_advanced"]:
        print("Reasoning (Advanced, CoT):", report["reasoning_advanced"]["accuracy"])
    if "logic" in report and report["logic"]:
        print("Logic (Basic):", report["logic"]["accuracy"])
    if "logic_advanced" in report and report["logic_advanced"]:
        print("Logic (Advanced, CoT):", report["logic_advanced"]["accuracy"])
        if report["logic_advanced"].get("breakdown"):
            for cat, stats in report["logic_advanced"]["breakdown"].items():
                print(f"    {cat}: {stats['passed']}/{stats['total']} ({stats['accuracy']}%)")
    if report.get("coding"):
        print("Coding:", report["coding"]["pass_at_1"])
        if report["coding"].get("breakdown"):
            for cat, stats in report["coding"]["breakdown"].items():
                print(f"    {cat}: {stats['passed']}/{stats['total']} ({stats['accuracy']}%)")
    if "rag_advanced" in report and report["rag_advanced"]:
        print("RAG:", report["rag_advanced"]["score"])
        if report["rag_advanced"].get("breakdown"):
            for cat, stats in report["rag_advanced"]["breakdown"].items():
                print(f"    {cat}: {stats['passed']}/{stats['total']} ({stats['accuracy']}%)")
    if "agent_advanced" in report and report["agent_advanced"]:
        print("Agent:", report["agent_advanced"]["score"])
        if report["agent_advanced"].get("breakdown"):
            for cat, stats in report["agent_advanced"]["breakdown"].items():
                print(f"    {cat}: {stats['passed']}/{stats['total']} ({stats['accuracy']}%)")
    print("Quality Score:", calculate_overall_score(report))
    print("Performance Score:", calculate_performance_score(report))
    print("Final Score:", calculate_final_score(report))

# ============================================================
# ALL SUMMARIES
# ============================================================

def print_summary(reports):
    print()
    print("=" * 100)
    print("BENCHMARK SUMMARY")
    print("=" * 100)
    for report in reports:
        print_model_summary(report)
    print_leaderboard(reports)

# ============================================================
# EXPORT EVERYTHING
# ============================================================

def export_results(reports):
    save_json(reports)
    save_csv(reports)
    update_history(reports)
    print_summary(reports)

# ============================================================
# CHARTS
# ============================================================

def save_tps_chart(report):
    if plt is None:
        return
    try:
        values = [
            report["performance"]["basic"]["prefill_tps"],
            report["performance"]["basic"]["decode_tps"]
        ]
        labels = ["Prefill TPS", "Decode TPS"]
        plt.figure(figsize=(7, 4))
        plt.bar(labels, values)
        plt.title(report["model"])
        plt.tight_layout()
        outfile = os.path.join(CHART_DIR, safe_model_name(report["model"]) + "_tps.png")
        plt.savefig(outfile)
        plt.close()
        print(f"Saved {outfile}")
    except Exception as e:
        print("Chart Error:", e)

# ============================================================
# QUALITY CHART
# ============================================================

def save_quality_chart(report):
    if plt is None:
        return
    try:
        labels = ["Reasoning-Adv", "Logic-Adv", "Coding", "Agent", "RAG"]
        values = [
            report["reasoning_advanced"]["accuracy"] if report.get("reasoning_advanced") else 0,
            report["logic_advanced"]["accuracy"] if report.get("logic_advanced") else 0,
            report["coding"]["pass_at_1"],
            report["agent_advanced"]["score"] if report.get("agent_advanced") else 0,
            report["rag_advanced"]["score"] if report.get("rag_advanced") else 0
        ]
        if report.get("reasoning"):
            labels.insert(0, "Reasoning-Basic")
            values.insert(0, report["reasoning"]["accuracy"])
        if report.get("logic"):
            labels.insert(0, "Logic-Basic")
            values.insert(0, report["logic"]["accuracy"])
        plt.figure(figsize=(8, 4))
        plt.bar(labels, values)
        plt.title(report["model"])
        plt.ylim(0, 100)
        plt.tight_layout()
        outfile = os.path.join(CHART_DIR, safe_model_name(report["model"]) + "_quality.png")
        plt.savefig(outfile)
        plt.close()
        print(f"Saved {outfile}")
    except Exception as e:
        print("Chart Error:", e)

# ============================================================
# HTML DASHBOARD
# ============================================================

def generate_html(reports):
    reports = sorted(reports, key=lambda x: x.get("final_score", 0), reverse=True)
    cards = ""
    for report in reports:
        basic = report.get("performance", {}).get("basic", {})
        reasoning_adv_html = ""
        if report.get("reasoning_advanced"):
            reasoning_adv_html = f"<div class='metric'>Reasoning (Advanced/CoT): <b>{report['reasoning_advanced']['accuracy']}%</b></div>"
        reasoning_basic_html = ""
        if report.get("reasoning"):
            reasoning_basic_html = f"<div class='metric'>Reasoning (Basic): <b>{report['reasoning']['accuracy']}%</b></div>"
        logic_basic_html = ""
        if report.get("logic"):
            logic_basic_html = f"<div class='metric'>Logic (Basic): <b>{report['logic']['accuracy']}%</b></div>"
        logic_adv_html = ""
        if report.get("logic_advanced"):
            logic_adv_html = f"<div class='metric'>Logic (Advanced/CoT): <b>{report['logic_advanced']['accuracy']}%</b></div>"
        agent_html = ""
        if report.get("agent_advanced"):
            agent_html = f"<div class='metric'>Agent: <b>{report['agent_advanced']['score']}%</b></div>"
        rag_html = ""
        if report.get("rag_advanced"):
            rag_html = f"<div class='metric'>RAG: <b>{report['rag_advanced']['score']}%</b></div>"
        cards += f"""
<div class='card'>
<h2>{html.escape(str(report['model']))}</h2>
<div class='score'>Final Score: {report['final_score']}</div>
<div class='metric'>Prefill TPS: <b>{basic.get('prefill_tps', '—')}</b></div>
<div class='metric'>Decode TPS: <b>{basic.get('decode_tps', '—')}</b></div>
<div class='metric'>TTFT: <b>{basic.get('ttft', '—')}</b></div>
{reasoning_basic_html}
{reasoning_adv_html}
{logic_basic_html}
{logic_adv_html}
<div class='metric'>Coding: <b>{report.get('coding', {}).get('pass_at_1', '—')}%</b></div>
{agent_html}
{rag_html}
</div>
"""
    return f"""<!DOCTYPE html>
<html>
<head>
<title>LLM Benchmark Dashboard</title>
<style>
body {{ background:#f4f6f9; font-family:Arial; margin:20px; }}
h1 {{ text-align:center; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(350px,1fr)); gap:20px; }}
.card {{ background:white; padding:20px; border-radius:12px; box-shadow:0 2px 8px rgba(0,0,0,.15); }}
.score {{ color:green; font-size:22px; font-weight:bold; margin-bottom:10px; }}
.metric {{ margin:6px 0; }}
</style>
</head>
<body>
<h1>LLM Benchmark Dashboard</h1>
<div class='grid'>
{cards}
</div>
</body>
</html>"""

# ============================================================
# SAVE DASHBOARD
# ============================================================

def save_html_dashboard(reports):
    outfile = os.path.join(RESULT_DIR, "dashboard.html")
    with open(outfile, "w") as f:
        f.write(generate_html(reports))
    print(f"Saved {outfile}")

# ============================================================
# RUN COMPLETE BENCHMARK
# ============================================================

def save_checkpoint(report, done, total):
    tmp = CHECKPOINT_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"report": report, "done": done, "total": total}, f, indent=2)
    os.replace(tmp, CHECKPOINT_FILE)

def load_checkpoint():
    with open(CHECKPOINT_FILE) as f:
        return json.load(f)

def run_steps(report, steps):
    """Run each (report_key, fn) once, checkpointing after every step. With RESUME, steps the checkpoint finished are skipped."""
    done = []
    if RESUME and CHECKPOINT_FILE and os.path.exists(CHECKPOINT_FILE):
        saved = load_checkpoint()
        done = [name for name, _ in steps if name in saved["done"]]
        report.update({name: saved["report"][name] for name in done})
    if CHECKPOINT_FILE:
        save_checkpoint(report, done, len(steps))
    group = None
    for name, fn in steps:
        if name in done:
            print(f"[RESUME] {name} already done; skipping")
            continue
        if group != (name == "performance"):
            group = name == "performance"
            print("\n" + "=" * 70 + "\n" + ("PERFORMANCE" if group else "CAPABILITY") + "\n" + "=" * 70)
        report[name] = fn()
        done.append(name)
        if CHECKPOINT_FILE:
            save_checkpoint(report, done, len(steps))

def run_complete_benchmark(runner, report, contexts, benchmark_type="both",
                            skip_advanced_reasoning=False, include_basic_reasoning=False,
                            include_basic_logic=False):
    steps = []
    if benchmark_type != "tasks":
        steps.append(("performance", lambda: run_performance_suite(runner, contexts)))
    if benchmark_type != "performance":
        if include_basic_reasoning:
            steps.append(("reasoning", lambda: benchmark_reasoning(runner)))
        if not skip_advanced_reasoning:
            steps.append(("reasoning_advanced", lambda: benchmark_reasoning_advanced(runner)))
        if include_basic_logic:
            steps.append(("logic", lambda: benchmark_logic(runner)))
        steps += [
            ("logic_advanced", lambda: benchmark_logic_advanced(runner)),
            ("coding", lambda: benchmark_humaneval(runner)),
            ("agent_advanced", lambda: benchmark_agent_advanced(runner)),
            ("rag_advanced", lambda: benchmark_rag_advanced(runner)),
        ]
    run_steps(report, steps)
    if report["performance"]:
        report["niah"] = report["performance"]["niah"]

    report["quality_score"] = calculate_overall_score(report)
    report["performance_score"] = calculate_performance_score(report)
    report["final_score"] = calculate_final_score(report)

    return report

# ============================================================
# PARSE ARGS
# ============================================================

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="LLM Benchmark Suite")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--model")
    parser.add_argument("--models", nargs="+")
    parser.add_argument("--display-name", help="Report name; API requests still use --model")
    parser.add_argument("-t", "--threads", type=int, default=8)
    parser.add_argument("-c", "--ctx", type=int, default=4096)
    parser.add_argument("--niah-contexts",
                         help="Comma-separated synthetic word counts; defaults scale with --ctx (512,1024,2048 at 4096)")
    parser.add_argument("--benchmark-type", choices=["performance", "tasks", "both"], default="both")
    parser.add_argument("--result-dir", default="results")
    parser.add_argument("--resume", action="store_true",
                         help="Continue an interrupted run in --result-dir: sections already in its checkpoint are skipped")
    parser.add_argument("--skip-advanced-reasoning", action="store_true",
                         help="Skip the 10-case CoT reasoning suite")
    parser.add_argument("--include-basic-reasoning", action="store_true",
                         help="Also run the old 10-item basic reasoning suite (arithmetic/logic one-liners). Skipped by default now that the advanced CoT suite covers this better.")
    parser.add_argument("--include-basic-logic", action="store_true",
                         help="Also run the old 4-item basic logic suite. Skipped by default now that the 20-case categorized advanced logic suite covers this better.")
    parser.add_argument("--fd-limit", type=int, default=65536,
                         help="Attempt to raise the open-file descriptor limit to this value before running")

    # runner mode selection
    parser.add_argument("--runner-mode", choices=["completion", "server", "openai"], default="completion",
                         help="Use a local llama-completion binary (default), llama-server, or an OpenAI-compatible endpoint.")
    parser.add_argument("--api-base-url", default=os.getenv("OPENAI_BASE_URL"),
                         help="[openai mode] base URL ending in /v1")
    parser.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY", "dummy"),
                         help="[openai mode] API key")
    parser.add_argument("--runtime-name", default="llama.cpp")

    # completion-mode args (unchanged from original)
    parser.add_argument("--binary", default=DEFAULT_BINARY,
                         help="[completion mode] path to llama-completion binary")

    # server-mode args (added)
    parser.add_argument("--server-url", type=str, default=None,
                         help="[server mode] base URL of an already-running llama-server, e.g. http://127.0.0.1:8080. If omitted, the script launches its own server per model.")
    parser.add_argument("--llama-server-bin", type=str, default="llama-server",
                         help="[server mode] path to the llama-server binary, used when --server-url is not given")
    parser.add_argument("--ngl", type=int, default=99,
                         help="[server mode] layers offloaded to GPU/NPU-backed backend")
    parser.add_argument("--server-parallel", type=int, default=1,
                         help="[server mode] number of parallel slots (--parallel). Keep at 1 for sequential benchmarking on RKNPU backends to avoid fd exhaustion.")
    parser.add_argument("--server-startup-timeout", type=int, default=180)
    parser.add_argument("--extra-server-args", type=str, default="",
                         help="[server mode] extra args passed to llama-server, quoted")

    args = parser.parse_args(argv)
    if args.threads < 1 or args.ctx < 1:
        parser.error("--threads and --ctx must be positive")
    if args.niah_contexts is None:
        # Leave room for tokenization overhead, the retrieval instruction and the answer.
        args.niah_contexts = ",".join(str(max(1, min(size, args.ctx // divisor)))
                                     for divisor, size in ((8, 4096), (4, 8192), (2, 16384)))
    return args

def self_test():
    report = empty_report("test.gguf")
    report["performance"] = {"basic": {"prefill_tps": 10, "decode_tps": 20}}
    assert calculate_performance_score(report) == 16
    report["performance"] = {}
    report["reasoning_advanced"] = {"accuracy": 75}
    assert calculate_final_score(report) == 75
    assert stream_text({"choices": [{"delta": {"content": "ready"}}]}) == "ready"
    assert stream_text({"choices": [{"delta": {"reasoning_content": "thinking"}}]}) == "thinking"
    assert OpenAIChatRunner("http://localhost:8000/v1/", "x", "m").url == "http://localhost:8000/v1/chat/completions"
    assert safe_model_name("../Display Model") == "Display-Model"
    # Resume: a step that dies keeps the earlier steps; --resume runs only what is left.
    global CHECKPOINT_FILE, RESUME
    ran = []
    def step(name):
        return name, lambda: ran.append(name) or {"v": name}
    def crash():
        raise RuntimeError("cut")
    with tempfile.TemporaryDirectory() as tmp:
        CHECKPOINT_FILE, RESUME = os.path.join(tmp, "checkpoint-m.json"), False
        try:
            run_steps({}, [step("a"), ("b", crash)])
        except RuntimeError:
            pass
        assert load_checkpoint()["done"] == ["a"] and load_checkpoint()["total"] == 2
        RESUME, ran[:], resumed = True, [], {}
        run_steps(resumed, [step("a"), step("b")])
        assert ran == ["b"] and resumed == {"a": {"v": "a"}, "b": {"v": "b"}}
        assert load_checkpoint()["done"] == ["a", "b"]
    CHECKPOINT_FILE, RESUME = None, False
    print("edge benchmark self-test passed")


def preflight(args):
    if args.runner_mode == "completion":
        if not args.model:
            raise SystemExit("Local preflight requires --model and --binary")
        result = LlamaRunner(args.binary, args.model, args.threads, args.ctx).generate(
            "Reply with READY only.", predict=8
        )
        if not result["response"]:
            raise SystemExit(f"Local preflight returned no response: {result['raw_output']}")
        print(f"Edge local preflight passed: {args.model} using {args.binary}")
        return
    if args.runner_mode != "openai" or not args.api_base_url or not args.model:
        raise SystemExit("OpenAI preflight requires --api-base-url and --model")
    result = OpenAIChatRunner(args.api_base_url, args.api_key, args.model, timeout=30).generate(
        "Reply with READY only.", predict=8
    )
    if not result["response"]:
        raise SystemExit(f"Endpoint preflight failed: {result['raw_output']}")
    print(f"Edge endpoint preflight passed: {args.model} at {args.api_base_url}")

# ============================================================
# MAIN BENCHMARK LOOP
# ============================================================

def benchmark_main(args, ensure_dirs, discover_models, empty_report):
    global RESULT_DIR, CHART_DIR, CHECKPOINT_FILE, RESUME
    RESULT_DIR = args.result_dir
    CHART_DIR = os.path.join(RESULT_DIR, "charts")
    RESUME = args.resume
    ensure_fd_limit(args.fd_limit)
    ensure_dirs()

    models = []
    if args.model:
        models.append(args.model)
    if args.models:
        models.extend(discover_models(args.models))
    if not models:
        raise SystemExit("Provide --model or --models")
    if args.display_name and len(models) != 1:
        raise SystemExit("--display-name requires exactly one model")

    contexts = [int(x) for x in args.niah_contexts.split(",")]
    reports = []
    extra_args = args.extra_server_args.split() if args.extra_server_args else None

    for model in models:
        print()
        print("=" * 80)
        print(os.path.basename(model))
        print("=" * 80)

        report = empty_report(model)
        report["model"] = args.display_name or report["model"]
        CHECKPOINT_FILE = os.path.join(RESULT_DIR, f"checkpoint-{safe_model_name(report['model'])}.json")
        report["benchmark_mode"] = {"performance": "performance", "tasks": "capability", "both": "complete"}[args.benchmark_type]
        report["platform"] = {
            "threads": args.threads,
            "ctx": args.ctx,
            "runner_mode": args.runner_mode,
            "runtime_name": args.runtime_name,
            "architecture": platform.machine(),
            "ram_gib": ram_gib(),
        }

        if args.runner_mode == "openai":
            if not args.api_base_url:
                raise SystemExit("OpenAI runner requires --api-base-url")
            runner = OpenAIChatRunner(args.api_base_url, args.api_key, model)
            report = run_complete_benchmark(runner, report, contexts,
                                             benchmark_type=args.benchmark_type,
                                             skip_advanced_reasoning=args.skip_advanced_reasoning,
                                             include_basic_reasoning=args.include_basic_reasoning,
                                             include_basic_logic=args.include_basic_logic)
            reports.append(report)
            if args.benchmark_type != "tasks":
                save_tps_chart(report)
            if args.benchmark_type != "performance":
                save_quality_chart(report)

        elif args.runner_mode == "completion":
            runner = LlamaRunner(
                binary=args.binary,
                model=model,
                threads=args.threads,
                ctx=args.ctx
            )
            report = run_complete_benchmark(runner, report, contexts,
                                             benchmark_type=args.benchmark_type,
                                             skip_advanced_reasoning=args.skip_advanced_reasoning,
                                             include_basic_reasoning=args.include_basic_reasoning,
                                             include_basic_logic=args.include_basic_logic)
            reports.append(report)
            if args.benchmark_type != "tasks":
                save_tps_chart(report)
            if args.benchmark_type != "performance":
                save_quality_chart(report)

        else:  # server mode
            if args.server_url:
                # hit an already-running server; don't manage its lifecycle
                if not wait_for_server(args.server_url, timeout=15):
                    print(f"WARNING: could not reach {args.server_url}, attempting anyway...")
                runner = ServerRunner(args.server_url)
                report = run_complete_benchmark(runner, report, contexts,
                                                 benchmark_type=args.benchmark_type,
                                                 skip_advanced_reasoning=args.skip_advanced_reasoning,
                                                 include_basic_reasoning=args.include_basic_reasoning,
                                             include_basic_logic=args.include_basic_logic)
                reports.append(report)
                if args.benchmark_type != "tasks":
                    save_tps_chart(report)
                if args.benchmark_type != "performance":
                    save_quality_chart(report)
            else:
                # launch our own server for this model, benchmark, tear down
                port = find_free_port()
                base_url = f"http://127.0.0.1:{port}"
                safe_tag = re.sub(r"[^a-zA-Z0-9_\-]", "_", os.path.basename(model))
                log_path = os.path.join(RESULT_DIR, f"server_{safe_tag}.log")
                print(f">>> Starting server for {os.path.basename(model)} on port {port}")
                proc = start_llama_server(
                    args.llama_server_bin, model, port,
                    args.threads, args.ngl, args.ctx,
                    parallel=args.server_parallel, extra_args=extra_args,
                    log_path=log_path
                )
                try:
                    if not wait_for_server(base_url, timeout=args.server_startup_timeout):
                        print(f"  ERROR: server did not become healthy within {args.server_startup_timeout}s, skipping this model. Check {log_path}")
                        continue
                    runner = ServerRunner(base_url)
                    report = run_complete_benchmark(runner, report, contexts,
                                                     benchmark_type=args.benchmark_type,
                                                     skip_advanced_reasoning=args.skip_advanced_reasoning,
                                                     include_basic_reasoning=args.include_basic_reasoning,
                                             include_basic_logic=args.include_basic_logic)
                    reports.append(report)
                    if args.benchmark_type != "tasks":
                        save_tps_chart(report)
                    if args.benchmark_type != "performance":
                        save_quality_chart(report)
                finally:
                    print(f"  Stopping server for {os.path.basename(model)}")
                    stop_llama_server(proc)
                    time.sleep(2)  # let port free up

    if not reports:
        raise SystemExit("No models were successfully benchmarked.")

    export_results(reports)
    save_html_dashboard(reports)
    # Completion marker: run.sh stops offering this run for resume.
    Path(RESULT_DIR, "benchmark-end-epoch").write_text(f"{int(time.time())}\n")

    print()
    print("=" * 80)
    print("Benchmark Completed")
    print("=" * 80)
    print(f"Results saved to {RESULT_DIR}")

# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    args = parse_args()
    if args.self_test:
        self_test()
    elif args.preflight:
        preflight(args)
    else:
        benchmark_main(args, ensure_dirs, discover_models, empty_report)
