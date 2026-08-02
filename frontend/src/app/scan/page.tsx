"use client";

import { useState, useEffect } from "react";
import { scanMarket, fetchSymbols, fetchStrategies, createDeployment } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useRouter } from "next/navigation";

export default function ScanPage() {
  const router = useRouter();
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
    sort_by: "return_pct",
    min_trades: 1,
    profitable_only: false,
    qty_pct: 1.0,
    leverage: 1.0,
    adx_filter: false,
    adx_len: 14,
    adx_trend_min: 25,
    adx_range_max: 20,
    adx_exit_on_flip: false,
    adx_tighten_trail_on_flip: false,
    save: false,
    live: false,
    json_output: true
  });
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<any[]>([]);
  const [errorStr, setErrorStr] = useState<string | null>(null);
  const [symbols, setSymbols] = useState<string[]>([]);
  const [strategies, setStrategies] = useState<string[]>([]);

  useEffect(() => {
    fetchSymbols().then(setSymbols).catch(() => setSymbols([]));
    fetchStrategies().then(setStrategies).catch(() => setStrategies([]));
  }, []);
  
  async function runScan() {
    setLoading(true);
    setResults([]);
    setErrorStr(null);
    try {
      const payload: any = { ...params };
      if (!payload.symbol || payload.symbol === "ALL") delete payload.symbol;
      if (!payload.strategy || payload.strategy === "ALL") delete payload.strategy;
      const res = await scanMarket(payload);
      if (res.output) {
        try {
          const parsed = JSON.parse(res.output);
          setResults(parsed);
        } catch(e) {
          setErrorStr(res.output);
        }
      }
    } catch (err: any) {
      setErrorStr(`Error: ${err.message}`);
    }
    setLoading(false);
  }

  async function handleDeploy(r: any) {
    try {
      const depName = `${r.strategy}_${r.symbol}_${Math.floor(Math.random() * 1000)}`;
      await createDeployment({
        name: depName,
        venue: "paper",
        strategy: r.strategy,
        symbol: r.symbol,
        timeframe: params.timeframe,
        lot: 1.0,
        sl_pct: params.sl_pct,
        tp_pct: params.tp_pct,
        trail_pct: params.trail_pct,
        params: {}
      });
      alert(`Successfully deployed ${depName}`);
    } catch(e: any) {
      alert("Error deploying: " + e.message);
    }
  }

  async function handleDeployTop3() {
    if (results.length === 0) return;
    const top3 = results.slice(0, 3);
    let successCount = 0;
    for (const r of top3) {
      try {
        const depName = `${r.strategy}_${r.symbol}_${Math.floor(Math.random() * 1000)}`;
        await createDeployment({
          name: depName,
          venue: "paper",
          strategy: r.strategy,
          symbol: r.symbol,
          timeframe: params.timeframe,
          lot: 1.0,
          sl_pct: params.sl_pct,
          tp_pct: params.tp_pct,
          trail_pct: params.trail_pct,
          params: {}
        });
        successCount++;
      } catch(e: any) {
        console.error("Failed deploying", r.strategy, r.symbol, e);
      }
    }
    alert(`Successfully auto-deployed ${successCount} strategies.`);
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
                  <SelectItem value="return_pct">Return</SelectItem>
                  <SelectItem value="win_rate_pct">Win Rate</SelectItem>
                  <SelectItem value="profit_factor">Profit Factor</SelectItem>
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
          
          {params.adx_filter && (
            <>
              <h3 className="font-semibold text-sm border-b pb-1 mt-6">ADX Filter Configuration</h3>
              <div className="grid grid-cols-5 gap-4 mt-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium">ADX Length</label>
                  <Input type="number" value={params.adx_len} onChange={(e) => setParams({...params, adx_len: Number(e.target.value)})} />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">ADX Trend Min</label>
                  <Input type="number" value={params.adx_trend_min} onChange={(e) => setParams({...params, adx_trend_min: Number(e.target.value)})} />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">ADX Range Max</label>
                  <Input type="number" value={params.adx_range_max} onChange={(e) => setParams({...params, adx_range_max: Number(e.target.value)})} />
                </div>
                <div className="space-y-2 pt-8 flex items-center gap-2">
                  <input type="checkbox" checked={params.adx_exit_on_flip} onChange={(e) => setParams({...params, adx_exit_on_flip: e.target.checked})} className="h-4 w-4 rounded border-gray-300" />
                  <label className="text-sm font-medium leading-none">Exit On Flip</label>
                </div>
                <div className="space-y-2 pt-8 flex items-center gap-2">
                  <input type="checkbox" checked={params.adx_tighten_trail_on_flip} onChange={(e) => setParams({...params, adx_tighten_trail_on_flip: e.target.checked})} className="h-4 w-4 rounded border-gray-300" />
                  <label className="text-sm font-medium leading-none">Tighten Trail</label>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>
      
      {errorStr && (
        <Card>
          <CardHeader>
            <CardTitle className="text-red-500">Scan Error</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="p-4 bg-black text-red-400 rounded-md overflow-x-auto text-xs font-mono whitespace-pre-wrap">
              {errorStr}
            </pre>
          </CardContent>
        </Card>
      )}

      {results.length > 0 && (
        <Card>
          <CardHeader className="flex flex-row justify-between items-center">
            <div>
              <CardTitle>Scan Results</CardTitle>
              <CardDescription>Found {results.length} valid combinations.</CardDescription>
            </div>
            <Button onClick={handleDeployTop3} variant="secondary">Deploy Top 3</Button>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Strategy</TableHead>
                  <TableHead>Return %</TableHead>
                  <TableHead>Trades</TableHead>
                  <TableHead>Win Rate %</TableHead>
                  <TableHead>Profit Factor</TableHead>
                  <TableHead>Max DD %</TableHead>
                  <TableHead className="text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {results.map((r, i) => (
                  <TableRow key={i}>
                    <TableCell className="font-medium">{r.symbol}</TableCell>
                    <TableCell>{r.strategy}</TableCell>
                    <TableCell className={r.return_pct > 0 ? "text-green-500" : "text-red-500"}>
                      {r.return_pct.toFixed(2)}%
                    </TableCell>
                    <TableCell>{r.trades}</TableCell>
                    <TableCell>{r.win_rate_pct.toFixed(1)}%</TableCell>
                    <TableCell>{r.profit_factor.toFixed(2)}</TableCell>
                    <TableCell className="text-red-400">{r.max_drawdown_pct.toFixed(2)}%</TableCell>
                    <TableCell className="text-right">
                      <Button size="sm" onClick={() => handleDeploy(r)}>Deploy</Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
