import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { buildTradesFromEvents, type RiskEventRow } from "@/lib/deployments/risk-summary";
import { TradeAppendixRow } from "@/routes/bots.$id.report";

// Golden snapshot tests: render the /bots/$id/report appendix card for
// each trade in a curated multi-trade stream, and assert that the rendered
// text values match what `risk_summary` derives from the same timeline.
// If the appendix template or the reducer drift out of sync, both the
// inline snapshot and the value assertions will fail loudly.

const T0 = Date.parse("2026-01-01T00:00:00Z");
const at = (min: number) => new Date(T0 + min * 60_000).toISOString();
const ev = (min: number, kind: string, extra: Partial<RiskEventRow> = {}): RiskEventRow => ({
  ts: at(min),
  kind,
  ...extra,
});

// Three back-to-back trades exercising the full risk vocabulary:
//   #1 long winner: trail_arm + be_arm + 2 sl_moves + tp_hit
//   #2 short loser: no arms, no sl_moves, straight sl_hit
//   #3 long open  : trail_arm only, still open at end of stream
const stream: RiskEventRow[] = [
  ev(0, "entry", { side: "buy", qty: 1, price: 100, sl_px: 95 }),
  ev(5, "trail_arm", { price: 101.5, profit_pct: 1.5, sl_px: 95, peak: 101.5 }),
  ev(6, "be_arm", { price: 102, profit_pct: 2.0, sl_px: 100, peak: 102 }),
  ev(7, "sl_move", { price: 103, profit_pct: 3.0, sl_px: 101, peak: 103 }),
  ev(8, "sl_move", { price: 104, profit_pct: 4.0, sl_px: 102, peak: 104 }),
  ev(10, "tp_hit", { price: 105, pnl: 5, peak: 105, trough: 99 }),

  ev(20, "entry", { side: "sell", qty: 2, price: 200 }),
  ev(23, "sl_hit", { price: 210, pnl: -20, peak: 200, trough: 199 }),

  ev(40, "entry", { side: "buy", qty: 1, price: 50, sl_px: 47.5 }),
  ev(44, "trail_arm", { price: 51, profit_pct: 2.0, sl_px: 47.5, peak: 51 }),
];

const trades = buildTradesFromEvents(stream);

// Reduce rendered HTML to a stable text snapshot: strip tags, collapse
// whitespace, mask absolute timestamps. Class names and shadcn wrapper
// markup change across versions and would produce noisy snapshot churn.
const textSnapshot = (html: string) =>
  html
    .replace(/<[^>]+>/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/2026-[0-9T:.\-Z]+/g, "<TS>")
    .replace(/\s+/g, " ")
    .trim();

