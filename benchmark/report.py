#!/usr/bin/env python3
"""Render a standalone HTML report from one benchmark result JSON file."""

import argparse
import html
import json
from pathlib import Path
from string import Template


def render(data, template_text):
    model = data.get("model", {})
    title = f"{model.get('name') or model.get('id') or 'AI model'} benchmark report"
    embedded = json.dumps(data, separators=(",", ":")).replace("<", "\\u003c")
    return Template(template_text).substitute(
        page_title=html.escape(title),
        benchmark_json=embedded,
    )


def self_test():
    output = render({"model": {"name": "<unsafe>"}}, "$page_title|$benchmark_json")
    assert "&lt;unsafe&gt;" in output
    assert "\\u003cunsafe>" in output
    print("report self-test passed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument("--template", type=Path, default=Path(__file__).with_name("report-template.html"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.input:
        parser.error("--input is required")

    output = args.output or args.input.with_suffix(".html")
    page = render(json.loads(args.input.read_text()), args.template.read_text())
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(page)
    temporary.replace(output)
    print(output)


if __name__ == "__main__":
    main()
