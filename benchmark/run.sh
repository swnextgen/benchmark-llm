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

API_INPUT="${OPENAI_BASE_URL:-}"
MODEL_INPUT="${OPENAI_MODEL:-}"
BENCHMARK_TYPE="${BENCHMARK_TYPE:-performance}"
SWE_TASK_COUNT="${SWE_TASK_COUNT:-10}"
TERMINAL_TASK_COUNT="${TERMINAL_TASK_COUNT:-10}"
REASONING_TASK_COUNT="${REASONING_TASK_COUNT:-5}"
if [[ -t 0 ]]; then
  read -r -p "OpenAI API URL (/v1 or /v1/chat/completions)${API_INPUT:+ [$API_INPUT]}: " answer
  API_INPUT="${answer:-$API_INPUT}"
  read -r -p "Model ID${MODEL_INPUT:+ [$MODEL_INPUT]}: " answer
  MODEL_INPUT="${answer:-$MODEL_INPUT}"
  if [[ "$MODE" == run ]]; then
    printf 'Benchmark type:\n  1. performance\n  2. task\n  3. both\n'
    read -r -p "Select [$BENCHMARK_TYPE]: " answer
    BENCHMARK_TYPE="${answer:-$BENCHMARK_TYPE}"
    case "${BENCHMARK_TYPE,,}" in
      performance|p|1) BENCHMARK_TYPE=performance ;;
      tasks|task|t|2) BENCHMARK_TYPE=tasks ;;
      both|b|3) BENCHMARK_TYPE=both ;;
      *) echo "Benchmark type must be performance, tasks or both." >&2; exit 2 ;;
    esac
    if [[ "$BENCHMARK_TYPE" != performance ]]; then
      read -r -p "SWE-bench task count [${SWE_TASK_COUNT}, max 10]: " answer
      SWE_TASK_COUNT="${answer:-$SWE_TASK_COUNT}"
      read -r -p "Terminal-Bench task count [${TERMINAL_TASK_COUNT}, max 10]: " answer
      TERMINAL_TASK_COUNT="${answer:-$TERMINAL_TASK_COUNT}"
      read -r -p "LiveBench task count [${REASONING_TASK_COUNT}, max 5]: " answer
      REASONING_TASK_COUNT="${answer:-$REASONING_TASK_COUNT}"
    fi
  fi
fi
case "${BENCHMARK_TYPE,,}" in
  performance|p|1) BENCHMARK_TYPE=performance ;;
  tasks|task|t|2) BENCHMARK_TYPE=tasks ;;
  both|b|3) BENCHMARK_TYPE=both ;;
  *) echo "BENCHMARK_TYPE must be performance, tasks or both." >&2; exit 2 ;;
