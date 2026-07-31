"""Pure risk-management core — reference implementation used by parity tests.

Mirrors the logic in `src/lib/deployments/risk-core.ts` and the embedded
logic in `python/delta_bt/scheduler.py`. No DB, no I/O.

Keep in lock-step with `src/lib/deployments/risk-core.ts`. Parity is guarded
by `tests/parity/test_risk_parity.py` against `tests/fixtures/risk-*.json`.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import List, Literal, Optional, Tuple

Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class RiskParams:
    side: Side
    entry: float
    sl_pct: float = 0.0
    tp_pct: float = 0.0
    trail_pct: float = 0.0
    trail_activate_pct: float = 0.0
    breakeven_after_pct: float = 0.0
    sl_type: Literal["pct", "atr", "point"] = "pct"
    tp_type: Literal["pct", "atr", "point"] = "pct"
    trail_type: Literal["pct", "atr", "point"] = "pct"
    atr_val: Optional[float] = None


@dataclass
class RiskState:
    peak: float
    trough: float
    trail_armed: bool = False
    be_armed: bool = False
    last_sl_px: Optional[float] = None


@dataclass
class RiskEvent:
    kind: str
    mark: float
    peak: float
    trough: float
    profit_pct: float
    sl_px: Optional[float]

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "mark": self.mark,
            "peak": self.peak,
            "trough": self.trough,
            "profit_pct": self.profit_pct,
            "sl_px": self.sl_px,
        }


def _r(n: Optional[float], d: int = 6) -> Optional[float]:
    return None if n is None else round(n, d)


def initial_state(p: RiskParams) -> RiskState:
    return RiskState(peak=p.entry, trough=p.entry)


def _calc_sl_px(p: RiskParams, entry: float) -> Optional[float]:
    if not p.sl_pct:
        return None
    if p.sl_type == "point":
        dist = p.sl_pct
    elif p.sl_type == "atr" and p.atr_val:
        dist = p.sl_pct * p.atr_val
    else:  # pct
        dist = entry * (p.sl_pct / 100.0)

    return entry - dist if p.side == "buy" else entry + dist


def _calc_tp_px(p: RiskParams, entry: float) -> Optional[float]:
    if not p.tp_pct:
        return None
    if p.tp_type == "point":
        dist = p.tp_pct
    elif p.tp_type == "atr" and p.atr_val:
        dist = p.tp_pct * p.atr_val
    else:  # pct
        dist = entry * (p.tp_pct / 100.0)

    return entry + dist if p.side == "buy" else entry - dist


def _calc_trail_px(p: RiskParams, base_price: float) -> Optional[float]:
    if not p.trail_pct:
        return None
    if p.trail_type == "point":
        dist = p.trail_pct
    elif p.trail_type == "atr" and p.atr_val:
        dist = p.trail_pct * p.atr_val
    else:  # pct
        dist = base_price * (p.trail_pct / 100.0)

    return base_price - dist if p.side == "buy" else base_price + dist


def effective_sl_px(p: RiskParams, s: RiskState) -> Optional[float]:
    if not p.side or not p.entry:
        return None
    if p.side == "buy":
        sl = _calc_sl_px(p, p.entry)
        if s.be_armed:
            sl = p.entry if sl is None else max(sl, p.entry)
        if p.trail_pct and s.trail_armed:
            t = _calc_trail_px(p, s.peak)
            if t is not None:
                sl = t if sl is None else max(sl, t)
        return sl
    sl = _calc_sl_px(p, p.entry)
    if s.be_armed:
        sl = p.entry if sl is None else min(sl, p.entry)
    if p.trail_pct and s.trail_armed:
        t = _calc_trail_px(p, s.trough)
        if t is not None:
            sl = t if sl is None else min(sl, t)
    return sl


def _profit_pct(p: RiskParams, mark: float) -> float:
    if not p.entry:
        return 0.0
    if p.side == "buy":
        return (mark - p.entry) / p.entry * 100.0
    return (p.entry - mark) / p.entry * 100.0


def _exit_reason(p: RiskParams, s: RiskState, mark: float) -> Optional[str]:
    sl = effective_sl_px(p, s)
    tp = _calc_tp_px(p, p.entry)
    if p.side == "buy":
        if sl is not None and mark <= sl:
            if p.trail_pct and s.trail_armed:
                tpx = _calc_trail_px(p, s.peak)
                sl_base = _calc_sl_px(p, p.entry)
                if tpx is not None and mark <= tpx and (p.sl_pct == 0 or sl_base is None or tpx >= sl_base):
                    return "exit_trail"
            return "exit_sl"
        if tp is not None and mark >= tp:
            return "exit_tp"
        return None
    if sl is not None and mark >= sl:
        if p.trail_pct and s.trail_armed:
            tpx = _calc_trail_px(p, s.trough)
            sl_base = _calc_sl_px(p, p.entry)
            if tpx is not None and mark >= tpx and (p.sl_pct == 0 or sl_base is None or tpx <= sl_base):
                return "exit_trail"
        return "exit_sl"
    if tp is not None and mark <= tp:
        return "exit_tp"
    return None


def step(p: RiskParams, prev: RiskState, mark: float) -> Tuple[RiskState, List[RiskEvent]]:
    events: List[RiskEvent] = []
    peak = max(prev.peak, mark) if p.side == "buy" else prev.peak
    trough = min(prev.trough, mark) if p.side == "sell" else prev.trough
    pp = _profit_pct(p, mark)

    trail_armed = prev.trail_armed or (
        p.trail_pct > 0 and (p.trail_activate_pct <= 0 or pp >= p.trail_activate_pct)
    )
    be_armed = prev.be_armed or (
        p.breakeven_after_pct > 0 and pp >= p.breakeven_after_pct
    )

    nxt = RiskState(peak=peak, trough=trough, trail_armed=trail_armed,
                    be_armed=be_armed, last_sl_px=prev.last_sl_px)
    new_sl = effective_sl_px(p, nxt)

    def _mk(kind: str) -> RiskEvent:
        return RiskEvent(kind=kind, mark=mark, peak=peak, trough=trough,
                         profit_pct=_r(pp), sl_px=_r(new_sl))

    if not prev.trail_armed and trail_armed:
        events.append(_mk("trail_arm"))
    if not prev.be_armed and be_armed:
        events.append(_mk("be_arm"))
    if new_sl is not None and prev.last_sl_px is not None and abs(new_sl - prev.last_sl_px) > 1e-9:
        events.append(_mk("sl_move"))
    ex = _exit_reason(p, nxt, mark)
    if ex:
        events.append(_mk(ex))
    nxt.last_sl_px = new_sl
    return nxt, events


def run_stream(p: RiskParams, marks: List[float]) -> List[dict]:
    s = initial_state(p)
    out: List[dict] = [{
        "kind": "entry",
        "mark": p.entry,
        "peak": p.entry,
        "trough": p.entry,
        "profit_pct": 0,
        "sl_px": _r(effective_sl_px(p, s)),
    }]
    s.last_sl_px = effective_sl_px(p, s)
    for m in marks:
        s, evs = step(p, s, m)
        for e in evs:
            out.append(e.to_dict())
        if any(e.kind.startswith("exit_") for e in evs):
            break
    return out
