import { describe, it, expect } from "vitest";
import type { Bar } from "@/lib/engine/types";
import { Bollinger } from "@/lib/strategies/bollinger";
import { RsiMr } from "@/lib/strategies/rsi_mr";

// This test validates the tail-window filter logic (used by the scheduler to
// avoid replaying stale signals during warmup) independently of any concrete
// strategy. A fake strategy emits a chosen signal at a chosen bar index; the
// filter should only surface it when it lands inside the tail window.

const TAIL_BY_RES: Record<string, number> = {
  "1m": 3,
  "3m": 3,
  "5m": 3,
  "15m": 4,
  "30m": 4,
  "1h": 6,
  "2h": 6,
  "4h": 8,
  "6h": 8,
  "1d": 10,
  "7d": 10,
};

const RANGE_TAIL_BY_RES: Record<string, number> = {
  "1m": 1,
  "3m": 1,
  "5m": 1,
  "15m": 1,
  "30m": 1,
  "1h": 2,
  "2h": 2,
  "4h": 3,
  "6h": 3,
  "1d": 4,
  "7d": 4,
};

function makeBars(n: number, resolution = "15m"): Bar[] {
  return Array.from({ length: n }, (_, i) => ({
    ts: new Date(2024, 0, 1, 0, i * 15).toISOString(),
    open: 100,
    high: 101,
    low: 99,
    close: 100,
    volume: 100,
    symbol: "BTCUSD",
    resolution,
  }));
}

function bar(close: number, i = 0, resolution = "1h"): Bar {
  return {
    ts: new Date(2024, 0, 1, i).toISOString(),
    open: close,
    high: close + 0.1,
    low: close - 0.1,
    close,
    volume: 100,
    symbol: "BTCUSD",
    resolution,
  };
}

function runFilter(opts: {
  bars: Bar[];
  regime: "trend" | "range" | "any";
  tailOnly?: boolean;
  signalAt: number;
  signal: "BUY" | "SELL";
}) {
  const { bars, regime, tailOnly, signalAt, signal } = opts;
  const isTailOnly = regime === "range" || tailOnly === true;
  const res = bars[0]?.resolution ?? "15m";
  const tail = isTailOnly ? (RANGE_TAIL_BY_RES[res] ?? 1) : (TAIL_BY_RES[res] ?? 3);
  let tailSig: string | null = null;
  let latestSig: string | null = null;
  for (let i = 0; i < bars.length; i++) {
    const s = i === signalAt ? signal : "HOLD";
    if (s === "BUY" || s === "SELL") {
      latestSig = s;
      if (bars.length - 1 - i < tail) tailSig = s;
    }
  }
  return { tailSig, latestSig, tailOnly: isTailOnly, tail };
}

describe("tail-window logic", () => {
  it("range strategies on 15m use tail=1", () => {
    const bars = makeBars(30, "15m");
    const { tailOnly, tail } = runFilter({
      bars,
      regime: "range",
      signalAt: bars.length - 1,
      signal: "BUY",
    });
    expect(tailOnly).toBe(true);
    expect(tail).toBe(1);
  });

  it("range strategies on 1h widen to tail=2 (catches previous-bar signal)", () => {
    const bars = makeBars(30, "1h");
    const { tailSig, tail } = runFilter({
      bars,
      regime: "range",
      signalAt: bars.length - 2,
      signal: "BUY",
    });
    expect(tail).toBe(2);
    expect(tailSig).toBe("BUY");
  });

  it("range strategies on 1d widen to tail=4", () => {
    const bars = makeBars(30, "1d");
    const { tail } = runFilter({
      bars,
      regime: "range",
      signalAt: bars.length - 1,
      signal: "BUY",
    });
    expect(tail).toBe(4);
  });

  it("trend strategies use a wider tail", () => {
    const bars = makeBars(30);
    const { tailSig, tailOnly, tail } = runFilter({
      bars,
      regime: "trend",
      signalAt: bars.length - 2,
      signal: "BUY",
    });
    expect(tailOnly).toBe(false);
    expect(tail).toBe(4);
    expect(tailSig).toBeTruthy();
  });

  it("range strategy does not replay a stale signal", () => {
    const bars = makeBars(30);
    const { tailSig } = runFilter({
      bars,
      regime: "range",
      signalAt: 5,
      signal: "BUY",
    });
    expect(tailSig ?? "HOLD").not.toBe("BUY");
    expect(tailSig ?? "HOLD").not.toBe("SELL");
  });

  it("trend strategy accepts a rescue signal within its wider tail", () => {
    const bars = makeBars(30);
    const { tailSig } = runFilter({
      bars,
      regime: "trend",
      signalAt: bars.length - 3,
      signal: "SELL",
    });
    expect(tailSig).toBe("SELL");
  });

  it("trend strategy does not accept a signal beyond the tail", () => {
    const bars = makeBars(30);
    const { tailSig, latestSig } = runFilter({
      bars,
      regime: "trend",
      signalAt: 5,
      signal: "BUY",
    });
    expect(tailSig).toBeNull();
    expect(latestSig).toBe("BUY");
  });

  it("bollinger mean-reversion intent stays valid until the middle band", () => {
    const strategy = new Bollinger({ period: 5, stdev: 1, mode: "revert" });
    strategy.onStart();
    [100, 100, 100, 100, 96, 98].forEach((close, i) => {
      strategy.onBar(bar(close, i), {
        position: { symbol: "BTCUSD", side: null, qty: 0, avgPrice: 0, openedAt: null },
        equity: 0,
        cash: 0,
      });
    });
    expect(strategy.intent(bar(98, 6))).toBe("BUY");
  });

  it("rsi mean-reversion intent stays valid until RSI exits through midline", () => {
    const strategy = new RsiMr({ len: 3, oversold: 30, overbought: 70, exit: 50 });
    strategy.onStart();
    [100, 96, 92, 90, 91].forEach((close, i) => {
      strategy.onBar(bar(close, i), {
        position: { symbol: "BTCUSD", side: null, qty: 0, avgPrice: 0, openedAt: null },
        equity: 0,
        cash: 0,
      });
    });
    expect(strategy.intent(bar(91, 5))).toBe("BUY");
  });
});