esac
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
MODEL_NAME="${MODEL_ID##*/}"
RESULT_BASENAME="${MODEL_NAME//\//-}"
RESULT_BASENAME="${RESULT_BASENAME// /-}"
MODEL_MAX_INPUT_TOKENS="${OPENAI_MODEL_MAX_INPUT_TOKENS:-131072}"
MODEL_CONTEXT_TOKENS="$MODEL_MAX_INPUT_TOKENS"
MODEL_CONTEXT_SOURCE=$([[ -n "${OPENAI_MODEL_MAX_INPUT_TOKENS:-}" ]] && echo configured || echo fallback)
MODEL_MAX_OUTPUT_TOKENS="${OPENAI_MODEL_MAX_OUTPUT_TOKENS:-8192}"
REASONING_EFFORT="${OPENAI_REASONING_EFFORT:-}"
START_FREE_BYTES=$((75 * 1024 * 1024 * 1024))
TASK_FREE_BYTES=$((20 * 1024 * 1024 * 1024))
SWE_SECONDS=$((25 * 60))
TERMINAL_SECONDS=$((20 * 60))
REASONING_SECONDS=$((10 * 60))
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
(( ${#SWE_TASKS[@]} == 10 && ${#TERMINAL_TASKS[@]} == 10 && ${#REASONING_TASKS[@]} == 5 )) || {
  echo "Expected 10 SWE, 10 Terminal and 5 reasoning tasks." >&2
  exit 2
}
[[ "$SWE_TASK_COUNT" =~ ^[0-9]+$ ]] && (( SWE_TASK_COUNT <= 10 )) || { echo "SWE-bench task count must be 0-10." >&2; exit 2; }
[[ "$TERMINAL_TASK_COUNT" =~ ^[0-9]+$ ]] && (( TERMINAL_TASK_COUNT <= 10 )) || { echo "Terminal-Bench task count must be 0-10." >&2; exit 2; }
[[ "$REASONING_TASK_COUNT" =~ ^[0-9]+$ ]] && (( REASONING_TASK_COUNT <= 5 )) || { echo "LiveBench task count must be 0-5." >&2; exit 2; }
[[ "$MODEL_MAX_INPUT_TOKENS" =~ ^[1-9][0-9]*$ ]] || { echo "Model input token limit must be a positive integer." >&2; exit 2; }
[[ "$PERFORMANCE_RUNS" =~ ^[1-9][0-9]*$ ]] || { echo "Performance runs must be a positive integer." >&2; exit 2; }
[[ "$PERFORMANCE_WARMUP_RUNS" =~ ^[0-9]+$ ]] || { echo "Performance warm-up runs cannot be negative." >&2; exit 2; }
for concurrency in "${AGGREGATE_CONCURRENCIES[@]}"; do
  [[ "$concurrency" =~ ^[1-9][0-9]*$ ]] || { echo "Aggregate concurrencies must be positive integers." >&2; exit 2; }
done
SWE_TASKS=("${SWE_TASKS[@]:0:SWE_TASK_COUNT}")
TERMINAL_TASKS=("${TERMINAL_TASKS[@]:0:TERMINAL_TASK_COUNT}")
REASONING_TASKS=("${REASONING_TASKS[@]:0:REASONING_TASK_COUNT}")
TOTAL_TASKS=$((${#SWE_TASKS[@]} + ${#TERMINAL_TASKS[@]} + ${#REASONING_TASKS[@]}))
TASK_INDEX=0

RUN_ID=$(date -u +%Y%m%dT%H%M%SZ)
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
TASK_HEARTBEAT_PID=""
PREFILL_MEASUREMENT=""
DECODE_MEASUREMENT=""
AGGREGATE_MEASUREMENTS=()

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
  if (( RUN_FINALIZED == 0 )) && [[ "$MODE" == run && -s "$RUN_DIR/task-results.tsv" ]] && command -v "$PY" >/dev/null 2>&1; then
    (( rc == 130 || rc == 143 )) && status=interrupted
    generate_result "$status" || true
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
  if [[ "$BENCHMARK_TYPE" != performance ]]; then
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
    if [[ -z "${OPENAI_MODEL_MAX_INPUT_TOKENS:-}" ]]; then
      MODEL_MAX_INPUT_TOKENS="$detected_context"
      MODEL_INFO=$(printf '{"max_input_tokens":%s,"max_output_tokens":%s,"input_cost_per_token":0,"output_cost_per_token":0}' \
        "$MODEL_MAX_INPUT_TOKENS" "$MODEL_MAX_OUTPUT_TOKENS")
    fi
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
content = (choices[0].get("message") or {}).get("content")
if not isinstance(content, str) or "READY" not in content.upper():
    raise SystemExit("Chat smoke test did not complete the requested READY response")
PY
}

validate_swe_tasks() {
  "$PY" - "$PREFLIGHT_DIR/swe-tasks.tsv" "${SWE_TASKS[@]}" <<'PY'
import sys
from datasets import load_dataset

output, *wanted = sys.argv[1:]
rows = {row["instance_id"]: row for row in load_dataset("princeton-nlp/SWE-bench_Verified", split="test")}
with open(output, "w") as f:
    f.write("instance_id\tdifficulty\n")
    for task in wanted:
        if task not in rows:
            raise SystemExit(f"Missing SWE-bench task: {task}")
        difficulty = rows[task].get("difficulty")
        if difficulty != "15 min - 1 hour":
            raise SystemExit(f"{task} is not medium: {difficulty!r}")
        f.write(f"{task}\t{difficulty}\n")
PY
}

swe_image() {
  local compatible=${1/__/_1776_}
  printf 'docker.io/swebench/sweb.eval.x86_64.%s:latest\n' "${compatible,,}"
}

harbor_model_args() {
  local args=(-a terminus-2 -m "openai/$MODEL_ID" --ak "api_base=$API_BASE" --ak max_turns=100 --ak "model_info=$MODEL_INFO" -n 1 -k 1 -r 0 -y)
  [[ -n "$REASONING_EFFORT" ]] && args+=(--ak "reasoning_effort=$REASONING_EFFORT")
  printf '%s\n' "${args[@]}"
}

prepare_images() {
  local task image container index=0
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
    "$HARBOR" run -d terminal-bench/terminal-bench-2-1 -i "terminal-bench/$task" "${model_args[@]}" \
      --delete --install-only --job-name "install-$task" -o "$PREFLIGHT_DIR/harbor-install" \
      > "$PREFLIGHT_DIR/harbor-install/$task.log" 2>&1
    log_event "[PREFLIGHT TERMINAL $index/${#TERMINAL_TASKS[@]}] READY $task"
  done

  log_event "[PREFLIGHT] Running Harbor oracle smoke test"
  "$HARBOR" run -d terminal-bench/terminal-bench-2-1 -i terminal-bench/cancel-async-tasks -a oracle -n 1 -k 1 -r 0 -y \
    --delete --job-name oracle-smoke -o "$PREFLIGHT_DIR/harbor-oracle" \
    > "$PREFLIGHT_DIR/harbor-oracle.log" 2>&1
  [[ $(json_outcome terminal "$PREFLIGHT_DIR/harbor-oracle") == pass ]] || die "Harbor oracle smoke test did not receive reward 1."
}

preflight() {
  echo "Preflight artifacts: $PREFLIGHT_DIR"
  echo "Configuration: $CONFIG_FILE"
  echo "API endpoint: $API_BASE"
  echo "Model: $MODEL_ID"
  echo "Benchmark type: $BENCHMARK_TYPE"
  [[ -n "$REASONING_EFFORT" ]] && echo "Reasoning effort: $REASONING_EFFORT"
  log_event "[PREFLIGHT] Checking local tools and Python runtime"
  ensure_tools
  if [[ "$BENCHMARK_TYPE" != performance ]]; then
    [[ $(uname -m) == x86_64 ]] || die "SWE-bench Docker evaluation requires x86_64."
    require_free "$START_FREE_BYTES"
    log_event "[PREFLIGHT] Checking local Docker"
    docker info --format '{{.Architecture}} {{.ServerVersion}}' | tee "$PREFLIGHT_DIR/docker.txt"
  fi
  log_event "[PREFLIGHT] Validating model API"
  validate_api
  log_event "[PREFLIGHT] Model context=$MODEL_CONTEXT_TOKENS tokens (source=$MODEL_CONTEXT_SOURCE); benchmark input limit=$MODEL_MAX_INPUT_TOKENS"
  if [[ "$BENCHMARK_TYPE" != performance ]]; then
    log_event "[PREFLIGHT] Validating SWE-bench task selection"
    validate_swe_tasks
    log_event "[PREFLIGHT] Preparing benchmark images"
    prepare_images
    require_free "$TASK_FREE_BYTES"
  fi
  echo "Preflight passed. Free disk: $(( $(free_bytes) / 1024 / 1024 / 1024 )) GiB"
}

generate_result() {
  local status=${1:-running}
  local aggregate_args=() measurement
  for measurement in "${AGGREGATE_MEASUREMENTS[@]}"; do
    aggregate_args+=(--aggregate-measurement "$measurement")
  done
  "$PY" "$RESULT_BUILDER" \
    --run-dir "$RUN_DIR" \
    --template "$RESULT_TEMPLATE" \
    --output "$RESULT_FILE" \
    --status "$status" \
    --model-id "$MODEL_ID" \
    --model-name "$MODEL_NAME" \
    --api-base-url "$API_BASE" \
    --reasoning-effort "$REASONING_EFFORT" \
    --maximum-context-tokens "$MODEL_CONTEXT_TOKENS" \
    --benchmark-input-limit-tokens "$MODEL_MAX_INPUT_TOKENS" \
    --context-source "$MODEL_CONTEXT_SOURCE" \
    --swe-count "$SWE_TASK_COUNT" \
    --terminal-count "$TERMINAL_TASK_COUNT" \
    --reasoning-count "$REASONING_TASK_COUNT" \
    --prefill-measurement "$PREFILL_MEASUREMENT" \
    --decode-measurement "$DECODE_MEASUREMENT" \
    "${aggregate_args[@]}"
}

generate_report() {
  "$PY" "$REPORT_BUILDER" --input "$RESULT_FILE" --template "$REPORT_TEMPLATE" --output "$REPORT_FILE" >/dev/null
}

measure_performance() {
  log_event "[PERFORMANCE] Prefill: $PERFORMANCE_WARMUP_RUNS warm-up + $PERFORMANCE_RUNS measured uncached requests"
  local reasoning_args=()
  [[ -n "$REASONING_EFFORT" ]] && reasoning_args=(--reasoning-effort "$REASONING_EFFORT")
  PREFILL_MEASUREMENT=$(timeout --foreground --signal=INT --kill-after=30s "$PERFORMANCE_SECONDS" \
    "$PY" "$MEASURE_API" --endpoint "$API_BASE" --model "$MODEL_ID" "${reasoning_args[@]}" \
      --runs "$PERFORMANCE_RUNS" --warmup-runs "$PERFORMANCE_WARMUP_RUNS" \
      --prompt-lines "$PREFILL_PROMPT_LINES" --max-tokens "$PREFILL_MAX_TOKENS" --json-only)
  log_event "[PERFORMANCE] Prefill measurement complete"
  log_event "[PERFORMANCE] Decode: $PERFORMANCE_WARMUP_RUNS warm-up + $PERFORMANCE_RUNS measured uncached requests"
  DECODE_MEASUREMENT=$(timeout --foreground --signal=INT --kill-after=30s "$PERFORMANCE_SECONDS" \
    "$PY" "$MEASURE_API" --endpoint "$API_BASE" --model "$MODEL_ID" "${reasoning_args[@]}" \
      --runs "$PERFORMANCE_RUNS" --warmup-runs "$PERFORMANCE_WARMUP_RUNS" \
      --prompt-lines "$DECODE_PROMPT_LINES" --max-tokens "$DECODE_MAX_TOKENS" --json-only)
  log_event "[PERFORMANCE] Decode measurement complete"
  local concurrency measurement
  for concurrency in "${AGGREGATE_CONCURRENCIES[@]}"; do
    log_event "[PERFORMANCE] Aggregate C$concurrency: $PERFORMANCE_WARMUP_RUNS warm-up + $PERFORMANCE_RUNS measured batches"
    measurement=$(timeout --foreground --signal=INT --kill-after=30s "$PERFORMANCE_SECONDS" \
      "$PY" "$MEASURE_API" --endpoint "$API_BASE" --model "$MODEL_ID" "${reasoning_args[@]}" \
        --runs "$PERFORMANCE_RUNS" --warmup-runs "$PERFORMANCE_WARMUP_RUNS" \
        --prompt-lines "$DECODE_PROMPT_LINES" --max-tokens "$DECODE_MAX_TOKENS" \
        --concurrency "$concurrency" --json-only)
    AGGREGATE_MEASUREMENTS+=("$measurement")
    log_event "[PERFORMANCE] Aggregate generation C$concurrency complete"
  done
}

task_started() {
  local phase=$1 attempt=$2 suite=$3 task=$4 limit=$5 log_path=$6 started_epoch
  TASK_INDEX=$((TASK_INDEX + 1))
  started_epoch=$(date +%s)
  printf 'phase\tattempt\tsuite\ttask\tstart_utc\ttimeout_seconds\n%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$phase" "$attempt" "$suite" "$task" "$(date -u +%FT%TZ)" "$limit" > "$RUN_DIR/active-task.tsv"
  log_event "[START $(printf '%02d' "$TASK_INDEX")/$TOTAL_TASKS] [${suite^^}] $task | limit=${limit}s | log=${log_path#$RUN_DIR/}"
  generate_result running
  (
    while sleep 60; do
      log_event "[RUNNING $(printf '%02d' "$TASK_INDEX")/$TOTAL_TASKS] [${suite^^}] $task | elapsed=$(($(date +%s) - started_epoch))s | log=${log_path#$RUN_DIR/}"
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
    timeout) label=TIMEOUT ;;
    *) label=ERROR ;;
  esac
  counts=$(awk -F '\t' 'NR>1 {done++; pass+=($9=="pass"); fail+=($9=="fail"); timeout+=($9=="timeout"); error+=($9=="infra_error")} END {printf "done=%d pass=%d fail=%d timeout=%d error=%d", done, pass, fail, timeout, error}' "$RUN_DIR/task-results.tsv")
  log_event "[$label $(printf '%02d' "$TASK_INDEX")/$TOTAL_TASKS] [${suite^^}] $task | duration=${duration}s | exit=$exit_code | $counts"
  generate_result running
}

json_outcome() {
  "$PY" - "$1" "$2" <<'PY'
import json, pathlib, sys
kind, root = sys.argv[1], pathlib.Path(sys.argv[2])
if kind == "swe":
    reports = [p for p in root.glob("*.json") if p.name != "preds.json"]
    if not reports:
        print("infra_error")
    else:
        data = json.loads(reports[-1].read_text())
        print("pass" if data.get("resolved_instances", 0) == 1 else "fail")
elif kind == "terminal":
    reports = list(root.glob("*/result.json"))
    if not reports:
        print("infra_error")
    else:
        data = json.loads(reports[-1].read_text())
        reward_stats = [e.get("reward_stats", {}).get("reward", {}) for e in data.get("stats", {}).get("evals", {}).values()]
        rewards = [float(value) for stats in reward_stats for value, trials in stats.items() if trials]
        print("pass" if rewards and max(rewards) >= 1 else "fail")
else:
    report = root / "result.json"
    if not report.exists():
        print("infra_error")
    else:
        print(json.loads(report.read_text()).get("outcome", "infra_error"))
PY
}

run_swe() {
  local phase=$1 attempt=$2 task=$3 task_dir start end limit agent_rc=0 eval_rc=0 outcome
  local reasoning_args=()
  task_dir="$RUN_DIR/$phase/swe/$task"
  mkdir -p "$task_dir"
  require_free "$TASK_FREE_BYTES"
  start=$(date +%s)
  limit=$SWE_SECONDS

  task_started "$phase" "$attempt" swe "$task" "$limit" "$task_dir/agent.log"
  [[ -n "$REASONING_EFFORT" ]] && reasoning_args=(-c "model.model_kwargs.reasoning_effort=$REASONING_EFFORT")
  set +e
  timeout --foreground --signal=INT --kill-after=60s "$limit" \
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

  if [[ -s "$task_dir/preds.json" ]] && (( agent_rc == 0 )); then
    limit=$((SWE_SECONDS - ($(date +%s) - start)))
    if (( limit > 0 )); then
      set +e
      (
        cd "$task_dir" || exit 1
        timeout --foreground --signal=INT --kill-after=60s "$limit" "$PY" -m swebench.harness.run_evaluation \
          -d princeton-nlp/SWE-bench_Verified -s test -i "$task" -p preds.json \
          --max_workers 1 -t "$limit" --cache_level instance --clean true -n none \
          -id "${RUN_ID}-${phase}-${task}" --report_dir .
      ) > "$task_dir/evaluator.log" 2>&1
      eval_rc=$?
      set -e
    else
      eval_rc=124
    fi
  fi

  end=$(date +%s)
  if (( agent_rc == 124 || agent_rc == 137 || eval_rc == 124 || eval_rc == 137 )); then
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
  task_dir="$RUN_DIR/$phase/terminal/$task"
  job="${phase}-${task}"
  mkdir -p "$task_dir"
  require_free "$TASK_FREE_BYTES"
  start=$(date +%s)
  limit=$TERMINAL_SECONDS

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

run_reasoning() {
  local phase=$1 attempt=$2 task=$3 task_dir start end limit rc outcome
  local reasoning_args=()
  task_dir="$RUN_DIR/$phase/reasoning/$task"
  mkdir -p "$task_dir"
  start=$(date +%s)
  limit=$REASONING_SECONDS

  task_started "$phase" "$attempt" reasoning "$task" "$limit" "$task_dir/reasoning.log"
  [[ -n "$REASONING_EFFORT" ]] && reasoning_args=(--reasoning-effort "$REASONING_EFFORT")
  set +e
  timeout --foreground --signal=INT --kill-after=30s "$limit" \
    "$PY" "$REASONING" --questions "$REASONING_QUESTIONS" --question-id "$task" \
      --api-base "$API_BASE" --api-key "$API_KEY" --model "$MODEL_ID" \
      "${reasoning_args[@]}" \
      --max-tokens "$MODEL_MAX_OUTPUT_TOKENS" --timeout "$limit" \
      --output "$task_dir/result.json" > "$task_dir/reasoning.log" 2>&1
  rc=$?
  set -e
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
  preflight
  if [[ "$MODE" == --preflight ]]; then
    echo "Preflight-only run complete: $RUN_DIR"
    return
  fi

  printf 'phase\tattempt\tsuite\ttask\tstart_utc\tend_utc\tduration_seconds\texit_code\toutcome\n' > "$RUN_DIR/task-results.tsv"
  : > "$RUN_DIR/active-task.tsv"

  date +%s > "$RUN_DIR/benchmark-start-epoch"
  generate_result running
  log_event "[BENCHMARK] Started type=$BENCHMARK_TYPE | tasks=$TOTAL_TASKS | live result=$RESULT_FILE"

  if [[ "$BENCHMARK_TYPE" != performance ]]; then
    local task
    for task in "${SWE_TASKS[@]}"; do
      run_swe primary 1 "$task"
    done
    for task in "${TERMINAL_TASKS[@]}"; do
      run_terminal primary 1 "$task"
    done
    for task in "${REASONING_TASKS[@]}"; do
      run_reasoning primary 1 "$task"
    done
  fi
  if [[ "$BENCHMARK_TYPE" != tasks ]]; then
    measure_performance
  fi
  echo "$(date +%s)" > "$RUN_DIR/benchmark-end-epoch"
  : > "$RUN_DIR/active-task.tsv"
  generate_result completed
  generate_report
  RUN_FINALIZED=1
  log_event "[BENCHMARK] COMPLETE type=$BENCHMARK_TYPE | tasks=$TOTAL_TASKS/$TOTAL_TASKS | result=$RESULT_FILE | report=$REPORT_FILE"
}

main
