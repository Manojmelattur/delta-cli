"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle, CardFooter, CardDescription } from "@/components/ui/card";
import Link from "next/link";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";

import { fetchSymbols, fetchStrategies, createDeployment, fetchStrategyManifest } from "@/lib/api";

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

export default function CreateDeploymentPage() {
  const router = useRouter();
  
  const [newDep, setNewDep] = useState({ 
    name: "", venue: "paper", strategy: "time_breakout", symbol: "BTCUSD", timeframe: "15m", 
    lot: 1.0, sl_pct: 0.0, tp_pct: 0.0, trail_pct: 0.0 
  });
  const [newParamsStr, setNewParamsStr] = useState("{}");
  
  const [symbols, setSymbols] = useState<string[]>([]);
  const [strategies, setStrategies] = useState<string[]>([]);
  const [manifestDefaults, setManifestDefaults] = useState<Record<string, any>>({});

  useEffect(() => {
    fetchSymbols().then(setSymbols).catch(() => {});
    fetchStrategies().then(setStrategies).catch(() => {});
    fetchStrategyManifest().then(m => {
      if (m && Array.isArray(m.strategies)) {
        const defaultsMap: Record<string, any> = {};
        m.strategies.forEach((s: any) => {
          defaultsMap[s.name] = s.defaults || {};
        });
        setManifestDefaults(defaultsMap);
      }
    }).catch(() => {});
  }, []);

  async function handleCreate() {
    let parsedParams = {};
    try {
      parsedParams = JSON.parse(newParamsStr);
    } catch (e) {
      alert("Invalid JSON format");
      return;
    }
    try {
      const data = { ...newDep, name: newDep.name || (newDep.strategy + "_" + newDep.symbol + "_" + Math.floor(Math.random()*1000)) };
      await createDeployment({ ...data, params: parsedParams });
      localStorage.removeItem("delta_deploy_params"); // clear it
      router.push("/deployments");
    } catch(e: any) {
      alert("Error: " + e.message);
    }
  }

  // Inject user's requested advanced risk properties on init or load from backtest
  useEffect(() => {
    try {
      const urlParams = new URLSearchParams(window.location.search);
      const isFromBacktest = urlParams.get("from_backtest");
      
      let defaultParams = manifestDefaults[newDep.strategy] || {};
      if (Object.keys(defaultParams).length === 0 && DEFAULT_STRATEGY_PARAMS[newDep.strategy]) {
        try { defaultParams = JSON.parse(DEFAULT_STRATEGY_PARAMS[newDep.strategy]); } catch {}
      }
      
      let pStr = JSON.stringify(defaultParams);
      let baseDep = { ...newDep };

      if (isFromBacktest) {
        const stored = localStorage.getItem("delta_deploy_params");
        if (stored) {
          const parsed = JSON.parse(stored);
          baseDep.strategy = parsed.strategy || newDep.strategy;
          baseDep.symbol = parsed.symbol || newDep.symbol;
          baseDep.timeframe = parsed.timeframe || newDep.timeframe;
          baseDep.sl_pct = parsed.sl_pct || 0.0;
          baseDep.tp_pct = parsed.tp_pct || 0.0;
          baseDep.trail_pct = parsed.trail_pct || 0.0;
          setNewDep(baseDep);
          pStr = typeof parsed.params_json === "object" ? JSON.stringify(parsed.params_json) : parsed.params_json;
        }
      }

      let p: any = {};
      try { p = JSON.parse(pStr); } catch { p = { ...defaultParams }; }
      
      p.use_kelly_sizer = true;
      p.kelly_fraction = 0.5;
      p.use_maker_limit = true;
      p.maker_limit_offset_bps = 5;
      p.use_atr_risk = true;
      p.atr_multiplier = 2.0;
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
      setNewParamsStr(JSON.stringify(p, null, 2));
    } catch {
      // Ignore
    }
  }, [manifestDefaults]);

  return (
    <div className="p-8 max-w-4xl mx-auto space-y-8">
      <div className="flex items-center gap-4">
        <Button variant="outline" onClick={() => router.push("/deployments")}>← Back</Button>
        <h1 className="text-4xl font-bold tracking-tight">Deploy New Live Bot</h1>
      </div>

      <Card>
        <CardContent className="space-y-6 pt-6">
          <div className="space-y-4">
            <h3 className="font-semibold text-sm text-muted-foreground uppercase tracking-wider">Configuration</h3>
            
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2 col-span-2">
                <label className="text-sm font-medium">Name</label>
                <Input value={newDep.name} onChange={(e) => setNewDep({...newDep, name: e.target.value})} placeholder="Auto-generated if empty" />
              </div>
              <div className="space-y-2 col-span-2">
                <label className="text-sm font-medium">Strategy</label>
                <Select 
                  value={newDep.strategy} 
                  onValueChange={v => {
                    if (v) {
                      setNewDep({...newDep, strategy: v});
                      let defaultParams = manifestDefaults[v] || {};
                      if (Object.keys(defaultParams).length === 0 && DEFAULT_STRATEGY_PARAMS[v]) {
                        try { defaultParams = JSON.parse(DEFAULT_STRATEGY_PARAMS[v]); } catch {}
                      }
                      try {
                        let p = { ...defaultParams };
                        p.use_kelly_sizer = true;
                        p.kelly_fraction = 0.5;
                        p.use_maker_limit = true;
                        p.maker_limit_offset_bps = 5;
                        p.use_atr_risk = true;
                        p.atr_multiplier = 2.0;
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
                        setNewParamsStr(JSON.stringify(p, null, 2));
                      } catch {}
                    }
                  }}
                >
                  <SelectTrigger className="w-full h-10"><SelectValue placeholder="Strategy" /></SelectTrigger>
                  <SelectContent>
                    {strategies.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2 col-span-2">
                <label className="text-sm font-medium">Symbol</label>
                <Input 
                  list="symbols-list"
                  value={newDep.symbol} 
                  onChange={e => setNewDep({...newDep, symbol: e.target.value.toUpperCase()})}
                  placeholder="e.g. BTCUSD"
                />
                <datalist id="symbols-list">
                  {symbols.map(s => <option key={s} value={s} />)}
                </datalist>
              </div>
              
              <div className="space-y-2 col-span-2">
                <label className="text-sm font-medium">Timeframe</label>
                <Input value={newDep.timeframe} onChange={(e) => setNewDep({...newDep, timeframe: e.target.value})} />
              </div>
              <div className="space-y-2 col-span-2">
                <label className="text-sm font-medium">Venue</label>
                <Select value={newDep.venue} onValueChange={v => { if (v) setNewDep({...newDep, venue: v}); }}>
                  <SelectTrigger className="w-full h-10"><SelectValue placeholder="Venue" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="paper">Paper</SelectItem>
                    <SelectItem value="live">Live</SelectItem>
                    <SelectItem value="testnet">Testnet</SelectItem>
                    <SelectItem value="paper_live">Paper Live</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2 col-span-2">
                <label className="text-sm font-medium">Position Lot</label>
                <Input type="number" step="0.1" value={newDep.lot} onChange={(e) => setNewDep({...newDep, lot: Number(e.target.value)})} />
              </div>
            </div>
          </div>

          <div className="space-y-4">
            <h3 className="font-semibold text-sm text-muted-foreground uppercase tracking-wider">Risk Management</h3>
            <div className="grid grid-cols-3 gap-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">Stop Loss %</label>
                <Input type="number" step="0.1" value={newDep.sl_pct} onChange={(e) => setNewDep({...newDep, sl_pct: Number(e.target.value)})} />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Take Profit %</label>
                <Input type="number" step="0.1" value={newDep.tp_pct} onChange={(e) => setNewDep({...newDep, tp_pct: Number(e.target.value)})} />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Trailing %</label>
                <Input type="number" step="0.1" value={newDep.trail_pct} onChange={(e) => setNewDep({...newDep, trail_pct: Number(e.target.value)})} />
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
              value={newParamsStr}
              onChange={e => setNewParamsStr(e.target.value)}
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
          <Button variant="ghost" onClick={() => router.push("/deployments")}>Cancel</Button>
          <Button onClick={handleCreate}>Deploy Bot</Button>
        </CardFooter>
      </Card>
    </div>
  );
}
