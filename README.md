# AI Model Benchmarking

Edge runs a local GGUF model through `llama-completion`. Advanced, Quick and Vals use an OpenAI-compatible Chat Completions API; their model can run separately on DGX or another server.

## Available benchmarks

| Benchmark | Tests included by default | Speed measurements | Runtime / limits |
|---|---|---|---|
| **Quick** | 4 SWE + 4 Terminal + 2 LiveBench = **10 tasks** | Prefill, C1 decode, TTFT, C4/C8/C12 throughput | Target ~45–60 min; no global deadline |
| **Complete (Advanced)** | 10 SWE + 10 Terminal + 5 LiveBench = **25 tasks** | Same as Quick | Several hours; can exceed 5 hours; no global deadline |
| **Vals public proxy** | **60 tasks**, five domains (below) | None | Typically ~65–75 min; 100-min task-run budget, excluding preflight |
| **Edge Complete** | **78 capability cases** + 3 retrieval checks | Basic speed, prefill, decode, response latency | Model-dependent; no global deadline |
| **Performance only** | No capability tasks | Advanced: C1/C4/C8/C12; Edge: speed + retrieval checks | Model-dependent |

`Capability` runs the selected profile's capability tests without its speed/retrieval pass. Advanced task counts are adjustable; Quick and Vals use fixed selections. First-run downloads add setup time.

### Quick and Complete coverage

| Suite | Quick selection | Complete selection | Grading |
|---|---|---|---|
| SWE-bench Verified | **4:** `django__django-11179`, `sympy__sympy-16886`, `pytest-dev__pytest-7982`, `pallets__flask-5014` | **10** repository bug fixes | Official SWE-bench evaluator |
| Terminal-Bench 2.1 | **4:** `fix-git`, `prove-plus-comm`, `kv-store-grpc`, `nginx-request-logging` | **10** Git, services, database, build and concurrency tasks | Harbor task verifier |
| LiveBench subset | **2:** `livebench-zebra_puzzle-26`, `livebench-spatial-88` | **5** zebra-puzzle and spatial questions | Local objective answer checks |

All selections are in [run.sh](benchmark/run.sh); the [benchmark guide](docs/benchmark-guide.md) lists the Complete task IDs. Quick uses easier tasks and shorter limits, so its scores are not comparable with Complete. Neither subset is a full upstream leaderboard evaluation.

Advanced speed measurements use one warm-up and three measured runs per measurement, reporting medians. C4/C8/C12 are **aggregate** tokens/s across concurrent requests; C1 is single-request decode. Prefill is an API-observed estimate, and server memory usage is unavailable without separate telemetry.

### Vals public proxy coverage

| Domain | Public benchmark | Tasks | Local evaluation |
|---|---|---:|---|
| Legal | LegalBench, 8 task types | 16 | Label accuracy |
| Finance | Finance Agent v2 | 14 | Closed-book, severity-weighted rubric score |
| Healthcare | MedQA | 12 | Multiple-choice accuracy |
| Mathematics | AIME 2024 / 2025 | 9 | Exact final integer answer |
| Science / engineering | MMLU-Pro | 9 | Multiple-choice accuracy |
| **Total** | **5 domains** | **60** | |

Questions, answers/rubrics, source links and upstream revisions are pinned in [vals-public-cases.json](benchmark/vals-public-cases.json). Task results retain the public task URL, Vals URL, version and grading evidence. This suite uses public resources and local graders; every result carries **`public_proxy — not Vals leaderboard comparable`**. See the [Vals availability report](docs/vals-ai-benchmark-report.md) for catalog access and licensing details.

Finance has no web/EDGAR tools. Its headline is a rubric score, not accuracy; the local pass threshold is 40%. The judge defaults to the model under test. For independent judging, set `VALS_JUDGE_BASE_URL`, `VALS_JUDGE_MODEL` and `VALS_JUDGE_API_KEY`; keep the judge fixed when comparing models.

### Edge coverage

| Suite | Default cases | What it checks |
|---|---:|---|
| Advanced reasoning | 10 | Arithmetic, multi-step reasoning, probability and deduction |
| Advanced logic | 20 | Conditions, quantifiers, syllogisms and logic puzzles |
| HumanEval Lite | 26 | Local Python function tests: strings, lists, algorithms and edge cases |
| Agent tasks | 10 | Structured output, constraints and planning responses |
| RAG | 12 | Answers from supplied context, extraction and missing-information handling |
| **Capability total** | **78** | Project-defined tests, not official leaderboard scores |
| Needle-in-a-haystack | 3 | Retrieval at 512 / 1024 / 2048 synthetic words with the default 4096-token context; included in the performance pass |

Definitions are in [edge_benchmark.py](benchmark/edge_benchmark.py). Direct-script flags `--include-basic-reasoning` / `--include-basic-logic` add 10 / 4 cases, disabled by default. Retrieval sizes use synthetic word counts; Edge speed metrics differ from Advanced. **Edge coding executes model-generated Python on the host; use an isolated, disposable environment.**

## Run guide

Edge needs Python 3, a local GGUF file and a working `llama-completion` binary built for the device (including ARM64). Advanced runs need Linux, Bash, Python 3, curl, GNU timeout and awk. Quick/Advanced capability also needs Git, Python venv support, **x86-64 and working Docker**; the runner installs its pinned Python packages automatically.

| Mode | Docker | Free disk required by the runner |
|---|---|---|
| Quick | Yes | 30 GiB at startup; 20 GiB before each task |
| Complete / Advanced capability | Yes | 75 GiB at startup; 20 GiB before each task |
| Vals / Performance / Edge | No | No Docker disk threshold |

### Edge: local files

