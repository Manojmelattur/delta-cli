"""Parity test: Python risk_core must produce the same event sequences as the
TS reference at `src/lib/deployments/risk-core.ts` for the shared fixtures.

Regenerate the golden after intentional algorithm changes:
    bun tests/parity/generate-golden.ts
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from delta_bt.risk_core import RiskParams, run_stream

ROOT = Path(__file__).resolve().parents[1]
STREAMS = json.loads((ROOT / "fixtures" / "risk-streams.json").read_text())
GOLDEN = json.loads((ROOT / "fixtures" / "risk-expected.json").read_text())
GOLDEN_BY_NAME = {g["name"]: g for g in GOLDEN}


def _to_params(d: dict) -> RiskParams:
    return RiskParams(
        side=d["side"], entry=float(d["entry"]),
        sl_pct=float(d.get("sl_pct") or 0),
        tp_pct=float(d.get("tp_pct") or 0),
        trail_pct=float(d.get("trail_pct") or 0),
        trail_activate_pct=float(d.get("trail_activate_pct") or 0),
        breakeven_after_pct=float(d.get("breakeven_after_pct") or 0),
    )


def test_golden_covers_all_streams():
    assert [g["name"] for g in GOLDEN] == [s["name"] for s in STREAMS]


@pytest.mark.parametrize("stream", STREAMS, ids=lambda s: s["name"])
def test_stream_matches_golden(stream):
    params = _to_params(stream["params"])
    events = run_stream(params, [float(m) for m in stream["marks"]])
    expected = GOLDEN_BY_NAME[stream["name"]]["events"]

    # Compare structurally: kinds first (fast, human-readable failures) then
    # every numeric field.
    assert [e["kind"] for e in events] == [e["kind"] for e in expected], (
        f"{stream['name']}: event ordering diverged from TS reference"
    )
    for got, want in zip(events, expected):
        for k in ("mark", "peak", "trough", "profit_pct"):
            assert got[k] == pytest.approx(want[k], abs=1e-6), (stream["name"], k, got, want)
        if want["sl_px"] is None:
            assert got["sl_px"] is None, (stream["name"], "sl_px")
        else:
            assert got["sl_px"] == pytest.approx(want["sl_px"], abs=1e-6), (stream["name"], "sl_px")


def test_structural_invariants():
    for s in STREAMS:
        events = run_stream(_to_params(s["params"]), [float(m) for m in s["marks"]])
        assert events[0]["kind"] == "entry", s["name"]
        assert sum(1 for e in events if e["kind"] == "trail_arm") <= 1, s["name"]
        assert sum(1 for e in events if e["kind"] == "be_arm") <= 1, s["name"]
        exits = [i for i, e in enumerate(events) if e["kind"].startswith("exit_")]
        if exits:
            assert exits == [len(events) - 1], s["name"]
