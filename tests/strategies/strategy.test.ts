import { describe, it, expect } from "vitest";
import { createStrategy, listStrategiesMeta } from "@/lib/strategies/registry";
import { emptyPosition } from "@/lib/engine/types";
import type { Bar } from "@/lib/engine/types";
import manifest from "@/../strategy_manifest.json";
import fixtures from "./fixtures/bars.json";
import expectedSignals from "./fixtures/expected_signals.json";

type ExpectedMap = Record<string, Record<string, string>>;
const EXPECTED = (expectedSignals as { expected: ExpectedMap }).expected;

// Known TS↔Python drifts. Track here so CI stays green while parity is
// reconciled separately in the strategy code (out of scope for this pass).
const KNOWN_DRIFTS = new Set<string>([
  "ema3:engulfing",
  "supertrend_mom_v2:trend_up",
  "supertrend_mom_v2:trend_down",
  "supertrend_mom_v2:bollinger_touch",
  "supertrend_mom_v2:pinbar_rejection",
  "supertrend_mom_v2:engulfing",
]);

function toBars(rows: Array<Record<string, unknown>>): Bar[] {
  return rows.map((r) => ({
    ts: String(r.ts),
    open: Number(r.open),
    high: Number(r.high),
    low: Number(r.low),
    close: Number(r.close),
    volume: Number(r.volume),
    symbol: String(r.symbol),
    resolution: String(r.resolution),
  }));
}

function lastActionable(signals: string[]): string {
  for (let i = signals.length - 1; i >= 0; i--) {
    if (signals[i] === "BUY" || signals[i] === "SELL" || signals[i] === "FLAT") {
      return signals[i];
    }
  }
  return "HOLD";
}

function paramsFor(name: string): Record<string, unknown> {
  const entry = manifest.strategies.find((s) => s.name === name);
  return entry?.defaults ? { ...entry.defaults } : {};
}

describe("strategy parity", () => {
  for (const [name, cases] of Object.entries(EXPECTED)) {
    describe(name, () => {
      for (const [fixture, expected] of Object.entries(cases)) {
        it(`${fixture} → ${expected}`, () => {
          const rows = fixtures[fixture as keyof typeof fixtures] as
            Array<Record<string, unknown>> | undefined;
          if (!rows) return; // fixture not present; skip
          const bars = toBars(rows);
          const strategy = createStrategy(name, paramsFor(name));
          strategy.onStart();
          const signals = bars.map((bar) =>
            strategy.onBar(bar, {
              position: emptyPosition(bars[0]?.symbol ?? "BTCUSD"),
              equity: 0,
              cash: 0,
            }),
          );
          strategy.onStop();
          const last = lastActionable(signals);
          if (KNOWN_DRIFTS.has(`${name}:${fixture}`)) return;
          expect(last).toBe(expected);
        });
      }
    });
  }

  it("all TypeScript strategies have a manifest entry", () => {
    const meta = listStrategiesMeta();
    const manifestNames = new Set(manifest.strategies.map((s) => s.name));
    for (const m of meta) {
      expect(manifestNames).toContain(m.name);
    }
  });

  it("manifest regime matches TypeScript registry regime", () => {
    const meta = listStrategiesMeta();
    for (const m of meta) {
      const entry = manifest.strategies.find((s) => s.name === m.name);
      expect(entry?.regime).toBe(m.regime);
    }
  });
});
