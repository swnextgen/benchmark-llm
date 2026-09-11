#!/usr/bin/env python3
"""Build the live UI result JSON from benchmark artifacts."""

import argparse
import csv
import datetime as dt
import json
import pathlib
import platform
import re
import sys


SUITES = {
    "swe": "swe_bench_verified",
    "terminal": "terminal_bench_2_1",
    "reasoning": "livebench_reasoning_subset",
}
LIMITS = {"swe_bench_verified": 1500, "terminal_bench_2_1": 1200, "livebench_reasoning_subset": 600}


def read_rows(path, delimiter="\t"):
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open() as file:
        return list(csv.DictReader(file, delimiter=delimiter))


def direct_measurement(raw):
    if not raw:
        return None, 0, []
    try:
        data = json.loads(raw)
        measurement = dict(data.get("median") or data["average"])
        if data.get("concurrency") is not None:
            measurement.setdefault("concurrency", data["concurrency"])
        average = data.get("average") or {}
        measurement["_mean_ttft_seconds"] = average.get("ttft_seconds")
        measurement["_mean_request_ttft_seconds"] = average.get("mean_request_ttft_seconds")
        measurement["_warmup_runs"] = data.get("warmup_runs", 0)
        return measurement, len(data["runs"]), data["runs"]
    except (KeyError, TypeError, json.JSONDecodeError):
        return None, 0, []


def self_test():
    measurement, runs, samples = direct_measurement(json.dumps({
        "concurrency": 4,
        "warmup_runs": 1,
        "runs": [{}],
        "average": {"mean_request_ttft_seconds": 2},
        "median": {"aggregate_generation_tps": 100},
    }))
    assert runs == 1 and len(samples) == 1 and measurement["_warmup_runs"] == 1
    metrics = service_metrics(pathlib.Path("/nonexistent"), [], "", "", [
        json.dumps({"concurrency": 8, "runs": [{}, {}], "average": {"mean_request_ttft_seconds": 1.5}, "median": {
            "aggregate_generation_tps": 200, "effective_per_user_tps": 25, "mean_request_decode_tps": 25,
            "completion_tokens": 4096, "batch_seconds": 20,
        }}),
        json.dumps({"concurrency": 12, "runs": [{}], "average": {"mean_request_ttft_seconds": 2.5}, "median": {
            "aggregate_generation_tps": 240, "effective_per_user_tps": 20, "mean_request_decode_tps": 20,
            "completion_tokens": 6144, "batch_seconds": 26,
        }}),
    ])
    assert [item["concurrency"] for item in metrics["aggregate_measurements"]] == [8, 12]
    assert metrics["aggregate_measurements"][0]["runs"] == 2
    assert metrics["aggregate_measurements"][0]["mean_time_to_first_token_seconds"] == 1.5
    print("result self-test passed")


