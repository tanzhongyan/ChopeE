"""The checkout micro-benchmark runs in-process and reports its keys (plan 05c API-10)."""
from __future__ import annotations

import json

import bench_checkout


def test_bench_runs_and_reports_keys(tmp_path, capsys):
    out = tmp_path / "r.json"
    assert bench_checkout.main(["--requests", "50", "--concurrency", "10", "--json-out", str(out)]) == 0
    printed = json.loads(capsys.readouterr().out)
    saved = json.loads(out.read_text())
    assert printed == saved
    for key in ("p50_ms", "p95_ms", "p99_ms", "requests_per_s"):
        assert printed[key] > 0
    assert printed["p50_ms"] <= printed["p95_ms"] <= printed["p99_ms"]
    assert printed["status_counts"] == {"202": 50}
