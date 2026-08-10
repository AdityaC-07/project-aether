"""Run benchmark comparisons across prompt versions and models.

Usage examples:
  python scripts/benchmark_runner.py --dataset benchmarks.json --output report.json
  python scripts/benchmark_runner.py --dataset benchmarks.json --output report.json ^
    --model llama-3.1-70b-versatile --config baseline:support=3.0.0,opposition=2.0.0 ^
    --config candidate:support=2.0.0,opposition=2.0.0
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.benchmark import (  # noqa: E402
    BenchmarkConfiguration,
    BenchmarkRunner,
    TestDataset,
)


def _parse_prompt_overrides(text: str) -> Dict[str, str]:
    overrides: Dict[str, str] = {}
    if not text:
        return overrides
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"Invalid prompt override '{part}'. Use prompt=version.")
        name, version = part.split("=", 1)
        overrides[name.strip()] = version.strip()
    return overrides


def _parse_configs(values: List[str], default_model: str) -> List[BenchmarkConfiguration]:
    if not values:
        return [BenchmarkConfiguration(name="default", model=default_model)]

    configs: List[BenchmarkConfiguration] = []
    for value in values:
        if ":" not in value:
            raise ValueError("Config must use NAME[:MODEL]:prompt=version,prompt2=version2")
        header, overrides = value.split(":", 1)
        if "@" in header:
            name, model = header.split("@", 1)
            model = model.strip() or default_model
        else:
            name, model = header, default_model
        configs.append(
            BenchmarkConfiguration(
                name=name.strip(),
                model=model,
                prompt_versions=_parse_prompt_overrides(overrides),
            )
        )
    return configs


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run benchmark comparisons over prompt versions and models.")
    parser.add_argument("--dataset", required=True, help="Path to a benchmark dataset JSON file.")
    parser.add_argument("--output", required=True, help="Path to write the benchmark report JSON.")
    parser.add_argument("--model", default="llama-3.1-70b-versatile", help="Default Groq model to evaluate.")
    parser.add_argument(
        "--config",
        action="append",
        default=[],
        help="Benchmark config as NAME[@MODEL]:prompt=version,prompt2=version2. May be repeated.",
    )
    args = parser.parse_args()

    dataset = TestDataset.from_file(args.dataset)
    configs = _parse_configs(args.config, args.model)

    runner = BenchmarkRunner(dataset, configs)
    report = await runner.run()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report.to_json(indent=2), encoding="utf-8")

    print(f"Wrote benchmark report to {output_path}")
    print(json.dumps(report.model_dump()["configurations"], indent=2))


if __name__ == "__main__":
    asyncio.run(main())
