import { describe, expect, it } from "vitest";
import {
  computeLotMargin,
  contractUnitLabel,
  type DeltaProduct,
} from "../src/lib/delta/trade.server";

const btcUsdProduct: DeltaProduct = {
  id: 27,
  symbol: "BTCUSD",
  contract_type: "perpetual_futures",
  tick_size: "0.5",
  contract_value: "0.001",
  state: "live",
  initial_margin: "0.5",
  settlement_asset: { symbol: "USD" },
  quoting_asset: { symbol: "USD" },
};

describe("Delta lot margin math", () => {
  it("treats BTCUSD size as lots, not BTC quantity", () => {
    const margin = computeLotMargin({
      product: btcUsdProduct,
      lots: 1,
      price: 65_916.0825,
      leverage: 1,
    });

    expect(margin.contractValue).toBe(0.001);
    expect(margin.contractUnit).toBe("BTC");
    expect(margin.notional).toBeCloseTo(65.9160825, 8);
    expect(margin.required).toBeCloseTo(65.9160825, 8);
  });

  it("reduces user margin requirement when leverage increases", () => {
    const margin = computeLotMargin({
      product: btcUsdProduct,
      lots: 1,
      price: 65_916.0825,
      leverage: 10,
    });

    expect(margin.notional).toBeCloseTo(65.9160825, 8);
    expect(margin.required).toBeCloseTo(6.59160825, 8);
  });

  it("keeps the product minimum margin floor", () => {
    const margin = computeLotMargin({
      product: btcUsdProduct,
      lots: 1,
      price: 65_916.0825,
      leverage: 500,
    });

    expect(margin.required).toBeCloseTo(0.3295804125, 8);
  });

  it("derives the lot unit from the symbol when product metadata omits it", () => {
    expect(contractUnitLabel(btcUsdProduct)).toBe("BTC");
  });
});
