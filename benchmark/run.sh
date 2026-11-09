#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BENCH_DIR="$ROOT/benchmark"
CONFIG_FILE="${BENCH_CONFIG:-$ROOT/config.env}"
if [[ -f "$CONFIG_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
  set +a
fi

MODE="${1:-run}"
if [[ "$MODE" != run && "$MODE" != --preflight ]]; then
  echo "Usage: $0 [--preflight]" >&2
  exit 2
fi

# Rows in a results TSV, header excluded.
tsv_rows() {
  awk 'NR > 1' "$1" 2>/dev/null | wc -l || true
}

# List unfinished runs (resume.env written, no benchmark-end-epoch) and let the user continue one or start new.
RESUME_DIR=""
offer_resume() {
  local dirs=() d i=0 answer
  for d in $(ls -dt "$ROOT"/benchmark-results/20*/ 2>/dev/null); do
    d=${d%/}
    [[ -f "$d/resume.env" && ! -f "$d/benchmark-end-epoch" ]] && dirs+=("$d")
  done
  (( ${#dirs[@]} )) || return 0
  echo "Unfinished benchmark runs:"
  for d in "${dirs[@]}"; do
    i=$((i + 1))
    (
      # shellcheck disable=SC1091
      source "$d/resume.env"
      retry=$(awk -F '\t' 'NR > 1 && $9 == "infra_error"' "$d/task-results.tsv" 2>/dev/null | wc -l || true)
      if [[ "$BENCHMARK_PROFILE" == edge ]]; then
        read -r finished total < <(python3 -c 'import glob, json, sys
for f in glob.glob(sys.argv[1] + "/checkpoint-*.json"):
    c = json.load(open(f)); print(len(c["done"]), c["total"]); break
else:
    print(0, "?")' "$d") || true
        unit=sections
      else
        total=$(( $(tsv_rows "$d/selected-tasks.tsv") + RESUME_PERF_TOTAL ))
        perf_done=$(ls "$d"/perf/*.json 2>/dev/null | wc -l || true)
        finished=$(( $(tsv_rows "$d/task-results.tsv") - retry + perf_done ))
        unit=tasks
        (( RESUME_PERF_TOTAL )) && unit=steps
      fi
      pending=$([[ "$total" == '?' ]] && echo '?' || echo $((total - finished)))
      last=$(ls -t "$d"/run.log "$d"/checkpoint-*.json "$d"/resume.env 2>/dev/null | head -1 || true)
      printf '  %d) %s  %s  %s/%s  %s/%s %s done, %s pending%s  last activity %s\n' "$i" "${d##*/}" "${OPENAI_MODEL_DISPLAY_NAME:-${OPENAI_MODEL:-${EDGE_MODEL:-?}}}" \
        "$BENCHMARK_PROFILE" "$BENCHMARK_TYPE" "$finished" "$total" "$unit" "$pending" \
        "$( (( retry )) && echo " (retrying $retry after infra errors)")" "$(date -r "$last" '+%F %H:%M')"
    )
  done
  read -r -p "Resume which run? [1-$i, or N to start a new benchmark] (N): " answer
  case "${answer,,}" in
    ""|n|new) return 0 ;;
    *[!0-9]*) echo "Enter a run number or N." >&2; exit 2 ;;
  esac
  (( answer >= 1 && answer <= i )) || { echo "Enter a run number or N." >&2; exit 2; }
  RESUME_DIR=${dirs[answer - 1]}
  # shellcheck disable=SC1091
  source "$RESUME_DIR/resume.env"
  echo "Resuming ${RESUME_DIR##*/} with its saved settings."
}
[[ -t 0 && "$MODE" == run ]] && offer_resume
# A resumed run reuses the saved settings instead of prompting again.
INTERACTIVE=0
[[ -t 0 && -z "$RESUME_DIR" ]] && INTERACTIVE=1

# Settings a resumed run must reuse (the API key is never stored).
save_resume_env() {  # dir url-var url model-var model display-name perf-steps
  {
    printf '%s=%q\n' BENCHMARK_PROFILE "$BENCHMARK_PROFILE" BENCHMARK_TYPE "$BENCHMARK_TYPE" \
      SWE_TASK_COUNT "$SWE_TASK_COUNT" TERMINAL_TASK_COUNT "$TERMINAL_TASK_COUNT" REASONING_TASK_COUNT "$REASONING_TASK_COUNT" \
      OPENAI_REASONING_EFFORT "${OPENAI_REASONING_EFFORT:-}" \
      OPENAI_MODEL_MAX_INPUT_TOKENS "${OPENAI_MODEL_MAX_INPUT_TOKENS:-}" OPENAI_MODEL_MAX_OUTPUT_TOKENS "${OPENAI_MODEL_MAX_OUTPUT_TOKENS:-}" \
      OPENAI_MODEL_DISPLAY_NAME "$6" RESUME_PERF_TOTAL "$7" "$2" "$3" "$4" "$5"
  } > "$1/resume.env"
}

RAM_GIB=$(awk '/MemTotal:/ {printf "%d", ($2 + 1048575) / 1048576}' /proc/meminfo 2>/dev/null || echo 0)
SUGGESTED_PROFILE=advanced
(( RAM_GIB > 0 && RAM_GIB <= 32 )) && SUGGESTED_PROFILE=edge
# Quick and Vals public proxy tests exist only for Advanced.
[[ "${BENCHMARK_TYPE:-}" == quick || "${BENCHMARK_TYPE:-}" == vals-public ]] && SUGGESTED_PROFILE=advanced
BENCHMARK_PROFILE="${BENCHMARK_PROFILE:-$SUGGESTED_PROFILE}"
BENCHMARK_TYPE="${BENCHMARK_TYPE:-both}"
SWE_TASK_COUNT="${SWE_TASK_COUNT:-10}"
TERMINAL_TASK_COUNT="${TERMINAL_TASK_COUNT:-10}"
REASONING_TASK_COUNT="${REASONING_TASK_COUNT:-5}"
MODEL_DISPLAY_INPUT="${OPENAI_MODEL_DISPLAY_NAME:-}"
if (( INTERACTIVE )); then
  printf 'Benchmark profile (detected %s GiB RAM; suggested %s):\n  1. Edge Device Benchmark\n  2. Advanced Systems Benchmark\n' "$RAM_GIB" "$SUGGESTED_PROFILE"
  read -r -p "Select [$BENCHMARK_PROFILE]: " answer
  BENCHMARK_PROFILE="${answer:-$BENCHMARK_PROFILE}"
  if [[ "$MODE" == run ]]; then
    printf 'Benchmark content:\n  1. Performance\n  2. Capability\n  3. Complete (performance + capability)\n  4. Quick test (Advanced only)\n  5. Vals public proxy (Advanced only, five Q&A domains, no Docker, about 70 min)\n'
    read -r -p "Select [$BENCHMARK_TYPE]: " answer
    BENCHMARK_TYPE="${answer:-$BENCHMARK_TYPE}"
    case "${BENCHMARK_TYPE,,}" in
      performance|p|1) BENCHMARK_TYPE=performance ;;
      tasks|task|capability|c|t|2) BENCHMARK_TYPE=tasks ;;
      both|complete|b|3) BENCHMARK_TYPE=both ;;
      quick|q|4) BENCHMARK_TYPE=quick ;;
      vals-public|vals_public|vals|v|5) BENCHMARK_TYPE=vals-public ;;
      *) echo "Benchmark content must be performance, capability, complete, quick or vals-public." >&2; exit 2 ;;
    esac
    if [[ "${BENCHMARK_PROFILE,,}" =~ ^(advanced|dgx|high|2)$ && "$BENCHMARK_TYPE" != performance && "$BENCHMARK_TYPE" != quick && "$BENCHMARK_TYPE" != vals-public ]]; then
      read -r -p "SWE-bench task count [${SWE_TASK_COUNT}, max 10]: " answer
      SWE_TASK_COUNT="${answer:-$SWE_TASK_COUNT}"
      read -r -p "Terminal-Bench task count [${TERMINAL_TASK_COUNT}, max 10]: " answer
      TERMINAL_TASK_COUNT="${answer:-$TERMINAL_TASK_COUNT}"
      read -r -p "LiveBench task count [${REASONING_TASK_COUNT}, max 5]: " answer
      REASONING_TASK_COUNT="${answer:-$REASONING_TASK_COUNT}"
    fi
  fi
fi
case "${BENCHMARK_PROFILE,,}" in
  edge|local|low|1) BENCHMARK_PROFILE=edge ;;
  advanced|dgx|high|2) BENCHMARK_PROFILE=advanced ;;
  *) echo "BENCHMARK_PROFILE must be edge or advanced." >&2; exit 2 ;;