describe("bots.$id.report — appendix rendering matches risk_summary", () => {
  it("splits the stream into 3 trades (1 tp, 1 sl, 1 open)", () => {
    expect(trades.map((t) => t.reason)).toEqual(["tp_hit", "sl_hit", null]);
  });

  it("trade #1 (long winner): rendered values match risk_summary", () => {
    const t = trades[0];
    const html = renderToStaticMarkup(<TradeAppendixRow t={t} />);
    const r = t.risk_summary;

    // Sanity: risk_summary is what we expect for the crafted stream
    expect(r.sl_move_count).toBe(2);
    expect(r.time_to_trail_arm_ms).toBe(5 * 60_000);
    expect(r.time_to_be_arm_ms).toBe(6 * 60_000);
    expect(r.time_to_first_arm_ms).toBe(5 * 60_000);
    expect(r.mfe_pct).toBeCloseTo(5, 10);
    expect(r.mae_pct).toBeCloseTo(-1, 10);

    // Header chip values from risk_summary appear in the DOM
    expect(html).toContain("Trade #1");
    expect(html).toContain("BUY");
    expect(html).toContain("tp_hit");
    expect(html).toContain("arm 5m 0s");
    expect(html).toContain("2 sl");
    expect(html).toContain("5.00%"); // MFE
    expect(html).toContain("-1.00%"); // MAE
    expect(html).toContain("PnL +5.0000");

    // Detail grid values from the trade record
    expect(html).toContain("100.0000"); // entry px
    expect(html).toContain("105.0000"); // exit px + peak
    expect(html).toContain("99.0000"); // trough
    expect(html).toContain("10m 0s"); // time in trade

    // Trail arm + BE arm cards
    expect(html).toContain("armed @ 101.5000");
    expect(html).toContain("armed @ 102.0000");
    expect(html).toContain("sl → 100.0000"); // be_arm sl_px

    // SL adjustments table shows both moves and the chain from → to
    expect(html).toContain("SL adjustments (2)");
    expect(html).toContain("95.0000 → 101.0000");
    expect(html).toContain("101.0000 → 102.0000");

    // SL adjustments table shows both moves and the chain from → to
    expect(html).toContain("SL adjustments (2)");
    expect(html).toContain("95.0000 → 101.0000");
    expect(html).toContain("101.0000 → 102.0000");

    expect(textSnapshot(html)).toMatchInlineSnapshot(
      `"Trade #1 BUY tp_hit arm 5m 0s · 2 sl · MFE 5.00% · MAE -1.00% PnL +5.0000 Entry 100.0000 <TS> Exit 105.0000 <TS> Time in trade 10m 0s Peak / Trough 105.0000 / 99.0000 Trailing arm armed @ 101.5000 · profit 1.50% · sl → 95.0000 <TS> Breakeven arm armed @ 102.0000 · profit 2.00% · sl → 100.0000 <TS> SL adjustments (2) ts from → to mark profit% <TS> 95.0000 → 101.0000 103.0000 3.00% <TS> 101.0000 → 102.0000 104.0000 4.00%"`,
    );
  });

  it("trade #2 (short loser): rendered values match risk_summary", () => {
    const t = trades[1];
    const html = renderToStaticMarkup(<TradeAppendixRow t={t} />);
    const r = t.risk_summary;

    expect(r.sl_move_count).toBe(0);
    expect(r.time_to_first_arm_ms).toBeNull();
    expect(r.mfe_pct).toBeCloseTo(0.5, 10); // (200-199)/200
    expect(r.mae_pct).toBeCloseTo(-5, 10); // (200-210)/200

    expect(html).toContain("Trade #2");
    expect(html).toContain("SELL");
    expect(html).toContain("sl_hit");
    // "arm —" appears when no arm event fired
    expect(html).toContain("arm —");
    expect(html).toContain("0 sl");
    expect(html).toContain("0.50%"); // MFE
    expect(html).toContain("-5.00%"); // MAE
    expect(html).toContain("PnL -20.0000");
    expect(html).toContain("SL adjustments (0)");
    expect(html).toContain("no adjustments");
    // Both arm boxes must show "not armed"
    expect(html.match(/not armed/g)?.length).toBe(2);
    expect(textSnapshot(html)).toMatchInlineSnapshot(
      `"Trade #2 SELL sl_hit arm — · 0 sl · MFE 0.50% · MAE -5.00% PnL -20.0000 Entry 200.0000 <TS> Exit 210.0000 <TS> Time in trade 3m 0s Peak / Trough 200.0000 / 199.0000 Trailing arm not armed Breakeven arm not armed SL adjustments (0) no adjustments"`,
    );
  });

  it("trade #3 (open long): rendered values match risk_summary", () => {
    const t = trades[2];
    const html = renderToStaticMarkup(<TradeAppendixRow t={t} />);
    const r = t.risk_summary;

    expect(t.exit_ts).toBeNull();
    expect(t.pnl).toBeNull();
    expect(r.time_to_trail_arm_ms).toBe(4 * 60_000);
    expect(r.time_to_be_arm_ms).toBeNull();
    expect(r.sl_move_count).toBe(0);

    expect(html).toContain("Trade #3");
    expect(html).toContain("BUY");
    // Reason badge omitted for open trades → no exit reason chip rendered
    expect(html).not.toContain("tp_hit");
    expect(html).not.toContain("sl_hit");
    // Header risk chip pulls arm time from risk_summary
    expect(html).toContain("arm 4m 0s");
    // Exit block shows "open" instead of a timestamp; PnL is em-dash
    expect(html).toContain(">open<");
    expect(html).toContain("PnL —");
    // Trail arm present, BE arm absent
    expect(html).toContain("armed @ 51.0000");
    expect(html.match(/not armed/g)?.length).toBe(1);
    expect(textSnapshot(html)).toMatchInlineSnapshot(
      `"Trade #3 BUY arm 4m 0s · 0 sl · MFE 2.00% · MAE 0.00% PnL — Entry 50.0000 <TS> Exit — open Time in trade — Peak / Trough 51.0000 / — Trailing arm armed @ 51.0000 · profit 2.00% · sl → 47.5000 <TS> Breakeven arm not armed SL adjustments (0) no adjustments"`,
    );
  });

  it("appendix values line up 1:1 with risk_summary across every trade", () => {
    for (const t of trades) {
      const html = renderToStaticMarkup(<TradeAppendixRow t={t} />);
      expect(html).toContain(`SL adjustments (${t.risk_summary.sl_move_count})`);
      expect(html).toContain(`Trade #${t.index}`);
      if (t.risk_summary.mfe_pct != null) {
        expect(html).toContain(`${t.risk_summary.mfe_pct.toFixed(2)}%`);
      }
      if (t.risk_summary.mae_pct != null) {
        expect(html).toContain(`${t.risk_summary.mae_pct.toFixed(2)}%`);
      }
    }
  });
});
