import { describe, it, expect } from "vitest";
import { buildTradesFromEvents, type RiskEventRow } from "@/lib/deployments/risk-summary";

// Helpers to build event streams at 1-minute cadence.
const T0 = Date.parse("2026-01-01T00:00:00Z");
const at = (min: number) => new Date(T0 + min * 60_000).toISOString();

const ev = (min: number, kind: string, extra: Partial<RiskEventRow> = {}): RiskEventRow => ({
  ts: at(min),
  kind,
  ...extra,
});

describe("buildTradesFromEvents — risk_summary parity with timeline", () => {
  it("returns no trades for an empty event list", () => {
    expect(buildTradesFromEvents([])).toEqual([]);
  });

  it("emits an empty risk_summary for a bare entry with no risk events", () => {
    const rows: RiskEventRow[] = [ev(0, "entry", { side: "buy", qty: 1, price: 100, sl_px: 95 })];
    const [t] = buildTradesFromEvents(rows);
    // Only the entry mark is tracked, so MFE/MAE collapse to 0 for both sides.
    expect(t.risk_summary).toEqual({
      time_to_trail_arm_ms: null,
      time_to_be_arm_ms: null,
      time_to_first_arm_ms: null,
      sl_move_count: 0,
      final_peak: null,
      final_trough: null,
      mfe_pct: 0,
      mae_pct: 0,
    });
  });

  it("computes arm times, sl_move count, peak/trough, and MFE/MAE for a long winner", () => {
    const rows: RiskEventRow[] = [
      ev(0, "entry", { side: "buy", qty: 1, price: 100, sl_px: 95 }),
      ev(5, "trail_arm", { price: 101.5, profit_pct: 1.5, sl_px: 95, peak: 101.5 }),
      ev(6, "be_arm", { price: 102, profit_pct: 2.0, sl_px: 100, peak: 102 }),
      ev(7, "sl_move", { price: 103, profit_pct: 3.0, sl_px: 101, peak: 103 }),
      ev(8, "sl_move", { price: 104, profit_pct: 4.0, sl_px: 102, peak: 104 }),
      ev(10, "tp_hit", { price: 105, pnl: 5, peak: 105, trough: 99 }),
    ];
    const [t] = buildTradesFromEvents(rows);
    const r = t.risk_summary;

    // Arm timing lines up with the event timestamps
    expect(r.time_to_trail_arm_ms).toBe(5 * 60_000);
    expect(r.time_to_be_arm_ms).toBe(6 * 60_000);
    expect(r.time_to_first_arm_ms).toBe(5 * 60_000);

    // sl_move count matches the number of sl_move events
    expect(r.sl_move_count).toBe(2);
    expect(t.sl_moves).toHaveLength(2);

    // sl_move chain is derived from prior sl_px values
    expect(t.sl_moves[0].from_px).toBe(95);
    expect(t.sl_moves[0].to_px).toBe(101);
    expect(t.sl_moves[1].from_px).toBe(101);
    expect(t.sl_moves[1].to_px).toBe(102);

    // Peak/trough taken from the exit event
    expect(r.final_peak).toBe(105);
    expect(r.final_trough).toBe(99);

    // MFE/MAE from tracked marks (100..105 up, 99 down)
    expect(r.mfe_pct).toBeCloseTo(5, 10); // (105-100)/100
    expect(r.mae_pct).toBeCloseTo(-1, 10); // (99-100)/100
    expect(t.time_in_trade_ms).toBe(10 * 60_000);
    expect(t.reason).toBe("tp_hit");
  });

  it("inverts MFE/MAE for a short trade", () => {
    const rows: RiskEventRow[] = [
      ev(0, "entry", { side: "sell", qty: 1, price: 100 }),
      ev(3, "sl_hit", { price: 102, pnl: -2, peak: 100, trough: 97 }),
    ];
    const [t] = buildTradesFromEvents(rows);
    // For a short: MFE uses min (97 → +3%), MAE uses max (102 → -2%)
    expect(t.risk_summary.mfe_pct).toBeCloseTo(3, 10);
    expect(t.risk_summary.mae_pct).toBeCloseTo(-2, 10);
    expect(t.reason).toBe("sl_hit");
    expect(t.pnl).toBe(-2);
  });

  it("keeps be_arm as first_arm when it fires before trail_arm", () => {
    const rows: RiskEventRow[] = [
      ev(0, "entry", { side: "buy", price: 100 }),
      ev(2, "be_arm", { price: 101, profit_pct: 1.0, sl_px: 100 }),
      ev(5, "trail_arm", { price: 102, profit_pct: 2.0, sl_px: 100 }),
      ev(9, "close", { price: 103, pnl: 3 }),
    ];
    const [t] = buildTradesFromEvents(rows);
    expect(t.risk_summary.time_to_be_arm_ms).toBe(2 * 60_000);
    expect(t.risk_summary.time_to_trail_arm_ms).toBe(5 * 60_000);
    expect(t.risk_summary.time_to_first_arm_ms).toBe(2 * 60_000);
  });

  it("still finalizes risk_summary for an open trade (no exit event)", () => {
    const rows: RiskEventRow[] = [
      ev(0, "entry", { side: "buy", price: 100, sl_px: 95 }),
      ev(4, "trail_arm", { price: 102, profit_pct: 2, sl_px: 95 }),
    ];
    const [t] = buildTradesFromEvents(rows);
    expect(t.exit_ts).toBeNull();
    expect(t.pnl).toBeNull();
    expect(t.risk_summary.time_to_trail_arm_ms).toBe(4 * 60_000);
    expect(t.risk_summary.sl_move_count).toBe(0);
    // MFE/MAE reflect the marks seen so far (100 and 102)
    expect(t.risk_summary.mfe_pct).toBeCloseTo(2, 10);
    expect(t.risk_summary.mae_pct).toBeCloseTo(0, 10);
  });

  it("segments back-to-back trades and resets extremes between them", () => {
    const rows: RiskEventRow[] = [
      ev(0, "entry", { side: "buy", price: 100 }),
      ev(2, "close", { price: 101, pnl: 1, peak: 101, trough: 100 }),
      ev(3, "entry", { side: "sell", price: 200 }),
      ev(5, "sl_hit", { price: 210, pnl: -10, peak: 200, trough: 199 }),
    ];
    const trades = buildTradesFromEvents(rows);
    expect(trades).toHaveLength(2);
    expect(trades[0].side).toBe("buy");
    expect(trades[0].risk_summary.mfe_pct).toBeCloseTo(1, 10);
    expect(trades[0].risk_summary.mae_pct).toBeCloseTo(0, 10);
    // Second trade must not inherit marks from the first
    expect(trades[1].side).toBe("sell");
    expect(trades[1].risk_summary.mfe_pct).toBeCloseTo(0.5, 10); // (200-199)/200
    expect(trades[1].risk_summary.mae_pct).toBeCloseTo(-5, 10); // (200-210)/200
  });

  it("ignores stray non-entry events before any entry", () => {
    const rows: RiskEventRow[] = [
      ev(0, "trail_arm", { price: 100, profit_pct: 1, sl_px: 95 }),
      ev(1, "sl_move", { price: 100, sl_px: 96 }),
      ev(2, "entry", { side: "buy", price: 100 }),
      ev(3, "close", { price: 101, pnl: 1 }),
    ];
    const trades = buildTradesFromEvents(rows);
    expect(trades).toHaveLength(1);
    expect(trades[0].trail_arm).toBeNull();
    expect(trades[0].risk_summary.sl_move_count).toBe(0);
  });

  it("sl_move_count equals sl_moves.length across many moves", () => {
    const rows: RiskEventRow[] = [ev(0, "entry", { side: "buy", price: 100, sl_px: 95 })];
    for (let i = 1; i <= 7; i++) {
      rows.push(ev(i, "sl_move", { price: 100 + i, sl_px: 95 + i }));
    }
    rows.push(ev(10, "close", { price: 108, pnl: 8 }));
    const [t] = buildTradesFromEvents(rows);
    expect(t.risk_summary.sl_move_count).toBe(t.sl_moves.length);
    expect(t.risk_summary.sl_move_count).toBe(7);
    // Chain integrity: each from_px equals the previous to_px
    for (let i = 1; i < t.sl_moves.length; i++) {
      expect(t.sl_moves[i].from_px).toBe(t.sl_moves[i - 1].to_px);
    }
  });
});