esac
case "${BENCHMARK_TYPE,,}" in
  performance|p|1) BENCHMARK_TYPE=performance ;;
  tasks|task|capability|c|2) BENCHMARK_TYPE=tasks ;;
  both|complete|b|3) BENCHMARK_TYPE=both ;;
  quick|q|4) BENCHMARK_TYPE=quick ;;
  vals-public|vals_public|vals|v|5) BENCHMARK_TYPE=vals-public ;;
  *) echo "BENCHMARK_TYPE must be performance, capability, complete, quick or vals-public." >&2; exit 2 ;;
esac
[[ "$BENCHMARK_PROFILE" == edge && ( "$BENCHMARK_TYPE" == quick || "$BENCHMARK_TYPE" == vals-public ) ]] && { echo "Quick and Vals public proxy tests require BENCHMARK_PROFILE=advanced." >&2; exit 2; }

if [[ "$BENCHMARK_PROFILE" == edge ]]; then
  EDGE_API_INPUT="${EDGE_BASE_URL:-${OPENAI_BASE_URL:-}}"
  EDGE_MODEL_ID="${EDGE_MODEL:-${OPENAI_MODEL:-}}"
  API_KEY="${OPENAI_API_KEY:-dummy}"
  if (( INTERACTIVE )); then
    read -r -p "OpenAI API URL (/v1 or /v1/chat/completions)${EDGE_API_INPUT:+ [$EDGE_API_INPUT]}: " answer
    EDGE_API_INPUT="${answer:-$EDGE_API_INPUT}"
    read -r -p "Model ID${EDGE_MODEL_ID:+ [$EDGE_MODEL_ID]}: " answer
    EDGE_MODEL_ID="${answer:-$EDGE_MODEL_ID}"
    if [[ "$MODE" == run ]]; then
      EDGE_MODEL_NAME="${MODEL_DISPLAY_INPUT:-${EDGE_MODEL_ID##*/}}"
      read -r -p "Display model name [$EDGE_MODEL_NAME]: " answer
      EDGE_MODEL_NAME="${answer:-$EDGE_MODEL_NAME}"
    fi
  fi
  EDGE_MODEL_NAME="${EDGE_MODEL_NAME:-${MODEL_DISPLAY_INPUT:-${EDGE_MODEL_ID##*/}}}"
  [[ -n "$EDGE_API_INPUT" && -n "$EDGE_MODEL_ID" ]] || { echo "Endpoint and model are required. Set EDGE_BASE_URL and EDGE_MODEL for non-interactive runs." >&2; exit 2; }
  EDGE_API_BASE="${EDGE_API_INPUT%/}"
  EDGE_API_BASE="${EDGE_API_BASE%/chat/completions}"
  python3 -m py_compile "$BENCH_DIR/edge_benchmark.py"
  python3 "$BENCH_DIR/edge_benchmark.py" --self-test
  python3 "$BENCH_DIR/edge_benchmark.py" --preflight --runner-mode openai \
    --api-base-url "$EDGE_API_BASE" --api-key "$API_KEY" --model "$EDGE_MODEL_ID"
  if [[ "$MODE" == --preflight ]]; then
    echo "Edge preflight passed: $EDGE_MODEL_ID at $EDGE_API_BASE"
    exit 0
  fi
  EDGE_RUN_DIR="${RESUME_DIR:-$ROOT/benchmark-results/$(date -u +%Y%m%dT%H%M%SZ)}"
  mkdir -p "$EDGE_RUN_DIR"
  save_resume_env "$EDGE_RUN_DIR" EDGE_BASE_URL "$EDGE_API_INPUT" EDGE_MODEL "$EDGE_MODEL_ID" "$EDGE_MODEL_NAME" 0
  edge_args=(--model "$EDGE_MODEL_ID" --display-name "$EDGE_MODEL_NAME" --benchmark-type "$BENCHMARK_TYPE" --runner-mode openai --api-base-url "$EDGE_API_BASE" --api-key "$API_KEY" --runtime-name "${EDGE_RUNTIME_NAME:-llama.cpp}" --result-dir "$EDGE_RUN_DIR" -t "${EDGE_THREADS:-8}" -c "${EDGE_CONTEXT_TOKENS:-32768}")
  [[ -n "$RESUME_DIR" ]] && edge_args+=(--resume)
  echo "Running Edge Device Benchmark for $EDGE_MODEL_NAME ($BENCHMARK_TYPE); results: $EDGE_RUN_DIR"
  exec python3 "$BENCH_DIR/edge_benchmark.py" "${edge_args[@]}"
fi

API_INPUT="${OPENAI_BASE_URL:-}"
MODEL_INPUT="${OPENAI_MODEL:-}"
if (( INTERACTIVE )); then
  read -r -p "OpenAI API URL (/v1 or /v1/chat/completions)${API_INPUT:+ [$API_INPUT]}: " answer
  API_INPUT="${answer:-$API_INPUT}"
  read -r -p "Model ID${MODEL_INPUT:+ [$MODEL_INPUT]}: " answer
  MODEL_INPUT="${answer:-$MODEL_INPUT}"
  if [[ "$MODE" == run ]]; then
    MODEL_DISPLAY_NAME="${MODEL_DISPLAY_INPUT:-${MODEL_INPUT##*/}}"
    read -r -p "Display model name [$MODEL_DISPLAY_NAME]: " answer
    MODEL_DISPLAY_NAME="${answer:-$MODEL_DISPLAY_NAME}"
  fi
fi
MODEL_DISPLAY_NAME="${MODEL_DISPLAY_NAME:-${MODEL_DISPLAY_INPUT:-${MODEL_INPUT##*/}}}"
if [[ "$BENCHMARK_TYPE" == performance ]]; then
  SWE_TASK_COUNT=0
  TERMINAL_TASK_COUNT=0
  REASONING_TASK_COUNT=0
fi
[[ -n "$API_INPUT" && -n "$MODEL_INPUT" ]] || {
  echo "Endpoint and model are required. Set OPENAI_BASE_URL and OPENAI_MODEL for non-interactive runs." >&2
  exit 2
}

STATE_DIR="$BENCH_DIR/.state"
VENV="$BENCH_DIR/.venv"
PY=python3
MINI_EXTRA="$VENV/bin/mini-extra"
HARBOR="$VENV/bin/harbor"
REASONING="$BENCH_DIR/reasoning.py"
REASONING_QUESTIONS="$BENCH_DIR/reasoning-questions.json"
VALS_PUBLIC="$BENCH_DIR/vals_public.py"
VALS_PUBLIC_CASES="$BENCH_DIR/vals-public-cases.json"
VALS_REPORT="$ROOT/docs/vals-ai-benchmark-report.md"
MEASURE_API="$BENCH_DIR/measure-api.py"
RESULT_BUILDER="$BENCH_DIR/result.py"
RESULT_TEMPLATE="$ROOT/resultschema.json"
REPORT_BUILDER="$BENCH_DIR/report.py"
REPORT_TEMPLATE="$BENCH_DIR/report-template.html"
RESULTS_ROOT="$ROOT/benchmark-results"
API_BASE="${API_INPUT%/}"
API_BASE="${API_BASE%/chat/completions}"
API_KEY="${OPENAI_API_KEY:-dummy}"
MODEL_ID="$MODEL_INPUT"
MODEL_NAME="$MODEL_DISPLAY_NAME"
RESULT_BASENAME="${MODEL_NAME//[^[:alnum:]._-]/-}"
[[ -n "$RESULT_BASENAME" ]] || RESULT_BASENAME=model
MODEL_MAX_INPUT_TOKENS="${OPENAI_MODEL_MAX_INPUT_TOKENS:-131072}"
MODEL_CONTEXT_TOKENS="$MODEL_MAX_INPUT_TOKENS"
MODEL_CONTEXT_SOURCE=$([[ -n "${OPENAI_MODEL_MAX_INPUT_TOKENS:-}" ]] && echo configured || echo fallback)
MODEL_MAX_OUTPUT_TOKENS="${OPENAI_MODEL_MAX_OUTPUT_TOKENS:-65536}"
REASONING_EFFORT="${OPENAI_REASONING_EFFORT:-}"
START_FREE_BYTES=$((75 * 1024 * 1024 * 1024))
TASK_FREE_BYTES=$((20 * 1024 * 1024 * 1024))
SWE_SECONDS=$((25 * 60))
SWE_GRADER_SECONDS=$((10 * 60))
TERMINAL_SECONDS=$((20 * 60))
REASONING_SECONDS=$((10 * 60))
REASONING_MAX_TOKENS=8192
SWE_DIFFICULTY="15 min - 1 hour"
TERMINAL_TIMEOUT_MULTIPLIER=1.2
ORACLE_TASK=cancel-async-tasks
PERFORMANCE_SECONDS="${OPENAI_PERFORMANCE_TIMEOUT_SECONDS:-1800}"
PERFORMANCE_RUNS="${OPENAI_PERFORMANCE_RUNS:-3}"
PERFORMANCE_WARMUP_RUNS="${OPENAI_PERFORMANCE_WARMUP_RUNS:-1}"
PREFILL_PROMPT_LINES="${OPENAI_PREFILL_PROMPT_LINES:-800}"
PREFILL_MAX_TOKENS="${OPENAI_PREFILL_MAX_TOKENS:-8}"
DECODE_PROMPT_LINES="${OPENAI_DECODE_PROMPT_LINES:-0}"
DECODE_MAX_TOKENS="${OPENAI_DECODE_MAX_TOKENS:-512}"
AGGREGATE_CONCURRENCIES_INPUT="${OPENAI_AGGREGATE_CONCURRENCIES:-${OPENAI_AGGREGATE_CONCURRENCY:-4 8 12}}"
read -r -a AGGREGATE_CONCURRENCIES <<< "$AGGREGATE_CONCURRENCIES_INPUT"
MODEL_INFO=$(printf '{"max_input_tokens":%s,"max_output_tokens":%s,"input_cost_per_token":0,"output_cost_per_token":0}' \
  "$MODEL_MAX_INPUT_TOKENS" "$MODEL_MAX_OUTPUT_TOKENS")