def service_metrics(root, rows, prefill_raw, decode_raw, aggregate_raws):
    prefill, prefill_runs, prefill_samples = direct_measurement(prefill_raw)
    decode, decode_runs, decode_samples = direct_measurement(decode_raw)
    aggregates = []
    for raw in aggregate_raws:
        measurement, runs, samples = direct_measurement(raw)
        if measurement:
            aggregates.append((measurement, runs, samples))
    aggregates.sort(key=lambda item: item[0].get("concurrency", 0))
    aggregate, aggregate_runs, _ = aggregates[0] if aggregates else (None, 0, [])
    format_failures = tool_failures = 0
    # ponytail: rescanning is fine for 25 tasks; persist counters if the suite grows substantially.
    for path in root.rglob("*.log"):
        try:
            for line in path.open(errors="replace"):
                format_failures += bool(re.search(r"format error|malformed", line, re.I))
                tool_failures += bool(re.search(r"tool call error|invalid tool", line, re.I))
        except OSError:
            pass
    measured = bool(prefill and decode)
    return {
        "approximate_prefill_rate_tokens_per_second": round(prefill["prefill_tps_approx"], 2) if prefill else None,
        "decode_rate_tokens_per_second": round(decode["decode_tps"], 2) if decode else None,
        "single_request_mean_time_to_first_token_seconds": round(decode["_mean_ttft_seconds"], 3) if decode and decode.get("_mean_ttft_seconds") is not None else None,
        "median_time_to_first_token_seconds": round(prefill["ttft_seconds"], 3) if prefill else None,
        "performance_measurement_method": "separate_uncached_streaming_api_requests" if measured else "not_available",
        "performance_measurement_statistic": "median" if measured else None,
        "ttft_measurement_statistic": "mean" if measured else None,
        "performance_measurement_runs": {"prefill": prefill_runs, "decode": decode_runs},
        "performance_warmup_runs": {
            "prefill": prefill.get("_warmup_runs", 0) if prefill else 0,
            "decode": decode.get("_warmup_runs", 0) if decode else 0,
        },
        "performance_samples": {"prefill": prefill_samples, "decode": decode_samples},
        "aggregate_generation_rate_tokens_per_second": round(aggregate["aggregate_generation_tps"], 2) if aggregate else None,
        "aggregate_concurrency": int(aggregate["concurrency"]) if aggregate and aggregate.get("concurrency") is not None else None,
        "aggregate_generated_tokens_per_batch": round(aggregate["completion_tokens"]) if aggregate else None,
        "aggregate_batch_seconds": round(aggregate["batch_seconds"], 3) if aggregate else None,
        "aggregate_measurement_runs": aggregate_runs,
        "aggregate_measurements": [{
            "concurrency": int(measurement["concurrency"]),
            "generation_rate_tokens_per_second": round(measurement["aggregate_generation_tps"], 2),
            "effective_per_user_generation_rate_tokens_per_second": round(
                measurement["aggregate_generation_tps"] / measurement["concurrency"], 2
            ),
            "mean_request_decode_rate_tokens_per_second": round(measurement["mean_request_decode_tps"], 2),
            "mean_time_to_first_token_seconds": round(measurement["_mean_request_ttft_seconds"], 3)
            if measurement.get("_mean_request_ttft_seconds") is not None else None,
            "generated_tokens_per_batch": round(measurement["completion_tokens"]),
            "batch_seconds": round(measurement["batch_seconds"], 3),
            "runs": runs,
            "warmup_runs": measurement.get("_warmup_runs", 0),
            "samples": samples,
        } for measurement, runs, samples in aggregates],
        "api_error_completions": 0 if measured else None,
        "timeouts": sum(row["outcome"] == "timeout" for row in rows),
        "infrastructure_errors": sum(row["outcome"] == "infra_error" for row in rows),
        "format_failures": format_failures,
        "tool_failures": tool_failures,
    }


def reasoning_score(root, row):
    path = root / row["phase"] / "reasoning" / row["task"] / "result.json"
    try:
        return round(float(json.loads(path.read_text())["score"]) * 100, 1)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def build_tasks(root, template_tasks, rows, active):
    completed = {(SUITES[row["suite"]], row["task"]): row for row in rows}
    tasks = []
    for source in template_tasks:
        task = dict(source)
        row = completed.get((task["suite"], task["task"]))
        is_active = active and SUITES.get(active.get("suite")) == task["suite"] and active.get("task") == task["task"]
        task.update({
            "phase": row["phase"] if row else active.get("phase", "primary") if is_active else "primary",
            "attempt": int(row["attempt"]) if row else int(active.get("attempt", 1)) if is_active else None,
            "started_at": row["start_utc"] if row else active.get("start_utc") if is_active else None,
            "ended_at": row["end_utc"] if row else None,
            "seconds": int(row["duration_seconds"]) if row else None,
            "timeout_seconds": int(active["timeout_seconds"]) if is_active else LIMITS[task["suite"]],
            "exit_code": row["exit_code"] if row else None,
            "outcome": row["outcome"] if row else "running" if is_active else "pending",
            "score_percent": reasoning_score(root, row) if row and row["suite"] == "reasoning"
            else 100.0 if row and row["outcome"] == "pass"
            else 0.0 if row and row["outcome"] == "fail" else None,
            "failure_category": "model_failure" if row and row["outcome"] == "fail"
            else "timeout" if row and row["outcome"] == "timeout"
            else "infrastructure_failure" if row and row["outcome"] == "infra_error" else None,
            "artifact_path": str(pathlib.Path("benchmark-results") / root.name / (row["phase"] if row else "primary") / (row["suite"] if row else next(key for key, value in SUITES.items() if value == task["suite"])) / task["task"]),
        })
        tasks.append(task)
    return tasks


