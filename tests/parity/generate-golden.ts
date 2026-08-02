// Regenerate the golden expected-events fixture from the TS reference core.
// Run: `bun tests/parity/generate-golden.ts`
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { runStream, type RiskParams } from "../../src/lib/deployments/risk-core";

const streams = JSON.parse(readFileSync("tests/fixtures/risk-streams.json", "utf8"));
const out = streams.map((s: { name: string; params: RiskParams; marks: number[] }) => ({
  name: s.name,
  events: runStream(s.params, s.marks),
}));
mkdirSync("tests/fixtures", { recursive: true });
writeFileSync("tests/fixtures/risk-expected.json", JSON.stringify(out, null, 2) + "\n");
console.log(`wrote ${out.length} scenarios`);
