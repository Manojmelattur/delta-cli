"use client";

import { useState, useEffect } from "react";
import { scanMarket, fetchSymbols, fetchStrategies } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export default function ScanPage() {
  const [params, setParams] = useState({
    strategy: "time_breakout",
    symbol: "",
    timeframe: "15m",
    top: 10,
    days: 30,
    capital: 10000,
    fee_bps: 5.0,
    slippage_bps: 2.0,
    sl_pct: 1.2,
    tp_pct: 2.4,
    trail_pct: 0.8,
    sort_by: "pnl",
    min_trades: 1,
    profitable_only: false,
    qty_pct: 1.0,
    leverage: 1.0,
    adx_filter: false,
    save: false,
    live: false
  });
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [symbols, setSymbols] = useState<string[]>([]);
  const [strategies, setStrategies] = useState<string[]>([]);

  useEffect(() => {
    fetchSymbols().then(setSymbols).catch(() => setSymbols([]));
    fetchStrategies().then(setStrategies).catch(() => setStrategies([]));
  }, []);
  
  async function runScan() {
    setLoading(true);
    setResult(null);
    try {
      const payload: any = { ...params };
      if (!payload.symbol || payload.symbol === "ALL") delete payload.symbol;
      if (!payload.strategy || payload.strategy === "ALL") delete payload.strategy;
      const res = await scanMarket(payload);
      setResult(res.output || "No output returned.");
    } catch (err: any) {
      setResult(`Error: ${err.message}`);
    }
    setLoading(false);
  }

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      <div className="flex justify-between items-center">
        <h1 className="text-4xl font-bold tracking-tight">Market Scanner</h1>
        <Button onClick={runScan} disabled={loading} size="lg">
          {loading ? "Scanning..." : "Run Scanner"}
        </Button>
      </div>
      
      <Card>
        <CardHeader>
          <CardTitle>Scanner Configuration</CardTitle>
          <CardDescription>Configure market sweep and backtest parameters.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="grid grid-cols-4 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Strategy</label>
              <Select value={params.strategy} onValueChange={(val: string | null) => setParams({...params, strategy: val || ""})}>
                <SelectTrigger>
                  <SelectValue placeholder="Select Strategy" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ALL">(All Strategies)</SelectItem>
                  {strategies.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Symbol</label>
              <Select value={params.symbol} onValueChange={(val: string | null) => setParams({...params, symbol: val || ""})}>
                <SelectTrigger>
                  <SelectValue placeholder="Select Symbol" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ALL">(Scan Universe)</SelectItem>
                  {symbols.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Timeframe</label>
              <Input value={params.timeframe} onChange={(e) => setParams({...params, timeframe: e.target.value})} />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Top N Assets</label>
              <Input type="number" value={params.top} onChange={(e) => setParams({...params, top: Number(e.target.value)})} />
            </div>
            <div className="space-y-2 pt-8 flex items-center gap-2">
              <input type="checkbox" checked={params.live} onChange={(e) => setParams({...params, live: e.target.checked})} className="h-4 w-4 rounded border-gray-300" />
              <label className="text-sm font-medium">Use Live Data (Testnet off)</label>
            </div>
          </div>
          
          <h3 className="font-semibold text-sm border-b pb-1">Backtest Settings</h3>
          <div className="grid grid-cols-6 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Days</label>
              <Input type="number" value={params.days} onChange={(e) => setParams({...params, days: Number(e.target.value)})} />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Capital</label>
              <Input type="number" value={params.capital} onChange={(e) => setParams({...params, capital: Number(e.target.value)})} />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Leverage</label>
              <Input type="number" step="0.1" value={params.leverage} onChange={(e) => setParams({...params, leverage: Number(e.target.value)})} />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Qty %</label>
              <Input type="number" step="0.1" value={params.qty_pct} onChange={(e) => setParams({...params, qty_pct: Number(e.target.value)})} />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Fee (BPS)</label>
              <Input type="number" step="0.1" value={params.fee_bps} onChange={(e) => setParams({...params, fee_bps: Number(e.target.value)})} />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Slippage</label>
              <Input type="number" step="0.1" value={params.slippage_bps} onChange={(e) => setParams({...params, slippage_bps: Number(e.target.value)})} />
            </div>
          </div>
          
          <h3 className="font-semibold text-sm border-b pb-1">Risk Management</h3>
          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Stop Loss %</label>
              <Input type="number" step="0.1" value={params.sl_pct} onChange={(e) => setParams({...params, sl_pct: Number(e.target.value)})} />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Take Profit %</label>
              <Input type="number" step="0.1" value={params.tp_pct} onChange={(e) => setParams({...params, tp_pct: Number(e.target.value)})} />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Trailing Stop %</label>
              <Input type="number" step="0.1" value={params.trail_pct} onChange={(e) => setParams({...params, trail_pct: Number(e.target.value)})} />
            </div>
          </div>

          <h3 className="font-semibold text-sm border-b pb-1">Filters</h3>
          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Sort By</label>
              <Select value={params.sort_by} onValueChange={(val: string | null) => setParams({...params, sort_by: val || ""})}>
                <SelectTrigger>
                  <SelectValue placeholder="Sort By" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="pnl">PnL</SelectItem>
                  <SelectItem value="sharpe">Sharpe</SelectItem>
                  <SelectItem value="winrate">Win Rate</SelectItem>
                  <SelectItem value="dd">Drawdown</SelectItem>
                  <SelectItem value="return">Return</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Min Trades</label>
              <Input type="number" value={params.min_trades} onChange={(e) => setParams({...params, min_trades: Number(e.target.value)})} />
            </div>
            <div className="space-y-2 pt-8 flex items-center gap-2">
              <input type="checkbox" checked={params.profitable_only} onChange={(e) => setParams({...params, profitable_only: e.target.checked})} className="h-4 w-4 rounded border-gray-300" />
              <label className="text-sm font-medium">Profitable Only</label>
            </div>
            <div className="space-y-2 pt-8 flex items-center gap-2">
              <input type="checkbox" checked={params.adx_filter} onChange={(e) => setParams({...params, adx_filter: e.target.checked})} className="h-4 w-4 rounded border-gray-300" />
              <label className="text-sm font-medium">ADX Regime Filter</label>
            </div>
            <div className="space-y-2 pt-8 flex items-center gap-2">
              <input type="checkbox" checked={params.save} onChange={(e) => setParams({...params, save: e.target.checked})} className="h-4 w-4 rounded border-gray-300" />
              <label className="text-sm font-medium">Save to DB</label>
            </div>
          </div>
        </CardContent>
      </Card>
      
      {result && (
        <Card>
          <CardHeader>
            <CardTitle>Scan Results</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="p-4 bg-black text-green-400 rounded-md overflow-x-auto text-xs font-mono whitespace-pre-wrap">
              {result}
            </pre>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