Run `bash benchmark/run.sh` and select **1. Edge Device Benchmark**. It asks only for the **model path** and **llama-completion path**, then runs the complete Edge suite with **8 threads / 4096 context**. No API URL, key, display-name or benchmark-content prompt is needed.

Or run the Python script directly from the repository root:

```bash
python3 benchmark/edge_benchmark.py \
  --model /home/pi/NVIDIA-Nemotron-3-Nano-4B-Q4_K_M.gguf \
  --binary /home/pi/prism-llama.cpp/build/bin/llama-completion \
  -t 8 -c 4096
```

Direct runs write to `results/`; use `--result-dir` to change it. Add `--preflight` to check the files and generate a short response, or `--benchmark-type tasks` / `--benchmark-type performance` to run only that part. The binary loads the model for each prompt, so runtime includes repeated loading.

For scripted `run.sh` commands, set `EDGE_MODEL` and `EDGE_BINARY` to those paths. Optional `EDGE_THREADS=8` and `EDGE_CONTEXT_TOKENS=4096` control execution and are saved for resume. Default retrieval sizes scale down with context; use `--niah-contexts` in direct runs to override them. Explicit Python `--runner-mode openai` / `server` remains available.

### Advanced: API endpoint

For initial workstation installation, follow [setup-guide.md](docs/setup-guide.md). From the repository root, configure the API:

```bash
export OPENAI_BASE_URL="http://127.0.0.1:8000/v1"
export OPENAI_MODEL="your-served-model-id"
export OPENAI_MODEL_DISPLAY_NAME="My Model"
export BENCH_CONFIG=/dev/null  # Use these environment settings instead of config.env.
```

For authentication, export `OPENAI_API_KEY` separately. The display name labels reports; `OPENAI_MODEL` is the API model ID. These API settings are not used by local Edge runs.

### Scripted runs

Choose **one** command after setting the local paths (Edge) or API settings (Advanced). Set `export BENCH_CONFIG=/dev/null` so an existing `config.env` cannot override these choices. Commands below run without prompts:

| Run | Command |
|---|---|
| Quick | `BENCHMARK_PROFILE=advanced BENCHMARK_TYPE=quick bash benchmark/run.sh </dev/null` |
| Vals | `BENCHMARK_PROFILE=advanced BENCHMARK_TYPE=vals-public bash benchmark/run.sh </dev/null` |
| Complete | `BENCHMARK_PROFILE=advanced BENCHMARK_TYPE=both bash benchmark/run.sh </dev/null` |
| Advanced capability only | `BENCHMARK_PROFILE=advanced BENCHMARK_TYPE=tasks bash benchmark/run.sh </dev/null` |
| Advanced performance only | `BENCHMARK_PROFILE=advanced BENCHMARK_TYPE=performance bash benchmark/run.sh </dev/null` |
| Edge Complete | `BENCHMARK_PROFILE=edge BENCHMARK_TYPE=both bash benchmark/run.sh </dev/null` |
| Edge capability only | `BENCHMARK_PROFILE=edge BENCHMARK_TYPE=tasks bash benchmark/run.sh </dev/null` |
| Edge performance only | `BENCHMARK_PROFILE=edge BENCHMARK_TYPE=performance bash benchmark/run.sh </dev/null` |

For Advanced capability/Complete, adjust `SWE_TASK_COUNT` (0–10), `TERMINAL_TASK_COUNT` (0–10) and `REASONING_TASK_COUNT` (0–5); for example, `export SWE_TASK_COUNT=2`. Every run performs preflight. To check Quick setup separately:

```bash
BENCHMARK_PROFILE=advanced BENCHMARK_TYPE=quick bash benchmark/run.sh --preflight </dev/null
```

For an interactive menu or resume, use `bash benchmark/run.sh`. For saved defaults, copy [config.example.env](config.example.env) to `config.env`, edit it, then `unset BENCH_CONFIG` before opening the menu. Resume keeps finished outcomes, retries infrastructure errors and continues missing measurements; Edge resumes by section. Each resumed Vals session receives a fresh time budget.

The Advanced API must support `/chat/completions`. Speed tests additionally require streaming token usage and `ignore_eos`. `/models` is optional; set supported limits with `OPENAI_MODEL_MAX_INPUT_TOKENS` / `OPENAI_MODEL_MAX_OUTPUT_TOKENS` if detection is unavailable. SWE/Terminal require at least 16K input and 4K output capacity; Vals math can request up to 16K output tokens.

## Results and recorded runs

`run.sh` outputs go to `benchmark-results/<UTC-run-id>/` (direct Edge Python runs default to `results/`):

| Output | Advanced / Quick / Vals | Edge |
|---|---|---|
| Model JSON | `<model>-result.json` (live and final) | `<model>-result.json` (final; different Edge schema) |
| HTML report | `<model>-result.html` | `dashboard.html` |
| Progress / evidence | `run.log`, `task-results.tsv`, `primary/`, `perf/` when measured | `checkpoint-<model>.json`, `report.json`, `leaderboard.csv` |



Completed means the run ended, not that all tests passed. The completed Nemotron Vals run includes 10 infrastructure errors. Older 30-/53-task Vals runs use different selections and are excluded from the current-suite count; compare matching task versions, settings and judges.

The runner preserves Docker caches. When space is needed, use `bash benchmark/cleanup-docker-cache.sh`; avoid `docker system prune`. Keep API keys and model weights out of published artifacts.

Further details: [benchmark workflow and task IDs](docs/benchmark-guide.md) · [installation and troubleshooting](docs/setup-guide.md) · [Vals catalog and methodology](docs/vals-ai-benchmark-report.md).