SWE_TASKS=(
  astropy__astropy-12907
  django__django-11141
  pydata__xarray-3677
  sympy__sympy-15599
  matplotlib__matplotlib-23299
  scikit-learn__scikit-learn-14087
  sphinx-doc__sphinx-11445
  pytest-dev__pytest-10051
  pylint-dev__pylint-6528
  mwaskom__seaborn-3187
)
TERMINAL_TASKS=(
  kv-store-grpc
  configure-git-webserver
  nginx-request-logging
  query-optimize
  db-wal-recovery
  git-multibranch
  git-leak-recovery
  build-cython-ext
  custom-memory-heap-crash
  cancel-async-tasks
)
REASONING_TASKS=(
  livebench-zebra_puzzle-26
  livebench-zebra_puzzle-30
  livebench-zebra_puzzle-46
  livebench-spatial-88
  livebench-spatial-90
)
VALS_LEGAL_TASKS=()
VALS_FINANCE_TASKS=()
VALS_HEALTH_TASKS=()
VALS_MATH_TASKS=()
VALS_SCIENCE_TASKS=()
# Per-case wall-clock cap (s) and reply cap (tokens). Thinking models need room: 512 tokens truncated every one.
# A responsive model finishes in about 65-75 min (finance, AIME and engineering questions are most of it); the deadline is the hard stop for slow ones.
declare -A VALS_SECONDS=([legal]=120 [finance]=420 [health]=120 [math]=420 [science]=240)
declare -A VALS_TOKENS=([legal]=4096 [finance]=10240 [health]=4096 [math]=16384 [science]=8192)
VALS_DEADLINE_SECONDS=6000
(( ${#SWE_TASKS[@]} == 10 && ${#TERMINAL_TASKS[@]} == 10 && ${#REASONING_TASKS[@]} == 5 )) || {
  echo "Expected 10 SWE, 10 Terminal and 5 reasoning tasks." >&2
  exit 2
}
[[ "$SWE_TASK_COUNT" =~ ^[0-9]+$ ]] && (( SWE_TASK_COUNT <= 10 )) || { echo "SWE-bench task count must be 0-10." >&2; exit 2; }
[[ "$TERMINAL_TASK_COUNT" =~ ^[0-9]+$ ]] && (( TERMINAL_TASK_COUNT <= 10 )) || { echo "Terminal-Bench task count must be 0-10." >&2; exit 2; }
[[ "$REASONING_TASK_COUNT" =~ ^[0-9]+$ ]] && (( REASONING_TASK_COUNT <= 5 )) || { echo "LiveBench task count must be 0-5." >&2; exit 2; }
[[ "$MODEL_MAX_INPUT_TOKENS" =~ ^[1-9][0-9]*$ ]] || { echo "Model input token limit must be a positive integer." >&2; exit 2; }
[[ "$MODEL_MAX_OUTPUT_TOKENS" =~ ^[1-9][0-9]*$ ]] || { echo "Model output token limit must be a positive integer." >&2; exit 2; }
[[ "$PERFORMANCE_RUNS" =~ ^[1-9][0-9]*$ ]] || { echo "Performance runs must be a positive integer." >&2; exit 2; }
[[ "$PERFORMANCE_WARMUP_RUNS" =~ ^[0-9]+$ ]] || { echo "Performance warm-up runs cannot be negative." >&2; exit 2; }
for concurrency in "${AGGREGATE_CONCURRENCIES[@]}"; do
  [[ "$concurrency" =~ ^[1-9][0-9]*$ ]] || { echo "Aggregate concurrencies must be positive integers." >&2; exit 2; }
done
SWE_TASKS=("${SWE_TASKS[@]:0:SWE_TASK_COUNT}")
TERMINAL_TASKS=("${TERMINAL_TASKS[@]:0:TERMINAL_TASK_COUNT}")
REASONING_TASKS=("${REASONING_TASKS[@]:0:REASONING_TASK_COUNT}")
if [[ "$BENCHMARK_TYPE" == quick ]]; then
  # Fixed task set keeps quick runs comparable across models.
  # Equal per-stage limits keep results independent of task order.
  SWE_TASKS=(django__django-11179 sympy__sympy-16886 pytest-dev__pytest-7982 pallets__flask-5014)
  TERMINAL_TASKS=(fix-git prove-plus-comm kv-store-grpc nginx-request-logging)
  REASONING_TASKS=(livebench-zebra_puzzle-26 livebench-spatial-88)
  SWE_TASK_COUNT=4 TERMINAL_TASK_COUNT=4 REASONING_TASK_COUNT=2
  SWE_DIFFICULTY="<15 min fix"
  SWE_SECONDS=600 SWE_GRADER_SECONDS=300 TERMINAL_SECONDS=480 REASONING_SECONDS=420
  # Harbor's agent timeout leaves time for its verifier inside the task cap.
  TERMINAL_TIMEOUT_MULTIPLIER=0.4
  START_FREE_BYTES=$((30 * 1024 * 1024 * 1024))
  ORACLE_TASK=fix-git
elif [[ "$BENCHMARK_TYPE" == vals-public ]]; then
  # Q&A only: every task is one chat-completions request, so no Docker, Harbor or SWE-bench is involved.
  SWE_TASKS=()
  TERMINAL_TASKS=()
  REASONING_TASKS=()
  VALS_LEGAL_TASKS=(
    legal-abercrombie-6 legal-abercrombie-15
    legal-decision-section-0 legal-decision-section-1
    legal-citizenship-0 legal-citizenship-1
    legal-proa-0 legal-proa-1
    legal-hearsay-0 legal-hearsay-33
    legal-personal-jurisdiction-0 legal-personal-jurisdiction-3
    legal-diversity-1-0 legal-diversity-1-4
    legal-ucc-0 legal-ucc-1
  )
  VALS_FINANCE_TASKS=(
    finance-public-1 finance-public-2 finance-public-3 finance-public-4 finance-public-5
    finance-public-6 finance-public-7 finance-public-8 finance-public-9 finance-public-10
    finance-public-11 finance-public-12 finance-public-13 finance-public-14
  )
  VALS_HEALTH_TASKS=(
    medqa-test-0 medqa-test-1 medqa-test-2 medqa-test-3
    medqa-test-4 medqa-test-5 medqa-test-6 medqa-test-7
    medqa-test-8 medqa-test-10 medqa-test-11 medqa-test-12
  )
  VALS_MATH_TASKS=(
    aime-2024-4 aime-2024-22
    aime-2025-6 aime-2025-8 aime-2025-11 aime-2025-14 aime-2025-24 aime-2025-26 aime-2025-29
  )
  VALS_SCIENCE_TASKS=(
    mmlu-pro-9058 mmlu-pro-9060 mmlu-pro-3545 mmlu-pro-2826
    mmlu-pro-11374 mmlu-pro-11379 mmlu-pro-11382 mmlu-pro-11384 mmlu-pro-11386
  )
  SWE_TASK_COUNT=0 TERMINAL_TASK_COUNT=0 REASONING_TASK_COUNT=0
fi
# Only SWE-bench and Terminal-Bench need Docker and the Harbor/mini-swe-agent venv; performance and Vals Q&A runs need Python and the API.
NEEDS_DOCKER=1
[[ "$BENCHMARK_TYPE" == performance || "$BENCHMARK_TYPE" == vals-public ]] && NEEDS_DOCKER=0
SWE_TOTAL_SECONDS=$((SWE_SECONDS + SWE_GRADER_SECONDS))
TOTAL_TASKS=$((${#SWE_TASKS[@]} + ${#TERMINAL_TASKS[@]} + ${#REASONING_TASKS[@]} + ${#VALS_LEGAL_TASKS[@]} + ${#VALS_FINANCE_TASKS[@]} + ${#VALS_HEALTH_TASKS[@]} + ${#VALS_MATH_TASKS[@]} + ${#VALS_SCIENCE_TASKS[@]}))
TASK_INDEX=0
GLOBAL_DEADLINE=0

check_task_limits() {
  if (( ${#SWE_TASKS[@]} + ${#TERMINAL_TASKS[@]} > 0 && MODEL_MAX_INPUT_TOKENS < 16384 )); then
    echo "Capability benchmark needs at least 16384 input tokens for SWE/Terminal agents; configured $MODEL_MAX_INPUT_TOKENS. Set OPENAI_MODEL_MAX_INPUT_TOKENS to a supported value (32768 recommended)." >&2
    exit 2
  fi
  if (( TOTAL_TASKS > 0 && MODEL_MAX_OUTPUT_TOKENS < 4096 )); then
    echo "Capability benchmark needs at least 4096 output tokens; configured $MODEL_MAX_OUTPUT_TOKENS. Remove OPENAI_MODEL_MAX_OUTPUT_TOKENS or set it to a supported value (8192 recommended)." >&2
    exit 2
  fi
}
check_task_limits

RUN_ID=${RESUME_DIR##*/}
[[ -n "$RUN_ID" ]] || RUN_ID=$(date -u +%Y%m%dT%H%M%SZ)
RUN_DIR="$RESULTS_ROOT/$RUN_ID"
PREFLIGHT_DIR="$RUN_DIR/preflight"
RESULT_FILE="$RUN_DIR/$RESULT_BASENAME-result.json"
REPORT_FILE="$RUN_DIR/$RESULT_BASENAME-result.html"
mkdir -p "$STATE_DIR/config" "$STATE_DIR/cache" "$STATE_DIR/huggingface" "$PREFLIGHT_DIR"
export XDG_CONFIG_HOME="$STATE_DIR/config"
export XDG_CACHE_HOME="$STATE_DIR/cache"
export HF_HOME="$STATE_DIR/huggingface"
export OPENAI_API_KEY="$API_KEY"
exec > >(tee -a "$RUN_DIR/run.log") 2>&1

RUN_FINALIZED=0
# Set once preflight passed: a resumed run that dies in preflight must not overwrite its good result with a degraded one.
RUN_STARTED=0
TASK_HEARTBEAT_PID=""
ACTIVE_LOG=""

stop_task_heartbeat() {
  if [[ -n "$TASK_HEARTBEAT_PID" ]]; then
    kill "$TASK_HEARTBEAT_PID" 2>/dev/null || true
    wait "$TASK_HEARTBEAT_PID" 2>/dev/null || true
    TASK_HEARTBEAT_PID=""
  fi
}

on_exit() {
  local rc=$? status=failed
  stop_task_heartbeat
  if (( RUN_FINALIZED == 0 && RUN_STARTED )) && [[ "$MODE" == run && -s "$RUN_DIR/task-results.tsv" ]] && command -v "$PY" >/dev/null 2>&1; then
    (( rc == 130 || rc == 143 )) && status=interrupted
    if generate_result "$status"; then
      generate_report || true
    fi
  fi
}

trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

log_event() {
  printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*"
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

free_bytes() {
  df -B1 --output=avail "$ROOT" | awk 'NR == 2 {print $1}'
}

require_free() {
  local required=$1 available
  available=$(free_bytes)
  (( available >= required )) || die "Only $((available / 1024 / 1024 / 1024)) GiB is free; $((required / 1024 / 1024 / 1024)) GiB is required. No Docker data was removed."
}

ensure_tools() {
  local command
  for command in curl timeout awk python3; do
    command -v "$command" >/dev/null || die "Missing required command: $command"
  done
  if (( NEEDS_DOCKER )); then
    command -v docker >/dev/null || die "Missing required command: docker"
    if [[ ! -x "$VENV/bin/python" || ! -x "$MINI_EXTRA" || ! -x "$HARBOR" ]]; then
      python3 -m venv "$VENV"
      "$VENV/bin/python" -m pip install --disable-pip-version-check -r "$BENCH_DIR/requirements.txt"
    fi
    PY="$VENV/bin/python"
  fi
  [[ -f "$RESULT_TEMPLATE" && -f "$REPORT_TEMPLATE" ]] || die "Missing result or report template."
  "$PY" -m py_compile "$RESULT_BUILDER" "$REPORT_BUILDER" "$MEASURE_API"
  "$PY" "$RESULT_BUILDER" --self-test
  "$PY" "$REPORT_BUILDER" --self-test
  "$PY" "$REASONING" --questions "$REASONING_QUESTIONS" --self-test
  if [[ "$BENCHMARK_TYPE" == vals-public ]]; then
    [[ -f "$VALS_PUBLIC" && -f "$VALS_PUBLIC_CASES" && -f "$VALS_REPORT" ]] || die "Missing Vals public proxy script, cases, or report."
    "$PY" -m py_compile "$VALS_PUBLIC"
    "$PY" "$VALS_PUBLIC" --cases "$VALS_PUBLIC_CASES" --self-test
    "$PY" "$VALS_PUBLIC" --cases "$VALS_PUBLIC_CASES" --validate-report "$VALS_REPORT"
    "$PY" "$VALS_PUBLIC" --cases "$VALS_PUBLIC_CASES" --write-manifest "$PREFLIGHT_DIR/vals-public-manifest.json"
  fi
}

validate_api() {
  local detected_context
  curl --fail --silent --show-error --max-time 15 \
    -H "Authorization: Bearer $API_KEY" "$API_BASE/models" > "$PREFLIGHT_DIR/models.json" 2> "$PREFLIGHT_DIR/models-error.log" || true
  detected_context=$("$PY" - "$PREFLIGHT_DIR/models.json" "$MODEL_ID" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except (OSError, json.JSONDecodeError):
    raise SystemExit
for model in data.get("data", []):
    if model.get("id") == sys.argv[2]:
        value = model.get("max_model_len") or model.get("max_context_length")
        if isinstance(value, int) and value > 0:
            print(value)
        break
PY
  )
  if [[ "$detected_context" =~ ^[1-9][0-9]*$ ]]; then
    MODEL_CONTEXT_TOKENS="$detected_context"
    MODEL_CONTEXT_SOURCE="api_models"
    (( MODEL_MAX_OUTPUT_TOKENS < detected_context )) || die "Output limit $MODEL_MAX_OUTPUT_TOKENS is not smaller than the model context $detected_context."
    if [[ -z "${OPENAI_MODEL_MAX_INPUT_TOKENS:-}" ]]; then
      MODEL_MAX_INPUT_TOKENS=$((detected_context - MODEL_MAX_OUTPUT_TOKENS))
      if (( MODEL_MAX_INPUT_TOKENS > 262144 )); then
        MODEL_MAX_INPUT_TOKENS=262144
      fi
    fi
    (( MODEL_MAX_INPUT_TOKENS + MODEL_MAX_OUTPUT_TOKENS <= detected_context )) || die "Input $MODEL_MAX_INPUT_TOKENS + output $MODEL_MAX_OUTPUT_TOKENS exceeds the model context $detected_context."
    MODEL_INFO=$(printf '{"max_input_tokens":%s,"max_output_tokens":%s,"input_cost_per_token":0,"output_cost_per_token":0}' \
      "$MODEL_MAX_INPUT_TOKENS" "$MODEL_MAX_OUTPUT_TOKENS")
  fi
  curl --fail --silent --show-error --max-time 120 "$API_BASE/chat/completions" \
    -H "Authorization: Bearer $API_KEY" \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"$MODEL_ID\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with READY only.\"}],\"max_tokens\":256,\"temperature\":0}" \
    > "$PREFLIGHT_DIR/chat.json"
  "$PY" - "$PREFLIGHT_DIR/chat.json" "$MODEL_ID" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
choices = data.get("choices") or []
if not choices:
    raise SystemExit("Chat smoke test returned no choices")
returned_model = data.get("model")
if returned_model and returned_model != sys.argv[2]:
    raise SystemExit(f"Requested model {sys.argv[2]!r}, but endpoint returned {returned_model!r}")
message = choices[0].get("message") or {}
content = message.get("content") or ""
reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
if not any(isinstance(part, str) and part.strip() for part in (content, reasoning)) and not message.get("tool_calls"):
    raise SystemExit("Chat smoke test returned no assistant output")
if "READY" not in content.upper():
    print("Warning: model did not follow the READY instruction; performance testing can continue.", file=sys.stderr)
PY
}

validate_swe_tasks() {
  "$PY" - "$PREFLIGHT_DIR/swe-tasks.tsv" "$SWE_DIFFICULTY" "${SWE_TASKS[@]}" <<'PY'
import sys
from datasets import load_dataset

output, expected, *wanted = sys.argv[1:]
rows = {row["instance_id"]: row for row in load_dataset("princeton-nlp/SWE-bench_Verified", split="test")}
with open(output, "w") as f:
    f.write("instance_id\tdifficulty\n")
    for task in wanted:
        if task not in rows:
            raise SystemExit(f"Missing SWE-bench task: {task}")
        difficulty = rows[task].get("difficulty")
        if difficulty != expected:
            raise SystemExit(f"{task} difficulty is {difficulty!r}, expected {expected!r}")
        f.write(f"{task}\t{difficulty}\n")
PY
}

swe_image() {
  local compatible=${1/__/_1776_}
  printf 'docker.io/swebench/sweb.eval.x86_64.%s:latest\n' "${compatible,,}"
}

harbor_model_args() {
  local args=(-a terminus-2 -m "openai/$MODEL_ID" --ak "api_base=$API_BASE" --ak max_turns=100 --ak "model_info=$MODEL_INFO" --agent-timeout-multiplier "$TERMINAL_TIMEOUT_MULTIPLIER" -n 1 -k 1 -r 0 -y)
  [[ -n "$REASONING_EFFORT" ]] && args+=(--ak "reasoning_effort=$REASONING_EFFORT")
  printf '%s\n' "${args[@]}"
}

run_preflight_step() {
  local label=$1 limit=$2 log_path=$3 rc=0 start
  shift 3
  start=$(date +%s)
  (
    while sleep 60; do
      log_event "$label | elapsed=$(( $(date +%s) - start ))s limit=${limit}s | log=${log_path#$RUN_DIR/}"
    done
  ) &
  TASK_HEARTBEAT_PID=$!
  timeout --foreground --signal=INT --kill-after=30s "$limit" "$@" > "$log_path" 2>&1 || rc=$?
  stop_task_heartbeat
  if (( rc != 0 )); then
    [[ -s "$log_path" ]] && tail -n 10 "$log_path" >&2
    (( rc == 124 )) && die "$label exceeded ${limit}s; check ${log_path#$RUN_DIR/}."
    die "$label failed with exit $rc; check ${log_path#$RUN_DIR/}."
  fi
}

prepare_images() {
  local task image container index=0
  # Harbor job names are fixed; a resumed run dir still holds the previous preflight's jobs.
  rm -rf "$PREFLIGHT_DIR/harbor-install" "$PREFLIGHT_DIR/harbor-oracle"
  mkdir -p "$PREFLIGHT_DIR/swe-images" "$PREFLIGHT_DIR/harbor-install"
  for task in "${SWE_TASKS[@]}"; do
    index=$((index + 1))
    log_event "[PREFLIGHT SWE $index/${#SWE_TASKS[@]}] Preparing $task"
    require_free "$TASK_FREE_BYTES"
    image=$(swe_image "$task")
    docker pull "$image" > "$PREFLIGHT_DIR/swe-images/$task.log" 2>&1
    container="model-benchmark-preflight-${task//__/-}"
    docker rm -f "$container" >/dev/null 2>&1 || true
    timeout --foreground --kill-after=30s 600 docker run --name "$container" --rm "$image" true \
      > "$PREFLIGHT_DIR/swe-images/$task-start.log" 2>&1 || {
        docker rm -f "$container" >/dev/null 2>&1 || true
        die "SWE container startup failed: $task"
      }
    log_event "[PREFLIGHT SWE $index/${#SWE_TASKS[@]}] READY $task"
  done

  mapfile -t model_args < <(harbor_model_args)
  index=0
  for task in "${TERMINAL_TASKS[@]}"; do
    index=$((index + 1))
    log_event "[PREFLIGHT TERMINAL $index/${#TERMINAL_TASKS[@]}] Preparing $task"
    require_free "$TASK_FREE_BYTES"
    run_preflight_step "[PREFLIGHT TERMINAL $index/${#TERMINAL_TASKS[@]}] Still preparing $task" 300 \
      "$PREFLIGHT_DIR/harbor-install/$task.log" \
      "$HARBOR" run -d terminal-bench/terminal-bench-2-1 -i "terminal-bench/$task" "${model_args[@]}" \
      --delete --install-only --job-name "install-$task" -o "$PREFLIGHT_DIR/harbor-install"
    log_event "[PREFLIGHT TERMINAL $index/${#TERMINAL_TASKS[@]}] READY $task"
  done

  (( ${#TERMINAL_TASKS[@]} )) || return 0
  log_event "[PREFLIGHT] Running Harbor oracle smoke test on $ORACLE_TASK"
  run_preflight_step "[PREFLIGHT] Harbor oracle still running on $ORACLE_TASK" 600 \
    "$PREFLIGHT_DIR/harbor-oracle.log" \
    "$HARBOR" run -d terminal-bench/terminal-bench-2-1 -i "terminal-bench/$ORACLE_TASK" -a oracle -n 1 -k 1 -r 0 -y \
    --delete --job-name oracle-smoke -o "$PREFLIGHT_DIR/harbor-oracle"
  [[ $(json_outcome terminal "$PREFLIGHT_DIR/harbor-oracle") == pass ]] || die "Harbor oracle smoke test on $ORACLE_TASK did not receive reward 1; see ${PREFLIGHT_DIR#$RUN_DIR/}/harbor-oracle.log."
  log_event "[PREFLIGHT] Harbor oracle smoke test passed"
}

preflight() {
  PREFLIGHT_START=$(date +%s)
  echo "Preflight artifacts: $PREFLIGHT_DIR"
  echo "Configuration: $CONFIG_FILE"
  echo "API endpoint: $API_BASE"
  echo "Model ID: $MODEL_ID"
  echo "Display model name: $MODEL_NAME"
  echo "Benchmark type: $BENCHMARK_TYPE"
  [[ -n "$REASONING_EFFORT" ]] && echo "Reasoning effort: $REASONING_EFFORT"
  quick_banner
  log_event "[PREFLIGHT] Checking local tools and Python runtime"
  ensure_tools
  if (( NEEDS_DOCKER )); then
    [[ $(uname -m) == x86_64 ]] || die "SWE-bench Docker evaluation requires x86_64."
    require_free "$START_FREE_BYTES"
    log_event "[PREFLIGHT] Checking local Docker"
    docker info --format '{{.Architecture}} {{.ServerVersion}}' | tee "$PREFLIGHT_DIR/docker.txt"
  fi
  log_event "[PREFLIGHT] Validating model API"
  validate_api
  check_task_limits
  log_event "[PREFLIGHT] Model context=$MODEL_CONTEXT_TOKENS tokens (source=$MODEL_CONTEXT_SOURCE); benchmark input limit=$MODEL_MAX_INPUT_TOKENS"
  if [[ "$BENCHMARK_TYPE" != tasks && "$BENCHMARK_TYPE" != vals-public && "$MODEL_CONTEXT_SOURCE" != api_models ]]; then
    log_event "[PREFLIGHT] WARNING: API did not report a context limit; the benchmark setting is unverified. The fixed $PREFILL_PROMPT_LINES-line prefill prompt will not be reduced."
  fi
  if (( NEEDS_DOCKER )); then
    if (( ${#SWE_TASKS[@]} )); then
      log_event "[PREFLIGHT] Validating SWE-bench task selection"
      validate_swe_tasks
    fi
    log_event "[PREFLIGHT] Preparing benchmark images"
    prepare_images
    require_free "$TASK_FREE_BYTES"
  fi
  echo "Preflight passed in $(( $(date +%s) - PREFLIGHT_START ))s. Free disk: $(( $(free_bytes) / 1024 / 1024 / 1024 )) GiB"
}

generate_result() {
  local status=${1:-running}
  local measurement_args=() concurrency file
  # Measurements live in perf/*.json so a resumed run keeps what an earlier attempt measured.
  [[ -s "$RUN_DIR/perf/prefill.json" ]] && measurement_args+=(--prefill-measurement "$(<"$RUN_DIR/perf/prefill.json")")
  [[ -s "$RUN_DIR/perf/decode.json" ]] && measurement_args+=(--decode-measurement "$(<"$RUN_DIR/perf/decode.json")")
  for concurrency in "${AGGREGATE_CONCURRENCIES[@]}"; do
    file="$RUN_DIR/perf/aggregate-C$concurrency.json"
    [[ -s "$file" ]] && measurement_args+=(--aggregate-measurement "$(<"$file")")
  done
  "$PY" "$RESULT_BUILDER" \
    --run-dir "$RUN_DIR" \
    --template "$RESULT_TEMPLATE" \
    --output "$RESULT_FILE" \
    --status "$status" \
    --benchmark-mode "$BENCHMARK_TYPE" \
    --model-id "$MODEL_ID" \
    --model-name "$MODEL_NAME" \
    --api-base-url "$API_BASE" \
    --reasoning-effort "$REASONING_EFFORT" \
    --maximum-context-tokens "$MODEL_CONTEXT_TOKENS" \
    --benchmark-input-limit-tokens "$MODEL_MAX_INPUT_TOKENS" \
    --benchmark-output-limit-tokens "$MODEL_MAX_OUTPUT_TOKENS" \
    --context-source "$MODEL_CONTEXT_SOURCE" \
    "${measurement_args[@]}"
}

generate_report() {
  "$PY" "$REPORT_BUILDER" --input "$RESULT_FILE" --template "$REPORT_TEMPLATE" --output "$REPORT_FILE" >/dev/null
}

# Run one measure-api.py step and save its JSON to perf/<name>.json; a resumed run reuses the saved file.
measure_step() {  # name, log label, then extra measure-api.py args
  local label=$2 file="$RUN_DIR/perf/$1.json" out reasoning_args=()
  shift 2
  if [[ -s "$file" ]]; then
    log_event "[PERFORMANCE] $label: reusing the measurement saved by the previous attempt"
    return 0
  fi
  [[ -n "$REASONING_EFFORT" ]] && reasoning_args=(--reasoning-effort "$REASONING_EFFORT")
  log_event "[PERFORMANCE] $label: $PERFORMANCE_WARMUP_RUNS warm-up + $PERFORMANCE_RUNS measured"
  out=$(timeout --foreground --signal=INT --kill-after=30s "$PERFORMANCE_SECONDS" \
    "$PY" "$MEASURE_API" --endpoint "$API_BASE" --model "$MODEL_ID" "${reasoning_args[@]}" \
      --runs "$PERFORMANCE_RUNS" --warmup-runs "$PERFORMANCE_WARMUP_RUNS" "$@" --json-only) || return $?
  mkdir -p "$RUN_DIR/perf"
  printf '%s\n' "$out" > "$file"
  log_event "[PERFORMANCE] $label measurement complete"
}

measure_performance() {
  local concurrency
  measure_step prefill Prefill --prompt-lines "$PREFILL_PROMPT_LINES" --max-tokens "$PREFILL_MAX_TOKENS" || return $?
  measure_step decode Decode --prompt-lines "$DECODE_PROMPT_LINES" --max-tokens "$DECODE_MAX_TOKENS" || return $?
  for concurrency in "${AGGREGATE_CONCURRENCIES[@]}"; do
    measure_step "aggregate-C$concurrency" "Aggregate C$concurrency" \
      --prompt-lines "$DECODE_PROMPT_LINES" --max-tokens "$DECODE_MAX_TOKENS" --concurrency "$concurrency" || return $?
  done
}

quick_banner() {
  if [[ "$BENCHMARK_TYPE" == vals-public ]]; then
    log_event "[VALS PUBLIC] $TOTAL_TASKS tasks: Legal ${#VALS_LEGAL_TASKS[@]}, Finance ${#VALS_FINANCE_TASKS[@]}, Medical ${#VALS_HEALTH_TASKS[@]}, Math ${#VALS_MATH_TASKS[@]}, Science ${#VALS_SCIENCE_TASKS[@]}; Q&A only, no Docker; typical 65-75m, hard run limit $((VALS_DEADLINE_SECONDS / 60))m"
    log_event "[VALS PUBLIC] Finance is closed-book (no tools), judged against the public rubric by ${VALS_JUDGE_MODEL:-the model under test}. All output is labeled public_proxy — not Vals leaderboard comparable."
    return 0
  fi
  [[ "$BENCHMARK_TYPE" == quick ]] || return 0
  log_event "[QUICK] Quick test: ${#SWE_TASKS[@]} SWE + ${#TERMINAL_TASKS[@]} Terminal + ${#REASONING_TASKS[@]} LiveBench easiest tasks, then performance; about 60 min on a responsive model"
  log_event "[QUICK] SWE ($SWE_DIFFICULTY): ${SWE_TASKS[*]} | agent=${SWE_SECONDS}s + grader=${SWE_GRADER_SECONDS}s/task"
  log_event "[QUICK] Terminal (easy): ${TERMINAL_TASKS[*]} | fixed limit=${TERMINAL_SECONDS}s/task"
  log_event "[QUICK] LiveBench: ${REASONING_TASKS[*]} | fixed limit=${REASONING_SECONDS}s/task, max output=${REASONING_MAX_TOKENS} tokens"
  log_event "[QUICK] Every task receives the same limits within its suite. Quick pass rates are not comparable with full runs."
}

# Log one suite's totals; silent when the suite had no tasks.
log_suite_summary() {
  local line
  line=$(awk -F '\t' -v suite="$1" 'NR>1 && $3==suite {n++; p+=($9=="pass"); f+=($9=="fail"); u+=($9=="unscored"); t+=($9=="timeout"); e+=($9=="infra_error"); d+=$7}
    END {if (n) printf "[SUMMARY] [%s] pass=%d/%d fail=%d unscored=%d timeout=%d error=%d time=%ds", toupper(suite), p, n, f, u, t, e, d}' "$RUN_DIR/task-results.tsv")
  if [[ -n "$line" ]]; then log_event "$line"; fi
}

task_started() {
  local phase=$1 attempt=$2 suite=$3 task=$4 limit=$5 log_path=$6 started_epoch
  TASK_INDEX=$((TASK_INDEX + 1))
  ACTIVE_LOG=$log_path
  started_epoch=$(date +%s)
  printf 'phase\tattempt\tsuite\ttask\tstart_utc\ttimeout_seconds\n%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$phase" "$attempt" "$suite" "$task" "$(date -u +%FT%TZ)" "$limit" > "$RUN_DIR/active-task.tsv"
  log_event "[START $(printf '%02d' "$TASK_INDEX")/$TOTAL_TASKS] [${suite^^}] $task | limit=${limit}s | log=${log_path#$RUN_DIR/}"
  generate_result running
  (
    while sleep 60; do
      elapsed=$(($(date +%s) - started_epoch))
      log_event "[RUNNING $(printf '%02d' "$TASK_INDEX")/$TOTAL_TASKS] [${suite^^}] $task | elapsed=${elapsed}s left=$((limit - elapsed))s | log=${log_path#$RUN_DIR/}"
    done
  ) &
  TASK_HEARTBEAT_PID=$!
}

record_result() {
  local phase=$1 attempt=$2 suite=$3 task=$4 start=$5 end=$6 duration=$7 exit_code=$8 outcome=$9 label counts
  stop_task_heartbeat
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$@" >> "$RUN_DIR/task-results.tsv"
  : > "$RUN_DIR/active-task.tsv"
  case "$outcome" in
    pass) label=PASS ;;
    fail) label=FAIL ;;
    unscored) label=UNSCORED ;;
    timeout) label=TIMEOUT ;;
    *) label=ERROR ;;
  esac
  counts=$(awk -F '\t' 'NR>1 {done++; pass+=($9=="pass"); fail+=($9=="fail"); unscored+=($9=="unscored"); timeout+=($9=="timeout"); error+=($9=="infra_error")} END {printf "done=%d pass=%d fail=%d unscored=%d timeout=%d error=%d", done, pass, fail, unscored, timeout, error}' "$RUN_DIR/task-results.tsv")
  log_event "[$label $(printf '%02d' "$TASK_INDEX")/$TOTAL_TASKS] [${suite^^}] $task | duration=${duration}s | exit=$exit_code | $counts"
  if [[ ( "$outcome" == timeout || "$outcome" == infra_error ) && -s "$ACTIVE_LOG" ]]; then
    log_event "[DETAIL] [${suite^^}] $task | last lines of ${ACTIVE_LOG#$RUN_DIR/}:"
    tail -n 5 "$ACTIVE_LOG" | sed 's/^/    /'
  fi
  generate_result running
}

json_outcome() {
  "$PY" "$RESULT_BUILDER" --task-outcome "$1" "$2"
}

# Resumed runs: true (task numbering still advances) when an earlier attempt already recorded this task.
resume_skip() {
  [[ -n "$RESUME_DIR" ]] && awk -F '\t' -v s="$1" -v t="$2" 'NR > 1 && $3 == s && $4 == t {f = 1} END {exit !f}' "$RUN_DIR/task-results.tsv" || return 1
  TASK_INDEX=$((TASK_INDEX + 1))
  log_event "[SKIP $(printf '%02d' "$TASK_INDEX")/$TOTAL_TASKS] [${1^^}] $2 | already recorded by the previous attempt"
}

# Park a cut or infra-failed attempt's output so its stale preds.json/result.json can't pass for the new attempt.
fresh_dir() {
  [[ -d "$1" ]] && mv "$1" "$1.$(date +%s).prev"
  mkdir -p "$1"
}

bounded_limit() {
  local requested=$1 remaining
  if [[ "$BENCHMARK_TYPE" != vals-public || "$GLOBAL_DEADLINE" == 0 ]]; then
    echo "$requested"
    return
  fi
  remaining=$((GLOBAL_DEADLINE - $(date +%s)))
  (( remaining > 0 )) || die "Vals public proxy reached its $((VALS_DEADLINE_SECONDS / 60))-minute global limit. Partial results were preserved."
  (( remaining < requested )) && echo "$remaining" || echo "$requested"
}

run_swe() {
  local phase=$1 attempt=$2 task=$3 task_dir start end limit agent_rc=0 eval_rc=0 outcome agent_status
  local reasoning_args=()
  resume_skip swe "$task" && return 0
  task_dir="$RUN_DIR/$phase/swe/$task"
  fresh_dir "$task_dir"
  require_free "$TASK_FREE_BYTES"
  limit=$SWE_TOTAL_SECONDS
  start=$(date +%s)

  task_started "$phase" "$attempt" swe "$task" "$limit" "$task_dir/agent.log"
  [[ -n "$REASONING_EFFORT" ]] && reasoning_args=(-c "model.model_kwargs.reasoning_effort=$REASONING_EFFORT")
  set +e
  timeout --foreground --signal=INT --kill-after=60s "$SWE_SECONDS" \
    "$MINI_EXTRA" swebench --subset verified --split test --filter "^${task}$" --workers 1 \
      -c swebench.yaml -c "$BENCH_DIR/mini-swe.yaml" \
      -c "model.model_name=openai/$MODEL_ID" \
      -c "model.model_kwargs.api_base=$API_BASE" \
      -c "model.model_kwargs.api_key=$API_KEY" \
      -c "model.model_kwargs.max_tokens=$MODEL_MAX_OUTPUT_TOKENS" \
      "${reasoning_args[@]}" \
      -o "$task_dir" \
      > "$task_dir/agent.log" 2>&1
  agent_rc=$?
  set -e
  grep -q 'TimeoutExpired' "$task_dir/agent.log" && agent_rc=124
  # mini-swe exit status, e.g. Submitted, RepeatedFormatError, LimitsExceeded.
  agent_status=$(awk '/^    [A-Za-z]+:$/ {gsub(/[ :]/, ""); print; exit}' "$task_dir"/exit_statuses_*.yaml 2>/dev/null || true)
  log_event "[DETAIL] [SWE] $task | agent_status=${agent_status:-unknown} | agent_rc=$agent_rc | agent_seconds=$(($(date +%s) - start))"

  if [[ -s "$task_dir/preds.json" ]] && (( agent_rc == 0 )); then
    limit=$SWE_GRADER_SECONDS
    ACTIVE_LOG="$task_dir/evaluator.log"
    set +e
    (
      cd "$task_dir" || exit 1
      HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 \
        timeout --foreground --signal=INT --kill-after=60s "$limit" "$PY" -m swebench.harness.run_evaluation \
        -d princeton-nlp/SWE-bench_Verified -s test -i "$task" -p preds.json \
        --max_workers 1 -t "$limit" --cache_level instance --clean true \
        -id "${RUN_ID}-${phase}-${task}" --report_dir .
    ) > "$task_dir/evaluator.log" 2>&1
    eval_rc=$?
    set -e
  fi

  end=$(date +%s)
  if (( agent_rc == 124 || agent_rc == 137 )); then
    outcome=timeout
  elif (( agent_rc != 0 || eval_rc != 0 )); then
    outcome=infra_error
  else
    outcome=$(json_outcome swe "$task_dir")
  fi
  record_result "$phase" "$attempt" swe "$task" "$(date -u -d "@$start" +%FT%TZ)" "$(date -u -d "@$end" +%FT%TZ)" "$((end - start))" "$agent_rc/$eval_rc" "$outcome"
}

run_terminal() {
  local phase=$1 attempt=$2 task=$3 task_dir start end limit rc outcome job
  resume_skip terminal "$task" && return 0
  task_dir="$RUN_DIR/$phase/terminal/$task"
  job="${phase}-${task}"
  fresh_dir "$task_dir"
  require_free "$TASK_FREE_BYTES"
  limit=$(bounded_limit "$TERMINAL_SECONDS")
  start=$(date +%s)

  task_started "$phase" "$attempt" terminal "$task" "$limit" "$task_dir/harbor.log"
  mapfile -t model_args < <(harbor_model_args)
  set +e
  timeout --foreground --signal=INT --kill-after=60s "$limit" \
    "$HARBOR" run -d terminal-bench/terminal-bench-2-1 -i "terminal-bench/$task" "${model_args[@]}" \
      --delete --job-name "$job" -o "$task_dir" > "$task_dir/harbor.log" 2>&1
  rc=$?
  set -e
  end=$(date +%s)
  if (( rc == 124 || rc == 137 )); then
    outcome=timeout
  elif (( rc != 0 )); then
    outcome=infra_error
  else
    outcome=$(json_outcome terminal "$task_dir")
  fi
  record_result "$phase" "$attempt" terminal "$task" "$(date -u -d "@$start" +%FT%TZ)" "$(date -u -d "@$end" +%FT%TZ)" "$((end - start))" "$rc" "$outcome"
}

run_vals_public() {
  local phase=$1 attempt=$2 suite=$3 task=$4 requested=$5 task_dir start end limit rc outcome max_tokens=${VALS_TOKENS[$3]}
  local reasoning_args=() judge_args=()
  resume_skip "$suite" "$task" && return 0
  task_dir="$RUN_DIR/$phase/$suite/$task"
  fresh_dir "$task_dir"
  limit=$(bounded_limit "$requested")
  start=$(date +%s)

  task_started "$phase" "$attempt" "$suite" "$task" "$limit" "$task_dir/vals-public.log"
  [[ -n "$REASONING_EFFORT" ]] && reasoning_args=(--reasoning-effort "$REASONING_EFFORT")
  # Finance prompts are open-ended; a thinking model with no effort set can burn the whole token cap and return nothing.
  [[ "$suite" == finance ]] && reasoning_args=(--reasoning-effort "${VALS_FINANCE_REASONING_EFFORT:-${REASONING_EFFORT:-medium}}")
  # Optional separate rubric judge for Finance: VALS_JUDGE_BASE_URL (ends in /v1), VALS_JUDGE_MODEL, VALS_JUDGE_API_KEY.
  if [[ "$suite" == finance && -n "${VALS_JUDGE_BASE_URL:-}${VALS_JUDGE_MODEL:-}" ]]; then
    judge_args=(--judge-api-base "${VALS_JUDGE_BASE_URL:-$API_BASE}" --judge-model "${VALS_JUDGE_MODEL:-$MODEL_ID}" --judge-api-key "${VALS_JUDGE_API_KEY:-$API_KEY}")
  fi
  set +e
  timeout --foreground --signal=INT --kill-after=30s "$limit" \
    "$PY" "$VALS_PUBLIC" --cases "$VALS_PUBLIC_CASES" --question-id "$task" \
      --api-base "$API_BASE" --api-key "$API_KEY" --model "$MODEL_ID" \
      "${reasoning_args[@]}" "${judge_args[@]}" --max-tokens "$max_tokens" --timeout "$limit" \
      --output "$task_dir/result.json" > "$task_dir/vals-public.log" 2>&1
  rc=$?
  set -e
  [[ -s "$task_dir/vals-public.log" ]] && log_event "[DETAIL] [${suite^^}] $task | $(tail -n 1 "$task_dir/vals-public.log")"
  end=$(date +%s)
  if (( rc == 124 || rc == 137 )); then
    outcome=timeout
  elif (( rc != 0 )); then
    outcome=infra_error
  else
    outcome=$(json_outcome "$suite" "$task_dir")
  fi
  record_result "$phase" "$attempt" "$suite" "$task" "$(date -u -d "@$start" +%FT%TZ)" "$(date -u -d "@$end" +%FT%TZ)" "$((end - start))" "$rc" "$outcome"
}

run_reasoning() {
  local phase=$1 attempt=$2 task=$3 task_dir start end limit rc outcome
  local reasoning_args=()
  resume_skip reasoning "$task" && return 0
  task_dir="$RUN_DIR/$phase/reasoning/$task"
  fresh_dir "$task_dir"
  limit=$REASONING_SECONDS
  start=$(date +%s)

  task_started "$phase" "$attempt" reasoning "$task" "$limit" "$task_dir/reasoning.log"
  [[ -n "$REASONING_EFFORT" ]] && reasoning_args=(--reasoning-effort "$REASONING_EFFORT")
  set +e
  timeout --foreground --signal=INT --kill-after=30s "$limit" \
    "$PY" "$REASONING" --questions "$REASONING_QUESTIONS" --question-id "$task" \
      --api-base "$API_BASE" --api-key "$API_KEY" --model "$MODEL_ID" \
      "${reasoning_args[@]}" \
      --max-tokens "$REASONING_MAX_TOKENS" --timeout "$limit" \
      --output "$task_dir/result.json" > "$task_dir/reasoning.log" 2>&1
  rc=$?
  set -e
  # reasoning.py prints one summary line: outcome, score, finish_reason ("length" = output token limit hit) and usage.
  [[ -s "$task_dir/reasoning.log" ]] && log_event "[DETAIL] [REASONING] $task | $(tail -n 1 "$task_dir/reasoning.log")"
  end=$(date +%s)
  if (( rc == 124 || rc == 137 )); then
    outcome=timeout
  elif (( rc != 0 )); then
    outcome=infra_error
  else
    outcome=$(json_outcome reasoning "$task_dir")
  fi
  record_result "$phase" "$attempt" reasoning "$task" "$(date -u -d "@$start" +%FT%TZ)" "$(date -u -d "@$end" +%FT%TZ)" "$((end - start))" "$rc" "$outcome"
}

main() {
  local performance_rc=0
  preflight
  if [[ "$MODE" == --preflight ]]; then
    echo "Preflight-only run complete: $RUN_DIR"
    return
  fi
  RUN_STARTED=1
  save_resume_env "$RUN_DIR" OPENAI_BASE_URL "$API_INPUT" OPENAI_MODEL "$MODEL_INPUT" "$MODEL_NAME" \
    "$([[ "$BENCHMARK_TYPE" == tasks || "$BENCHMARK_TYPE" == vals-public ]] && echo 0 || echo $((2 + ${#AGGREGATE_CONCURRENCIES[@]})))"

  # The result builder reads the task selection (and per-task caps) from here.
  {
    printf 'suite\ttask\ttimeout_seconds\n'
    printf "swe\t%s\t$SWE_TOTAL_SECONDS\n" "${SWE_TASKS[@]}"
    printf "legal\t%s\t${VALS_SECONDS[legal]}\n" "${VALS_LEGAL_TASKS[@]}"
    printf "finance\t%s\t${VALS_SECONDS[finance]}\n" "${VALS_FINANCE_TASKS[@]}"
    printf "health\t%s\t${VALS_SECONDS[health]}\n" "${VALS_HEALTH_TASKS[@]}"
    printf "math\t%s\t${VALS_SECONDS[math]}\n" "${VALS_MATH_TASKS[@]}"
    printf "science\t%s\t${VALS_SECONDS[science]}\n" "${VALS_SCIENCE_TASKS[@]}"
    printf "terminal\t%s\t$TERMINAL_SECONDS\n" "${TERMINAL_TASKS[@]}"
    printf "reasoning\t%s\t$REASONING_SECONDS\n" "${REASONING_TASKS[@]}"
  } | awk -F '\t' 'NF == 3 && $2 != ""' > "$RUN_DIR/selected-tasks.tsv"
  : > "$RUN_DIR/active-task.tsv"
  if [[ -n "$RESUME_DIR" && -f "$RUN_DIR/task-results.tsv" ]]; then
    # Keep finished rows; infra errors are retried, so move them aside (result.py counts every row).
    awk -F '\t' 'NR > 1 && $9 == "infra_error"' "$RUN_DIR/task-results.tsv" >> "$RUN_DIR/task-results.retried.tsv"
    awk -F '\t' 'NR == 1 || $9 != "infra_error"' "$RUN_DIR/task-results.tsv" > "$RUN_DIR/task-results.tsv.tmp"
    mv "$RUN_DIR/task-results.tsv.tmp" "$RUN_DIR/task-results.tsv"
    # ponytail: counts task time only (not performance steps), so a resumed duration is slightly short.
    echo $(( $(date +%s) - $(awk -F '\t' 'NR > 1 {s += $7} END {print s + 0}' "$RUN_DIR/task-results.tsv") )) > "$RUN_DIR/benchmark-start-epoch"
    log_event "[RESUME] $RUN_ID: $(tsv_rows "$RUN_DIR/task-results.tsv") of $TOTAL_TASKS tasks already recorded; the rest run now"
  else
    printf 'phase\tattempt\tsuite\ttask\tstart_utc\tend_utc\tduration_seconds\texit_code\toutcome\n' > "$RUN_DIR/task-results.tsv"
    date +%s > "$RUN_DIR/benchmark-start-epoch"
  fi
  # Each session gets the full Vals budget, so a run stopped by the limit can continue.
  [[ "$BENCHMARK_TYPE" == vals-public ]] && GLOBAL_DEADLINE=$(( $(date +%s) + VALS_DEADLINE_SECONDS ))
  generate_result running
  log_event "[BENCHMARK] Started type=$BENCHMARK_TYPE | tasks=$TOTAL_TASKS | live result=$RESULT_FILE"
  quick_banner

  if [[ "$BENCHMARK_TYPE" == vals-public ]]; then
    local task
    for task in "${VALS_LEGAL_TASKS[@]}"; do run_vals_public primary 1 legal "$task" "${VALS_SECONDS[legal]}"; done
    log_suite_summary legal
    for task in "${VALS_FINANCE_TASKS[@]}"; do run_vals_public primary 1 finance "$task" "${VALS_SECONDS[finance]}"; done
    log_suite_summary finance
    for task in "${VALS_HEALTH_TASKS[@]}"; do run_vals_public primary 1 health "$task" "${VALS_SECONDS[health]}"; done
    log_suite_summary health
    for task in "${VALS_MATH_TASKS[@]}"; do run_vals_public primary 1 math "$task" "${VALS_SECONDS[math]}"; done
    log_suite_summary math
    for task in "${VALS_SCIENCE_TASKS[@]}"; do run_vals_public primary 1 science "$task" "${VALS_SECONDS[science]}"; done
    log_suite_summary science
  elif [[ "$BENCHMARK_TYPE" != performance ]]; then
    local task
    for task in "${SWE_TASKS[@]}"; do
      run_swe primary 1 "$task"
    done
    log_suite_summary swe
    for task in "${TERMINAL_TASKS[@]}"; do
      run_terminal primary 1 "$task"
    done
    log_suite_summary terminal
    for task in "${REASONING_TASKS[@]}"; do
      run_reasoning primary 1 "$task"
    done
    log_suite_summary reasoning
  fi
  if [[ "$BENCHMARK_TYPE" != tasks && "$BENCHMARK_TYPE" != vals-public ]]; then
    measure_performance || performance_rc=$?
    if (( performance_rc != 0 )); then
      if (( performance_rc == 3 && TOTAL_TASKS == 0 )); then
        date +%s > "$RUN_DIR/benchmark-end-epoch"
        generate_result skipped
        generate_report
        RUN_FINALIZED=1
        log_event "[BENCHMARK] SKIPPED: model server could not complete a measurable performance request; see the diagnostic above. result=$RESULT_FILE report=$REPORT_FILE"
        return 0
      fi
      return "$performance_rc"
    fi
  fi
  echo "$(date +%s)" > "$RUN_DIR/benchmark-end-epoch"
  : > "$RUN_DIR/active-task.tsv"
  generate_result completed
  generate_report
  RUN_FINALIZED=1
  log_suite_summary swe
  log_suite_summary terminal
  log_suite_summary reasoning
  log_suite_summary legal
  log_suite_summary finance
  log_suite_summary health
  log_suite_summary math
  log_suite_summary science
  log_event "[BENCHMARK] COMPLETE type=$BENCHMARK_TYPE | tasks=$TOTAL_TASKS/$TOTAL_TASKS | elapsed=$(( $(date +%s) - PREFLIGHT_START ))s including preflight | result=$RESULT_FILE | report=$REPORT_FILE"
}

main
