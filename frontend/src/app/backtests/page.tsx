"use client";

import { useEffect, useState } from "react";
import { fetchRuns, fetchSymbols, fetchStrategies, createBacktest } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export default function BacktestsPage() {
  const [runs, setRuns] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  
  const [open, setOpen] = useState(false);
  const [newRun, setNewRun] = useState({ 
    strategy: "time_breakout", symbol: "BTC-USDT", timeframe: "15m", 
    days: 30, capital: 1000, fee_bps: 5, slippage_bps: 2, leverage: 1, qty_pct: 1.0,
    sl_pct: 0.0, tp_pct: 0.0, trail_pct: 0.0,
    live: false, start: "", end: ""
  });
  
  const [tpLevels, setTpLevels] = useState<string>("");
  const [paramsStr, setParamsStr] = useState("{}");
  const [running, setRunning] = useState(false);
  
  const [symbols, setSymbols] = useState<string[]>([]);
  const [strategies, setStrategies] = useState<string[]>([]);

  async function load() {
    setLoading(true);
    const data = await fetchRuns();
    setRuns(data);
    setLoading(false);
  }

  useEffect(() => {
    load();
    fetchSymbols().then(setSymbols);
    fetchStrategies().then(setStrategies);
  }, []);

  async function handleCreate() {
    let parsedParams: any = {};
    try {
      parsedParams = JSON.parse(paramsStr);
    } catch (e) {
      alert("Invalid JSON params");
      return;
    }
    
    if (tpLevels.trim()) {
      const levels = tpLevels.split(",").map(s => parseFloat(s.trim())).filter(n => !isNaN(n));
      if (levels.length > 0) {
        parsedParams.tp_levels = levels;
      }
    }
    
    setRunning(true);
    try {
      const result = await createBacktest({ ...newRun, params: parsedParams });
      if (result?.ok === false || result?.error) {
        alert("Backtest failed: " + (result.error || result.detail || JSON.stringify(result)));
      } else {
        setOpen(false);
        load();
      }
    } catch (e: any) {
      alert("Backtest error: " + e.message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      <div className="flex justify-between items-center">
        <h1 className="text-4xl font-bold tracking-tight">Historical Backtests</h1>
        <div className="flex gap-4">
          <Button onClick={load} variant="outline" disabled={loading}>Refresh</Button>
          <Button onClick={() => setOpen(true)}>New Backtest</Button>
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
              <DialogHeader>
                <DialogTitle>Run New Backtest</DialogTitle>
              </DialogHeader>
              <div className="space-y-4 py-4">
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Strategy</label>
                    <Select value={newRun.strategy} onValueChange={(val: string | null) => setNewRun({...newRun, strategy: val || ""})}>
                      <SelectTrigger>
                        <SelectValue placeholder="Select Strategy" />
                      </SelectTrigger>
                      <SelectContent>
                        {strategies.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Symbol</label>
                    <Select value={newRun.symbol} onValueChange={(val: string | null) => setNewRun({...newRun, symbol: val || ""})}>
                      <SelectTrigger>
                        <SelectValue placeholder="Select Symbol" />
                      </SelectTrigger>
                      <SelectContent>
                        {symbols.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                
                <h3 className="font-semibold text-lg border-b pb-2 pt-4">Data Source</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2 flex flex-col justify-center">
                    <label className="flex items-center gap-2 text-sm font-medium cursor-pointer">
                      <input type="checkbox" checked={newRun.live} onChange={e => setNewRun({...newRun, live: e.target.checked})} className="rounded border-gray-300 text-primary focus:ring-primary" />
                      Use Live Production Data (vs Testnet)
                    </label>
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Timeframe</label>
                    <Input value={newRun.timeframe} onChange={e => setNewRun({...newRun, timeframe: e.target.value})} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Lookback Days</label>
                    <Input type="number" value={newRun.days || ""} onChange={e => setNewRun({...newRun, days: e.target.value ? Number(e.target.value) : undefined as any})} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Start Date (YYYY-MM-DD)</label>
                    <Input type="text" placeholder="Optional" value={newRun.start} onChange={e => setNewRun({...newRun, start: e.target.value})} />
                  </div>
                </div>
                
                <h3 className="font-semibold text-lg border-b pb-2 pt-4">Financial Settings</h3>
                <div className="grid grid-cols-3 gap-4">
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Capital ($)</label>
                    <Input type="number" value={newRun.capital} onChange={e => setNewRun({...newRun, capital: Number(e.target.value)})} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Leverage (x)</label>
                    <Input type="number" step="0.1" value={newRun.leverage} onChange={e => setNewRun({...newRun, leverage: Number(e.target.value)})} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Order Qty (%)</label>
                    <Input type="number" step="0.1" value={newRun.qty_pct} onChange={e => setNewRun({...newRun, qty_pct: Number(e.target.value)})} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Fee (bps)</label>
                    <Input type="number" step="0.1" value={newRun.fee_bps} onChange={e => setNewRun({...newRun, fee_bps: Number(e.target.value)})} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Slippage (bps)</label>
                    <Input type="number" step="0.1" value={newRun.slippage_bps} onChange={e => setNewRun({...newRun, slippage_bps: Number(e.target.value)})} />
                  </div>
                </div>
                
                <h3 className="font-semibold text-lg border-b pb-2 pt-4">Risk Management</h3>
                <div className="grid grid-cols-3 gap-4">
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Stop Loss %</label>
                    <Input type="number" step="0.1" value={newRun.sl_pct} onChange={e => setNewRun({...newRun, sl_pct: Number(e.target.value)})} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Take Profit %</label>
                    <Input type="number" step="0.1" value={newRun.tp_pct} onChange={e => setNewRun({...newRun, tp_pct: Number(e.target.value)})} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Trailing Stop %</label>
                    <Input type="number" step="0.1" value={newRun.trail_pct} onChange={e => setNewRun({...newRun, trail_pct: Number(e.target.value)})} />
                  </div>
                </div>
                
                <h3 className="font-semibold text-lg border-b pb-2 pt-4">Strategy Parameters</h3>
                <div className="space-y-2">
                   <label className="text-sm font-medium">Multiple TP Points (%)</label>
                   <Input type="text" placeholder="e.g. 2, 4, 6 (comma separated)" value={tpLevels} onChange={e => setTpLevels(e.target.value)} />
                   <p className="text-xs text-muted-foreground">Will inject as `tp_levels` array in JSON params.</p>
                </div>
                <div className="space-y-2">
                  <p className="text-xs text-muted-foreground">JSON overrides (e.g. <code>{`{"ema_fast": 9, "ema_slow": 21}`}</code>)</p>
                  <textarea 
                    className="w-full h-24 p-3 font-mono text-sm bg-black text-green-400 rounded-md"
                    value={paramsStr}
                    onChange={e => setParamsStr(e.target.value)}
                  />
                </div>
              </div>
              <DialogFooter>
                <Button onClick={handleCreate} disabled={running}>{running ? "Running..." : "Run Backtest"}</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>
      
      <Card>
        <CardHeader>
          <CardTitle>Run History</CardTitle>
          <CardDescription>View all historical backtest runs and their performance.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Run ID</TableHead>
                <TableHead>Strategy</TableHead>
                <TableHead>Symbol</TableHead>
                <TableHead>Resolution</TableHead>
                <TableHead>Return %</TableHead>
                <TableHead>Date</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.map((run: any) => (
                <TableRow key={run.id}>
                  <TableCell className="font-mono text-xs">
                    <a href={`/backtests/${run.id}`} className="text-blue-500 hover:underline">{run.id}</a>
                  </TableCell>
                  <TableCell className="font-medium">{run.strategy}</TableCell>
                  <TableCell>{run.symbol}</TableCell>
                  <TableCell>{run.resolution}</TableCell>
                  <TableCell>
                    <Badge variant={run.return_pct >= 0 ? 'default' : 'destructive'}>
                      {run.return_pct?.toFixed(2)}%
                    </Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{new Date(run.created_at).toLocaleDateString()}</TableCell>
                </TableRow>
              ))}
              {runs.length === 0 && !loading && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground py-6">
                    No backtest runs found.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
