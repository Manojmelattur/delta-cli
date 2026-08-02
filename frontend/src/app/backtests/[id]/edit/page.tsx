"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { fetchSymbols, fetchStrategies, createBacktest, fetchRunSummary } from "@/lib/api";
import { Card, CardContent, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const DEFAULT_STRATEGY_PARAMS: Record<string, string> = {
  "ema_cross": '{\n  "fast": 9,\n  "slow": 21\n}',
  "ema3": '{\n  "fast": 9,\n  "medium": 21,\n  "slow": 50\n}',
  "ema_rsi": '{\n  "ema_period": 20,\n  "rsi_period": 14,\n  "rsi_overbought": 70,\n  "rsi_oversold": 30\n}',
  "macd": '{\n  "fast": 12,\n  "slow": 26,\n  "signal": 9\n}',
  "rsi_mr": '{\n  "rsi_period": 14,\n  "overbought": 70,\n  "oversold": 30\n}',
  "smc_ob": '{\n  "lookback": 50,\n  "mitigation_threshold": 0.5\n}',
  "supertrend_mom": '{\n  "period": 10,\n  "multiplier": 3.0\n}',
  "time_breakout": '{\n  "start_time": "09:15",\n  "end_time": "15:30"\n}',
  "vwap": '{\n  "mult": 1.0\n}',
  "vwap_bands": '{\n  "mult1": 1.0,\n  "mult2": 2.0\n}',
  "bollinger": '{\n  "period": 20,\n  "std_dev": 2.0\n}',
  "turtle": '{\n  "entry_period": 20,\n  "exit_period": 10\n}'
};

export default function EditBacktestPage() {
  const router = useRouter();
  const params = useParams();
  const id = params.id as string;

  const [newRun, setNewRun] = useState({ 
    strategy: "time_breakout", symbol: "BTC-USDT", timeframe: "15m", 
    days: 30, capital: 1000, fee_bps: 5, slippage_bps: 2, leverage: 1, qty_pct: 1.0,
    sl_pct: 0.0, tp_pct: 0.0, trail_pct: 0.0,
    live: false, start: "", end: ""
  });
  
  const [paramsStr, setParamsStr] = useState("{}");
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(true);
  
  const [symbols, setSymbols] = useState<string[]>([]);
  const [strategies, setStrategies] = useState<string[]>([]);

  useEffect(() => {
    fetchSymbols().then(setSymbols);
    fetchStrategies().then(setStrategies);
    
    // Load existing backtest data
    fetchRunSummary(id).then(data => {
      if (data && data.run) {
        setNewRun({
          strategy: data.run.strategy || "time_breakout",
          symbol: data.run.symbol || "BTC-USDT",
          timeframe: data.run.resolution || "15m",
          days: data.run.days || 30,
          capital: data.run.capital || 1000,
          fee_bps: data.run.fee_bps || 5,
          slippage_bps: data.run.slippage_bps || 2,
          leverage: data.run.leverage || 1,
          qty_pct: data.run.qty_pct || 1.0,
          sl_pct: data.run.sl_pct || 0.0,
          tp_pct: data.run.tp_pct || 0.0,
          trail_pct: data.run.trail_pct || 0.0,
          live: data.run.live || false,
          start: data.run.start || "",
          end: data.run.end || ""
        });
        
        let pStr = data.run.params_json || "{}";
        let p: any = {};
        try {
          p = typeof pStr === 'string' ? JSON.parse(pStr.replace(/'/g, '"').replace(/True/g, 'true').replace(/False/g, 'false')) : pStr;
        } catch (e) {
          console.warn("Failed to parse params_json, falling back to empty object", e);
          p = {};
        }

        if (p.use_kelly_sizer === undefined) {
          p.use_kelly_sizer = true;
          p.kelly_fraction = 0.5;
        }
        if (p.use_maker_limit === undefined) {
          p.use_maker_limit = true;
          p.maker_limit_offset_bps = 5;
        }
        if (p.use_atr_risk === undefined) {
          p.use_atr_risk = true;
          p.atr_multiplier = 2.0;
        }
        if (p.risk_type === undefined) p.risk_type = "percentage";
        
        if (p.multiple_tp === undefined) {
          p.multiple_tp = true;
          p.tp_levels = p.tp_levels || [
            { price_pct: 1.5, qty_pct: 50 },
            { price_pct: 3.0, qty_pct: 50 }
          ];
        }
        if (p.multiple_sl === undefined) {
          p.multiple_sl = true;
          p.sl_levels = p.sl_levels || [
            { price_pct: -1.0, qty_pct: 50 },
            { price_pct: -2.0, qty_pct: 50 }
          ];
        }
        if (p.multiple_tsl === undefined) {
          p.multiple_tsl = true;
          p.tsl_levels = p.tsl_levels || [
            { activation_pct: 1.0, trail_pct: 0.5, qty_pct: 50 },
            { activation_pct: 2.0, trail_pct: 1.0, qty_pct: 50 }
          ];
        }
        
        setParamsStr(JSON.stringify(p, null, 2));
      }
      setLoading(false);
    });
  }, [id]);



  async function handleCreate() {
    let parsedParams: any = {};
    try {
      parsedParams = JSON.parse(paramsStr);
    } catch (e) {
      alert("Invalid JSON params");
      return;
    }
    
    setRunning(true);
    try {
      const result = await createBacktest({ ...newRun, params: parsedParams });
      if (result?.ok === false || result?.error) {
        alert("Backtest failed: " + (result.error || result.detail || JSON.stringify(result)));
      } else {
        router.push("/backtests");
      }
    } catch (e: any) {
      alert("Backtest error: " + e.message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="p-8 max-w-4xl mx-auto space-y-8">
      <div className="flex items-center gap-4">
        <Button variant="outline" onClick={() => router.push(`/backtests/${id}`)}>← Cancel</Button>
        <h1 className="text-4xl font-bold tracking-tight">Edit & Rerun Backtest</h1>
      </div>

      {loading ? <div className="p-4">Loading original backtest...</div> : (
      <Card>
        <CardContent className="space-y-6 pt-6">
          <div className="space-y-4">
            <h3 className="font-semibold text-sm text-muted-foreground uppercase tracking-wider">Configuration & Data Source</h3>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2 col-span-2">
                <label className="text-sm font-medium">Strategy</label>
                <Select 
                  value={newRun.strategy} 
                  onValueChange={(val: string) => {
                    setNewRun({...newRun, strategy: val});
                    let pStr = DEFAULT_STRATEGY_PARAMS[val] || "{}";
                    try {
                      let p = JSON.parse(pStr);
                      p.use_kelly_sizer = true;
                      p.use_maker_limit = true;
                      p.use_atr_risk = true;
                      p.risk_type = "percentage";
                      p.multiple_tp = true;
                      p.tp_levels = p.tp_levels || [
                        { price_pct: 1.5, qty_pct: 50 },
                        { price_pct: 3.0, qty_pct: 50 }
                      ];
                      p.multiple_sl = true;
                      p.sl_levels = p.sl_levels || [
                        { price_pct: -1.0, qty_pct: 50 },
                        { price_pct: -2.0, qty_pct: 50 }
                      ];
                      p.multiple_tsl = true;
                      p.tsl_levels = p.tsl_levels || [
                        { activation_pct: 1.0, trail_pct: 0.5, qty_pct: 50 },
                        { activation_pct: 2.0, trail_pct: 1.0, qty_pct: 50 }
                      ];
                      pStr = JSON.stringify(p, null, 2);
                    } catch {}
                    setParamsStr(pStr);
                  }}
                >
                  <SelectTrigger className="w-full h-10"><SelectValue placeholder="Select Strategy" /></SelectTrigger>
                  <SelectContent>
                    {strategies.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2 col-span-2">
                <label className="text-sm font-medium">Symbol</label>
                <Input 
                  list="backtest-symbols-list"
                  value={newRun.symbol} 
                  onChange={e => setNewRun({...newRun, symbol: e.target.value.toUpperCase()})}
                  placeholder="e.g. BTCUSD"
                />
                <datalist id="backtest-symbols-list">
                  {symbols.map(s => <option key={s} value={s} />)}
                </datalist>
              </div>
              <div className="space-y-2 col-span-2 flex items-center pt-2">
                <label className="flex items-center gap-2 text-sm font-medium cursor-pointer">
                  <input type="checkbox" checked={newRun.live} onChange={e => setNewRun({...newRun, live: e.target.checked})} className="rounded border-gray-300 text-primary focus:ring-primary" />
                  Use Live Production Data
                </label>
              </div>
              <div className="space-y-2 col-span-2">
                <label className="text-sm font-medium">Timeframe</label>
                <Input value={newRun.timeframe} onChange={e => setNewRun({...newRun, timeframe: e.target.value})} />
              </div>
              <div className="space-y-2 col-span-2">
                <label className="text-sm font-medium">Lookback Days</label>
                <Input type="number" value={newRun.days || ""} onChange={e => setNewRun({...newRun, days: e.target.value ? Number(e.target.value) : undefined as any})} />
              </div>
              <div className="space-y-2 col-span-2">
                <label className="text-sm font-medium">Start Date (YYYY-MM-DD)</label>
                <Input type="text" placeholder="Optional" value={newRun.start} onChange={e => setNewRun({...newRun, start: e.target.value})} />
              </div>
            </div>
          </div>

          <div className="space-y-4">
            <h3 className="font-semibold text-sm text-muted-foreground uppercase tracking-wider">Financial Settings</h3>
            <div className="grid grid-cols-5 gap-4">
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
          </div>

          <div className="space-y-4">
            <h3 className="font-semibold text-sm text-muted-foreground uppercase tracking-wider">Basic Risk Overrides</h3>
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
          </div>

          <div className="space-y-4">
            <div className="flex justify-between items-center">
              <h3 className="font-semibold text-sm text-muted-foreground uppercase tracking-wider">Strategy Params & Advanced Risk</h3>
              <span className="text-[10px] text-muted-foreground">JSON Configuration</span>
            </div>
            <textarea 
              className="w-full h-96 p-4 font-mono text-sm bg-black text-green-400 rounded-md border border-zinc-800 focus:outline-none focus:border-green-500 placeholder:text-zinc-600"
              value={paramsStr}
              onChange={e => setParamsStr(e.target.value)}
              placeholder={`{
  "use_kelly_sizer": true,
  "kelly_fraction": 0.5,
  "use_maker_limit": true,
  "maker_limit_offset_bps": 5,
  "use_atr_risk": true,
  "atr_multiplier": 2.0,
  "risk_type": "percentage",
  "multiple_tp": true,
  "tp_levels": [
    { "price_pct": 1.5, "qty_pct": 50 },
    { "price_pct": 3.0, "qty_pct": 50 }
  ],
  "multiple_sl": true,
  "sl_levels": [
    { "price_pct": -1.0, "qty_pct": 50 },
    { "price_pct": -2.0, "qty_pct": 50 }
  ],
  "multiple_tsl": true,
  "tsl_levels": [
    { "activation_pct": 1.0, "trail_pct": 0.5, "qty_pct": 50 },
    { "activation_pct": 2.0, "trail_pct": 1.0, "qty_pct": 50 }
  ]
}`}
            />
          </div>
        </CardContent>
        <CardFooter className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => router.push(`/backtests/${id}`)}>Cancel</Button>
          <Button onClick={handleCreate} disabled={running}>{running ? "Running..." : "Run Backtest"}</Button>
        </CardFooter>
      </Card>
      )}
    </div>
  );
}