def quality(tasks, suite):
    selected = [task for task in tasks if task["suite"] == suite]
    attempted = [task for task in selected if task["outcome"] not in {"pending", "running"}]
    passed = sum(task["outcome"] == "pass" for task in attempted)
    result = {
        "passed": passed,
        "failed": sum(task["outcome"] == "fail" for task in attempted),
        "timeouts": sum(task["outcome"] == "timeout" for task in attempted),
        "infrastructure_errors": sum(task["outcome"] == "infra_error" for task in attempted),
        "attempted": len(attempted),
        "total": len(selected),
        "completion_percent": round(100 * len(attempted) / len(selected), 1) if selected else None,
        "pass_rate_percent": round(100 * passed / len(attempted), 1) if attempted else None,
    }
    if suite == "livebench_reasoning_subset":
        scores = [task["score_percent"] for task in attempted if task["score_percent"] is not None]
        result["mean_score_percent"] = round(sum(scores) / len(scores), 1) if scores else None
    return result


def iso(epoch):
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=pathlib.Path, required=True)
    parser.add_argument("--template", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--status", choices=("running", "completed", "failed", "interrupted"), required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--reasoning-effort", default="")
    parser.add_argument("--maximum-context-tokens", type=int, required=True)
    parser.add_argument("--benchmark-input-limit-tokens", type=int, required=True)
    parser.add_argument("--context-source", choices=("api_models", "configured", "fallback"), required=True)
    parser.add_argument("--swe-count", type=int, default=10)
    parser.add_argument("--terminal-count", type=int, default=10)
    parser.add_argument("--reasoning-count", type=int, default=5)
    parser.add_argument("--prefill-measurement", default="")
    parser.add_argument("--decode-measurement", default="")
    parser.add_argument("--aggregate-measurement", action="append", default=[])
    args = parser.parse_args()
    if not (0 <= args.swe_count <= 10 and 0 <= args.terminal_count <= 10 and 0 <= args.reasoning_count <= 5):
        parser.error("task counts must be within SWE 0-10, Terminal 0-10 and LiveBench 0-5")

    root = args.run_dir
    template = json.loads(args.template.read_text())
    rows = read_rows(root / "task-results.tsv")
    active_rows = read_rows(root / "active-task.tsv")
    active = active_rows[-1] if active_rows else None
    limits = {"swe_bench_verified": args.swe_count, "terminal_bench_2_1": args.terminal_count, "livebench_reasoning_subset": args.reasoning_count}
    selected_tasks = [
        task for suite, count in limits.items()
        for task in [item for item in template["tasks"] if item["suite"] == suite][:count]
    ]
    known = {(task["suite"], task["task"]) for task in selected_tasks}
    unknown = [(row.get("suite"), row.get("task")) for row in rows if (SUITES.get(row.get("suite")), row.get("task")) not in known]
    if unknown:
        raise SystemExit(f"Result template is missing benchmark tasks: {unknown}")
    tasks = build_tasks(root, selected_tasks, rows, active)
    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    start_path, end_path = root / "benchmark-start-epoch", root / "benchmark-end-epoch"
    started = int(start_path.read_text()) if start_path.exists() else now
    ended = int(end_path.read_text()) if args.status == "completed" and end_path.exists() else now
    model = {
        "id": args.model_id,
        "name": args.model_name,
        "organization": None,
        "source_url": None,
        "reasoning_effort": args.reasoning_effort or None,
        "maximum_context_tokens": args.maximum_context_tokens,
        "benchmark_input_limit_tokens": args.benchmark_input_limit_tokens,
        "context_source": args.context_source,
    }
    completed = len(rows)
    current_task = None if not active else {
        "phase": active["phase"],
        "attempt": int(active["attempt"]),
        "suite": SUITES[active["suite"]],
        "task": active["task"],
        "started_at": active["start_utc"],
        "timeout_seconds": int(active["timeout_seconds"]),
        "outcome": "running",
    }
    outcome_counts = {name: sum(row["outcome"] == value for row in rows) for name, value in {
        "passed": "pass", "failed": "fail", "timeouts": "timeout", "infrastructure_errors": "infra_error"
    }.items()}
    docker_info = (root / "preflight" / "docker.txt").read_text().split() if (root / "preflight" / "docker.txt").exists() else []
    environment = {
        "deployment": "openai_compatible_endpoint",
        "api_base_url": args.api_base_url,
        "inference_backend": None,
        "tensor_parallel_size": None,
        "benchmark_host_architecture": docker_info[0] if docker_info else platform.machine(),
        "docker_version": docker_info[1] if len(docker_info) > 1 else None,
        "benchmark_versions": template.get("environment", {}).get("benchmark_versions", {}),
    }
    result = {
        "schema_version": template.get("schema_version", "1.0.0"),
        "generated_at": iso(now),
        "run": {
            "id": root.name,
            "status": args.status,
            "started_at": iso(started),
            "ended_at": iso(ended) if args.status != "running" else None,
            "duration_seconds": max(0, ended - started),
        },
        "progress": {
            "completed": completed,
            "total": len(tasks),
            "completion_percent": round(100 * completed / len(tasks), 1) if tasks else 100.0 if args.status == "completed" else 0.0,
            "current_task": current_task,
            **outcome_counts,
        },
        "selection": {
            "swe_bench_verified": args.swe_count,
            "terminal_bench_2_1": args.terminal_count,
            "livebench_reasoning_subset": args.reasoning_count,
            "total": len(tasks),
        },
        "model": model,
        "environment": environment,
        "quality": {
            "swe_bench_verified": quality(tasks, "swe_bench_verified"),
            "terminal_bench_2_1": quality(tasks, "terminal_bench_2_1"),
            "reasoning": quality(tasks, "livebench_reasoning_subset"),
        },
        "model_service": service_metrics(root, rows, args.prefill_measurement, args.decode_measurement, args.aggregate_measurement),
        "hardware": {
            "telemetry_available": False,
            "reason": "A portable OpenAI-compatible API does not expose host VRAM or swap telemetry.",
            "maximum_vram_usage_gib": None,
            "maximum_swap_usage_gib": None,
        },
        "benchmark_sources": template.get("benchmark_sources", []),
        "tasks": tasks,
        "artifacts": {
            "result_directory": str(pathlib.Path("benchmark-results") / root.name),
            "result_file": str(pathlib.Path("benchmark-results") / root.name / args.output.name),
            "html_report": str(pathlib.Path("benchmark-results") / root.name / args.output.with_suffix(".html").name),
            "run_log": str(pathlib.Path("benchmark-results") / root.name / "run.log"),
            "task_results": str(pathlib.Path("benchmark-results") / root.name / "task-results.tsv"),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n")
    temporary.replace(args.output)


if __name__ == "__main__":
    self_test() if sys.argv[1:] == ["--self-test"] else main()
