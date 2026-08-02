import { readFileSync } from "node:fs";
import { describe, it, expect } from "vitest";
import { runStream, type RiskParams } from "../../src/lib/deployments/risk-core";

interface Stream {
  name: string;
  params: RiskParams;
  marks: number[];
}
interface Golden {
  name: string;
  events: unknown[];
}

const streams: Stream[] = JSON.parse(readFileSync("tests/fixtures/risk-streams.json", "utf8"));
const golden: Golden[] = JSON.parse(readFileSync("tests/fixtures/risk-expected.json", "utf8"));

describe("risk-core parity (TS reference)", () => {
  it("has one golden entry per stream", () => {
    expect(golden.map((g) => g.name)).toEqual(streams.map((s) => s.name));
  });

  for (const s of streams) {
    it(`stream: ${s.name} — event ordering + sl_move detection`, () => {
      const events = runStream(s.params, s.marks);
      const g = golden.find((x) => x.name === s.name)!;
      expect(events).toEqual(g.events);

      // Structural invariants that hold for every stream:
      // 1. First event is always `entry`.
      expect(events[0]?.kind).toBe("entry");
      // 2. Exit events, if any, only appear as the last event.
      const exitIdx = events.findIndex((e) => e.kind.startsWith("exit_"));
      if (exitIdx >= 0) expect(exitIdx).toBe(events.length - 1);
      // 3. trail_arm / be_arm each fire at most once.
      expect(events.filter((e) => e.kind === "trail_arm").length).toBeLessThanOrEqual(1);
      expect(events.filter((e) => e.kind === "be_arm").length).toBeLessThanOrEqual(1);
      // 4. Within a tick, canonical order is trail_arm → be_arm → sl_move → exit.
      //    (Approximated here by ensuring sl_move never precedes an arm event
      //    at the same mark.)
      const order: Record<string, number> = {
        trail_arm: 0,
        be_arm: 1,
        sl_move: 2,
        exit_sl: 3,
        exit_tp: 3,
        exit_trail: 3,
      };
      let prevKey: number | null = null;
      let prevMark: number | null = null;
      for (const e of events.slice(1)) {
        if (prevMark === e.mark && prevKey != null && order[e.kind] != null) {
          expect(order[e.kind]).toBeGreaterThanOrEqual(prevKey);
        }
        prevMark = e.mark;
        prevKey = order[e.kind] ?? null;
      }
    });
  }
});
