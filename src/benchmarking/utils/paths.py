"""Shared paths for benchmark CSV output."""

from pathlib import Path


def benchmark_csv(filename: str) -> str:
    return str(Path("benchmarking") / "results" / filename)
