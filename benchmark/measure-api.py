#!/usr/bin/env python3
"""Measure one OpenAI-compatible streaming endpoint without extra packages."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import statistics
import time
import uuid
from http.client import HTTPException
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def generated_text(chunk):
    choices = chunk.get("choices") or []
    if not choices:
        return ""
    delta = choices[0].get("delta") or {}
    return delta.get("reasoning") or delta.get("reasoning_content") or delta.get("content") or ""


def http_error_outcome(code, detail):
    try:
        detail = json.loads(detail).get("message", detail)
    except (ValueError, AttributeError):
        pass
    if code == 400 and "prompt length" in detail and "max_num_tokens" in detail:
        return (3, f"SKIPPED: the model server cannot process the benchmark's fixed prompt.\n"
                f"Server response: {detail}\n"
                "Increase the server's request-token limit and rerun. The benchmark will not shorten its prompt.")
    return (1, f"Model API HTTP {code}: {detail}")


def complete_stream(first_token_at, usage):
    return first_token_at is not None and isinstance(usage, dict) and all(
        isinstance(usage.get(key), int) for key in ("prompt_tokens", "completion_tokens")
    )


def run_once(endpoint, api_key, model, prompt_lines, max_tokens, reasoning_effort):
    nonce = uuid.uuid4().hex
    context = "\n".join(
        f"{nonce}-{i}: def transform_{i}(value): return (value * 17 + {i}) % 1000003"
        for i in range(prompt_lines)
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": f"Performance test {nonce}. Follow the final instruction."},
            {"role": "user", "content": context + "\nOutput only the letter X repeatedly."},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
        "ignore_eos": True,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    request = Request(
        endpoint.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    started = time.perf_counter()
    first_token_at = None
    usage = None
    stream_events = 0
    saw_done = False
    content_type = "unknown"
    try:
        with urlopen(request, timeout=900) as response:
            content_type = response.headers.get("Content-Type", "unknown")
            for raw_line in response:
                line = raw_line.decode(errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    saw_done = True
                    continue
                if not data:
                    continue
                chunk = json.loads(data)
                stream_events += 1
                if first_token_at is None and generated_text(chunk):
                    first_token_at = time.perf_counter()
                if chunk.get("usage"):
                    usage = chunk["usage"]
    except HTTPError as error:
        code, message = http_error_outcome(error.code, error.read(4096).decode(errors="replace"))
        print(message, file=sys.stderr)
        raise SystemExit(code) from error
    except (OSError, HTTPException, json.JSONDecodeError) as error:
        print(f"Model API streaming failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    finished = time.perf_counter()
    if not complete_stream(first_token_at, usage):
        print(
            "SKIPPED: streaming response did not provide token timing and usage; accurate TTFT/TPS cannot be measured. "
            f"first_token_seen={first_token_at is not None}, usage_seen={usage is not None}, "
            f"SSE_events={stream_events}, done={saw_done}, content_type={content_type}. "
            "Check the model server's streaming support and logs.",
            file=sys.stderr,
        )
        raise SystemExit(3)

    prompt_tokens = usage["prompt_tokens"]
    completion_tokens = usage["completion_tokens"]
    ttft = first_token_at - started
    decode_seconds = max(finished - first_token_at, 1e-9)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "ttft_seconds": ttft,
        "total_seconds": finished - started,
        "prefill_tps_approx": prompt_tokens / ttft,
        "decode_tps": max(completion_tokens - 1, 0) / decode_seconds,
    }


def aggregate_batch(results, batch_seconds, concurrency):
    generated = sum(result["completion_tokens"] for result in results)
    aggregate_tps = generated / max(batch_seconds, 1e-9)
    return {
        "concurrency": concurrency,
        "prompt_tokens": sum(result["prompt_tokens"] for result in results),
        "completion_tokens": sum(result["completion_tokens"] for result in results),
        "batch_seconds": batch_seconds,
        "aggregate_generation_tps": aggregate_tps,
        "effective_per_user_tps": aggregate_tps / concurrency,
        "mean_request_ttft_seconds": statistics.mean(result["ttft_seconds"] for result in results),
        "per_request_ttft_seconds": [result["ttft_seconds"] for result in results],
        "mean_request_decode_tps": statistics.mean(result["decode_tps"] for result in results),
    }


def run_concurrent(endpoint, api_key, model, prompt_lines, max_tokens, reasoning_effort, concurrency):
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(run_once, endpoint, api_key, model, prompt_lines, max_tokens, reasoning_effort)
            for _ in range(concurrency)
        ]
        results = [future.result() for future in futures]
    return aggregate_batch(results, time.perf_counter() - started, concurrency)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default=os.getenv("OPENAI_BASE_URL", "http://127.0.0.1:8000/v1"))
    parser.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY", "dummy"))
    parser.add_argument("--model")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--warmup-runs", type=int, default=0)
    parser.add_argument("--prompt-lines", type=int, default=800)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--reasoning-effort", default=os.getenv("OPENAI_REASONING_EFFORT"))
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json-only", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        assert generated_text({"choices": [{"delta": {"content": "X"}}]}) == "X"
        assert generated_text({"choices": [{"delta": {"reasoning": "Z"}}]}) == "Z"
        assert generated_text({"choices": [{"delta": {"reasoning_content": "Y"}}]}) == "Y"
        assert http_error_outcome(400, '{"message":"prompt length (51767) exceeds max_num_tokens (4096)"}')[0] == 3
        assert http_error_outcome(401, "unauthorized")[0] == 1
        assert not complete_stream(None, None)
        assert complete_stream(1, {"prompt_tokens": 10, "completion_tokens": 2})
        batch = aggregate_batch([
            {"prompt_tokens": 10, "completion_tokens": 101, "ttft_seconds": 1, "decode_tps": 50},
            {"prompt_tokens": 10, "completion_tokens": 101, "ttft_seconds": 3, "decode_tps": 50},
        ], 2, 2)
        assert batch["completion_tokens"] == 202 and batch["aggregate_generation_tps"] == 101
        assert batch["effective_per_user_tps"] == 50.5
        assert batch["mean_request_ttft_seconds"] == 2
        print("self-test passed")
        return

    if args.runs < 1 or args.warmup_runs < 0 or args.concurrency < 1:
        parser.error("--runs and --concurrency must be positive; --warmup-runs cannot be negative")
    if not args.model:
        parser.error("--model is required")

    for _ in range(args.warmup_runs):
        if args.concurrency == 1:
            run_once(args.endpoint, args.api_key, args.model, args.prompt_lines, args.max_tokens, args.reasoning_effort)
        else:
            run_concurrent(
                args.endpoint, args.api_key, args.model, args.prompt_lines,
                args.max_tokens, args.reasoning_effort, args.concurrency,
            )

    runs = []
    for number in range(1, args.runs + 1):
        if args.concurrency == 1:
            result = run_once(args.endpoint, args.api_key, args.model, args.prompt_lines, args.max_tokens, args.reasoning_effort)
        else:
            result = run_concurrent(
                args.endpoint, args.api_key, args.model, args.prompt_lines,
                args.max_tokens, args.reasoning_effort, args.concurrency,
            )
        result["run"] = number
        runs.append(result)
        if not args.json_only:
            print(json.dumps(result), flush=True)

    measured = (
        ("prompt_tokens", "completion_tokens", "ttft_seconds", "total_seconds", "prefill_tps_approx", "decode_tps")
        if args.concurrency == 1 else
        ("prompt_tokens", "completion_tokens", "batch_seconds", "aggregate_generation_tps", "effective_per_user_tps", "mean_request_ttft_seconds", "mean_request_decode_tps")
    )
    summary = {
        "model": args.model,
        "concurrency": args.concurrency,
        "warmup_runs": args.warmup_runs,
        "runs": runs,
        "average": {
            key: statistics.mean(run[key] for run in runs)
            for key in measured
        },
        "median": {
            key: statistics.median(run[key] for run in runs)
            for key in measured
        },
    }
    print(json.dumps(summary) if args.json_only else json.dumps(summary["average"], indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
