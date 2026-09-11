#!/usr/bin/env python3
"""Run one pinned LiveBench reasoning question against an OpenAI-compatible API."""

import argparse
import datetime as dt
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path


def normalize(value):
    return value.strip().lower().replace("-", " ")


def zebra_score(ground_truth, answer):
    expected = ground_truth.split(",")
    matches = re.findall(r"<solution>(.*?)</solution>", answer, re.I | re.S)
    actual = (matches[-1] if matches else answer.strip().splitlines()[-1]).split(",")
    correct = sum(
        normalize(want) == normalize(got).replace("position", "").strip()
        or normalize(want) in normalize(got).replace("position", "").strip()
        for want, got in zip(expected, actual)
    )
    return ((correct == len(expected)) + correct / len(expected)) / 2


def spatial_score(ground_truth, answer):
    wanted = normalize(ground_truth)
    candidates = [normalize(value) for value in re.findall(r"\*\*([^*]+)\*\*", answer)[-3:]]
    candidates += [normalize(value) for value in re.findall(r"\\(?:boxed|fbox)\{([^{}]+)\}", answer)[-1:]]
    word_to_number = {
        "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
        "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
        "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
        "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
        "eighteen": "18", "nineteen": "19", "twenty": "20",
    }
    return int(any(value == wanted or word_to_number.get(value) == wanted for value in candidates))


def score(question, answer):
    if question["task"] == "zebra_puzzle":
        return zebra_score(question["ground_truth"], answer)
    if question["task"] == "spatial":
        return spatial_score(question["ground_truth"], answer)
    raise ValueError(f"Unsupported reasoning task: {question['task']}")


def call_api(api_base, api_key, model, question, max_tokens, reasoning_effort, timeout):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": question["prompt"]}],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    payload = json.dumps(payload).encode()
    request = urllib.request.Request(
        f"{api_base.rstrip('/')}/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def run(args):
    questions = json.loads(args.questions.read_text())
    question = next((item for item in questions if item["id"] == args.question_id), None)
    if question is None:
        raise ValueError(f"Unknown question ID: {args.question_id}")

    started = dt.datetime.now(dt.timezone.utc)
    before = time.monotonic()
    response = call_api(
        args.api_base, args.api_key, args.model, question,
        args.max_tokens, args.reasoning_effort, args.timeout,
    )
    duration = time.monotonic() - before
    message = response["choices"][0]["message"]
    answer = message.get("content") or message.get("reasoning") or message.get("reasoning_content") or ""
    result_score = score(question, answer)
    result = {
        "id": question["id"],
        "question_id": question["question_id"],
        "task": question["task"],
        "difficulty": question["difficulty"],
        "release_date": question["release_date"],
        "source": question["source"],
        "description": question["description"],
        "prompt": question["prompt"],
        "started_utc": started.isoformat(),
        "duration_seconds": round(duration, 3),
        "outcome": "pass" if result_score == 1 else "fail",
        "score": result_score,
        "ground_truth": question["ground_truth"],
        "answer": answer,
        "usage": response.get("usage", {}),
        "response_id": response.get("id"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("id", "outcome", "score", "duration_seconds", "usage")}))


def self_test(questions_path):
    questions = json.loads(questions_path.read_text())
    required = {"id", "question_id", "task", "difficulty", "release_date", "source", "description", "ground_truth", "prompt"}
    assert len(questions) == 5
    assert len({item["id"] for item in questions}) == 5
    assert all(required <= item.keys() and item["task"] in {"zebra_puzzle", "spatial"} for item in questions)
    assert zebra_score("alpha, 2", "work\n<solution>alpha, 2</solution>") == 1
    assert zebra_score("alpha, 2", "<solution>alpha, 3</solution>") == 0.25
    assert spatial_score("2", "reasoning\n**two**") == 1
    assert spatial_score("2", r"reasoning\n\boxed{2}") == 1
    assert spatial_score("2", "reasoning\n**3**") == 0
    print("reasoning self-test passed")


def main():
    default_questions = Path(__file__).with_name("reasoning-questions.json")
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", type=Path, default=default_questions)
    parser.add_argument("--question-id")
    parser.add_argument("--api-base")
    parser.add_argument("--api-key", default="dummy")
    parser.add_argument("--model")
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--reasoning-effort")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test(args.questions)
        return
    missing = [name for name in ("question_id", "api_base", "model", "output") if not getattr(args, name)]
    if missing:
        parser.error("missing arguments: " + ", ".join("--" + name.replace("_", "-") for name in missing))
    try:
        run(args)
    except (OSError, ValueError, KeyError, IndexError, json.JSONDecodeError, urllib.error.URLError) as error:
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps({"id": args.question_id, "outcome": "infra_error", "error": str(error)}, indent=2) + "\n")
        raise SystemExit(f"reasoning request failed: {error}")


if __name__ == "__main__":
    main()
