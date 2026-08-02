"use client";

import { useState, useEffect } from "react";
import { 
  scanMarket, 
  fetchSymbols, 
  fetchStrategies, 
  createDeployment, 
  runAutoDeploy,
  runRankUniverse,
  runSweep
} from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { SortableTable } from "@/components/ui/sortable-table";
import { 
  Play, 
  Sparkles, 
  Cpu, 
  RefreshCw, 
  Terminal, 
  CheckCircle2, 
  Sliders, 
  TrendingUp, 
  Target, 
  Link as LinkIcon
} from "lucide-react";
import Link from "next/link";

export default function ScanPage() {
  const [activeTab, setActiveTab] = useState<"scan" | "sweep" | "rank" | "auto_deploy">("scan");
  
  // Market Scanner state
  const [scanParams, setScanParams] = useState({
    strategy: "ALL",
    symbol: "ALL",
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

  // Strategy Sweep state
  const [sweepParams, setSweepParams] = useState({
    symbol: "BTCUSD",
    resolution: "15m",
    days: 30,
    live: false,
    sl_pct: 0.0,
    tp_pct: 0.0,
    trail_pct: 0.0
  });

  // Rank Universe state
  const [rankParams, setRankParams] = useState({
    top: 15,
    live: false,
    resolution: "1h",
    days: 30
  });

  // Auto Deploy state
  const [autoDeployParams, setAutoDeployParams] = useState({
    venue: "paper",
    live: false,
    top: 5,
    days: 14,
    resolution: "1h",
    size: 1.0,
    sl_pct: 1.5,
    tp_pct: 3.0,
    trail_pct: 1.0,
    symbol: ""
  });

  const [loading, setLoading] = useState(false);
  const [scanResults, setScanResults] = useState<any[]>([]);
  const [sweepResults, setSweepResults] = useState<any[]>([]);
  const [rankResults, setRankResults] = useState<any[]>([]);
  
  const [terminalConsole, setTerminalConsole] = useState<string | null>(null);
  const [errorStr, setErrorStr] = useState<string | null>(null);
  const [successStr, setSuccessStr] = useState<string | null>(null);
  
  const [symbols, setSymbols] = useState<string[]>([]);
  const [strategies, setStrategies] = useState<string[]>([]);

  useEffect(() => {
    fetchSymbols().then(setSymbols).catch(() => setSymbols([]));
    fetchStrategies().then(setStrategies).catch(() => setStrategies([]));
  }, []);

  // Action: Market Scanner (Scan parameter grids)
  async function handleRunScan() {
    setLoading(true);
    setScanResults([]);
    setTerminalConsole(null);
    setErrorStr(null);
    setSuccessStr(null);
    try {
      const payload: any = { ...scanParams };
      if (!payload.symbol || payload.symbol === "ALL") delete payload.symbol;
      if (!payload.strategy || payload.strategy === "ALL") delete payload.strategy;
      
      const res = await scanMarket(payload);
      if (res.output) {
        try {
          const parsed = JSON.parse(res.output);
          setScanResults(parsed);
          setSuccessStr(`Sweep completed successfully! Found ${parsed.length} results.`);
        } catch (e) {
          setTerminalConsole(res.output);
        }
      }
    } catch (err: any) {
      setErrorStr(`Error starting scan: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  // Action: Strategy Sweep
  async function handleRunSweep() {
    setLoading(true);
    setSweepResults([]);
    setTerminalConsole(null);
    setErrorStr(null);
    setSuccessStr(null);
    try {
      const res = await runSweep(sweepParams);
      if (res.ok) {
        setSweepResults(res.results || []);
        setTerminalConsole(res.output || "Execution completed with no output.");
        setSuccessStr(`Strategy sweep on ${sweepParams.symbol} finished!`);
      } else {
        setErrorStr(res.detail || "An unexpected error occurred during execution.");
      }
    } catch (err: any) {
      setErrorStr(`Error: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  // Action: Rank Universe
  async function handleRunRankUniverse() {
    setLoading(true);
    setRankResults([]);
    setTerminalConsole(null);
    setErrorStr(null);
    setSuccessStr(null);
    try {
      const res = await runRankUniverse(rankParams);
      if (res.ok) {
        setRankResults(res.results || []);
        setTerminalConsole(res.output || "Execution completed with no output.");
        setSuccessStr(`Ranked universe successfully! Listed top ${rankParams.top} assets.`);
      } else {
        setErrorStr(res.detail || "An unexpected error occurred during execution.");
      }
    } catch (err: any) {
      setErrorStr(`Error: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  // Action: Auto Deploy
  async function handleRunAutoDeploy() {
    setLoading(true);
    setTerminalConsole(null);
    setErrorStr(null);
    setSuccessStr(null);
    try {
      const payload = { 
        ...autoDeployParams,
        symbol: autoDeployParams.symbol.trim() || undefined
      };
      const res = await runAutoDeploy(payload);
      if (res.ok) {
        setTerminalConsole(res.output || "Execution completed with no output.");
        setSuccessStr("Auto Deploy task successfully executed and deployments provisioned!");
      } else {
        setErrorStr(res.detail || "An unexpected error occurred during execution.");
      }
    } catch (err: any) {
      setErrorStr(`Error starting auto-deploy process: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  async function handleDeploySingle(r: any) {
    try {
      const depName = `Scan_${r.strategy}_${r.symbol}_${Math.floor(Math.random() * 1000)}`;
      await createDeployment({
        name: depName,
        venue: "paper",
        strategy: r.strategy,
        symbol: r.symbol,
        timeframe: scanParams.timeframe,
        lot: 1.0,
        sl_pct: scanParams.sl_pct,
        tp_pct: scanParams.tp_pct,
        trail_pct: scanParams.trail_pct,
        params: {}
      });
      alert(`Successfully deployed ${depName}`);
    } catch (e: any) {
      alert("Error deploying: " + e.message);
    }
  }

  async function handleDeployTop3() {
    if (scanResults.length === 0) return;
    const top3 = scanResults.slice(0, 3);
    let successCount = 0;
    for (const r of top3) {
      try {
        const depName = `Scan_${r.strategy}_${r.symbol}_${Math.floor(Math.random() * 1000)}`;
        await createDeployment({
          name: depName,
          venue: "paper",
          strategy: r.strategy,
          symbol: r.symbol,
          timeframe: scanParams.timeframe,
          lot: 1.0,
          sl_pct: scanParams.sl_pct,
          tp_pct: scanParams.tp_pct,
          trail_pct: scanParams.trail_pct,
          params: {}
        });
        successCount++;
      } catch (e) {
        console.error(e);
      }
    }
    alert(`Successfully deployed ${successCount} strategies.`);
  }

  // Column definitions for SortableTable components
  const scanColumns = [
    { key: "symbol", header: "Symbol", sortable: true, className: "font-semibold text-teal-400" },
    { key: "strategy", header: "Strategy", sortable: true, className: "font-mono text-xs" },
    { 
      key: "return_pct", 
      header: "Return %", 
      sortable: true,
      render: (val: number) => (
        <span className={`font-semibold ${val > 0 ? "text-emerald-400" : "text-red-400"}`}>
          {val > 0 ? "+" : ""}{val.toFixed(2)}%
        </span>
      )
    },
    { key: "trades", header: "Trades", sortable: true },
    { key: "win_rate_pct", header: "Win Rate %", sortable: true, render: (val: number) => `${val.toFixed(1)}%` },
    { key: "profit_factor", header: "Profit Factor", sortable: true, render: (val: number) => val.toFixed(2) },
    { key: "max_drawdown_pct", header: "Max DD %", sortable: true, className: "text-red-400/90", render: (val: number) => `${val.toFixed(2)}%` },
    {
      key: "action",
      header: "Action",
      className: "text-right",
      render: (_: any, row: any) => (
        <Button size="sm" onClick={() => handleDeploySingle(row)} className="bg-teal-500/10 text-teal-300 hover:bg-teal-500/20 h-8">
          Deploy
        </Button>
      )
    }
  ];

  const sweepColumns = [
    { key: "strategy", header: "Strategy", sortable: true, className: "font-mono text-xs font-bold text-emerald-400" },
    { 
      key: "return_pct", 
      header: "Return %", 
      sortable: true,
      render: (val: number) => (
        <span className={`font-semibold ${val > 0 ? "text-emerald-400" : "text-red-400"}`}>
          {val > 0 ? "+" : ""}{val.toFixed(2)}%
        </span>
      )
    },
    { 
      key: "pnl", 
      header: "Net PnL ($)", 
      sortable: true,
      render: (val: number) => (
        <span className={val > 0 ? "text-emerald-400" : "text-red-400"}>
          {val > 0 ? "+" : ""}${val.toFixed(2)}
        </span>
      )
    },
    { key: "sharpe", header: "Sharpe Ratio", sortable: true, render: (val: number) => val.toFixed(2) },
    { key: "win_rate_pct", header: "Win Rate %", sortable: true, render: (val: number) => `${val.toFixed(1)}%` },
    { key: "max_drawdown_pct", header: "Max DD %", sortable: true, className: "text-red-400/90", render: (val: number) => `${val.toFixed(2)}%` },
    { key: "trades", header: "Trades", sortable: true },
    { 
      key: "profit_factor", 
      header: "Profit Factor", 
      sortable: true, 
      render: (val: number) => val > 999999 ? "∞" : val.toFixed(2) 
    }
  ];

  const rankColumns = [
    { key: "rank", header: "Rank", sortable: true, className: "text-center font-mono text-xs text-muted-foreground" },
    { key: "symbol", header: "Symbol", sortable: true, className: "font-semibold text-yellow-400" },
    { 
      key: "regime", 
      header: "Market Regime", 
      sortable: true,
      render: (val: string) => (
        <Badge variant="outline" className={
          val === "trend" 
            ? "border-emerald-500/30 text-emerald-400 bg-emerald-500/5" 
            : val === "range"
              ? "border-cyan-500/30 text-cyan-400 bg-cyan-500/5"
              : "border-border text-muted-foreground"
        }>
          {val.toUpperCase()}
        </Badge>
      )
    },
    { key: "price", header: "Price", sortable: true, className: "font-mono text-xs", render: (val: number) => `$${val.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 4})}` },
    { key: "turnover_usd", header: "24h Turnover (USD)", sortable: true, className: "font-mono text-xs", render: (val: number) => `$${val.toLocaleString(undefined, {maximumFractionDigits: 0})}` },
    { key: "open_interest", header: "Open Interest", sortable: true, className: "font-mono text-xs", render: (val: number) => val.toLocaleString() },
    { key: "funding_pct", header: "Funding Rate", sortable: true, className: "font-mono text-xs", render: (val: number) => `${(val * 100).toFixed(4)}%` },
    { key: "adx", header: "ADX (Trend)", sortable: true, className: "font-mono text-xs", render: (val: number) => val.toFixed(1) },
    { key: "atr_pct", header: "ATR %", sortable: true, className: "font-mono text-xs", render: (val: number) => `${val.toFixed(2)}%` },
    { 
      key: "rs_vs_btc", 
      header: "Strength (vs BTC)", 
      sortable: true, 
      className: "font-mono text-xs", 
      render: (val: number) => (
        <span className={val > 0 ? "text-emerald-400" : "text-red-400"}>
          {val > 0 ? "+" : ""}{val.toFixed(2)}%
        </span>
      )
    }
  ];

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h1 className="text-4xl font-extrabold tracking-tight bg-gradient-to-r from-emerald-400 via-teal-300 to-cyan-400 bg-clip-text text-transparent">
            System Scanner & Rankings
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            Analyze market structures, find best strategy parameters, rank universe gainers, and configure custom auto-deployers.
          </p>
        </div>

        {/* Tab Controls */}
        <div className="flex flex-wrap gap-1 p-1 bg-muted/80 backdrop-blur rounded-lg border border-border/40">
          <button
            onClick={() => { setActiveTab("scan"); setErrorStr(null); setSuccessStr(null); setTerminalConsole(null); }}
            className={`flex items-center gap-2 px-3 py-1.5 text-xs font-semibold rounded-md transition-all ${
              activeTab === "scan"
                ? "bg-teal-500/10 text-teal-400 border border-teal-500/20 shadow-md"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Cpu className="w-3.5 h-3.5" />
            Market Scanner
          </button>
          <button
            onClick={() => { setActiveTab("sweep"); setErrorStr(null); setSuccessStr(null); setTerminalConsole(null); }}
            className={`flex items-center gap-2 px-3 py-1.5 text-xs font-semibold rounded-md transition-all ${
              activeTab === "sweep"
                ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 shadow-md"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Sliders className="w-3.5 h-3.5" />
            Strategy Sweep
          </button>
          <button
            onClick={() => { setActiveTab("rank"); setErrorStr(null); setSuccessStr(null); setTerminalConsole(null); }}
            className={`flex items-center gap-2 px-3 py-1.5 text-xs font-semibold rounded-md transition-all ${
              activeTab === "rank"
                ? "bg-yellow-500/10 text-yellow-400 border border-yellow-500/20 shadow-md"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <TrendingUp className="w-3.5 h-3.5" />
            Rank Universe
          </button>
          <button
            onClick={() => { setActiveTab("auto_deploy"); setErrorStr(null); setSuccessStr(null); setTerminalConsole(null); }}
            className={`flex items-center gap-2 px-3 py-1.5 text-xs font-semibold rounded-md transition-all ${
              activeTab === "auto_deploy"
                ? "bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 shadow-md"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Sparkles className="w-3.5 h-3.5" />
            Auto-Deploy
          </button>
        </div>
      </div>

      {/* Main Tab Views */}
      {activeTab === "scan" && (
        /* MARKET SCANNER VIEW */
        <div className="space-y-8">
          <Card className="border-teal-500/10 bg-card/40 backdrop-blur">
            <CardHeader className="flex flex-row justify-between items-center border-b border-border/40 pb-4">
              <div>
                <CardTitle className="text-xl font-bold flex items-center gap-2">
                  <Cpu className="w-5 h-5 text-teal-400" />
                  Scanner Config
                </CardTitle>
                <CardDescription>Scan ALL strategies on one symbol, or ONE strategy across a market universe.</CardDescription>
              </div>
              <Button 
                onClick={handleRunScan} 
                disabled={loading} 
                className="bg-teal-500 hover:bg-teal-600 text-black font-bold flex items-center gap-2"
              >
                {loading ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    Sweeping...
                  </>
                ) : (
                  <>
                    <Play className="w-4 h-4 fill-current" />
                    Run Sweep Scan
                  </>
                )}
              </Button>
            </CardHeader>
            <CardContent className="space-y-6 pt-6">
              {/* Primary Params */}
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="space-y-2">
                  <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Strategy</label>
                  <Select value={scanParams.strategy} onValueChange={(val) => setScanParams({...scanParams, strategy: val || ""})}>
                    <SelectTrigger className="h-10 border-border/40 bg-muted/20">
                      <SelectValue placeholder="Select Strategy" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="ALL">ALL (Scan All Registered)</SelectItem>
                      {strategies.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Symbol</label>
                  <Select value={scanParams.symbol} onValueChange={(val) => setScanParams({...scanParams, symbol: val || ""})}>
                    <SelectTrigger className="h-10 border-border/40 bg-muted/20">
                      <SelectValue placeholder="Select Symbol" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="ALL">ALL (Rank & Scan Universe)</SelectItem>
                      {symbols.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Timeframe</label>
                  <Input 
                    value={scanParams.timeframe} 
                    onChange={(e) => setScanParams({...scanParams, timeframe: e.target.value})} 
                    className="h-10 border-border/40 bg-muted/20"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Top Universe Coins</label>
                  <Input 
                    type="number" 
                    value={scanParams.top} 
                    onChange={(e) => setScanParams({...scanParams, top: Number(e.target.value)})} 
                    className="h-10 border-border/40 bg-muted/20"
                  />
                </div>
              </div>

              {/* Backtest & Risk Specs */}
              <div>
                <h3 className="text-xs font-bold text-teal-400 uppercase tracking-wider mb-3">Backtest Specs & Risk Limits</h3>
                <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">Days</label>
                    <Input type="number" value={scanParams.days} onChange={(e) => setScanParams({...scanParams, days: Number(e.target.value)})} className="h-9 border-border/40" />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">Capital</label>
                    <Input type="number" value={scanParams.capital} onChange={(e) => setScanParams({...scanParams, capital: Number(e.target.value)})} className="h-9 border-border/40" />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">Leverage</label>
                    <Input type="number" step="0.1" value={scanParams.leverage} onChange={(e) => setScanParams({...scanParams, leverage: Number(e.target.value)})} className="h-9 border-border/40" />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">SL %</label>
                    <Input type="number" step="0.1" value={scanParams.sl_pct} onChange={(e) => setScanParams({...scanParams, sl_pct: Number(e.target.value)})} className="h-9 border-border/40" />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">TP %</label>
                    <Input type="number" step="0.1" value={scanParams.tp_pct} onChange={(e) => setScanParams({...scanParams, tp_pct: Number(e.target.value)})} className="h-9 border-border/40" />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">Trail %</label>
                    <Input type="number" step="0.1" value={scanParams.trail_pct} onChange={(e) => setScanParams({...scanParams, trail_pct: Number(e.target.value)})} className="h-9 border-border/40" />
                  </div>
                </div>
              </div>

              {/* Filtering Controls */}
              <div className="border-t border-border/40 pt-4 flex flex-wrap gap-6 items-center">
                <div className="flex items-center gap-2">
                  <Select value={scanParams.sort_by} onValueChange={(val) => setScanParams({...scanParams, sort_by: val || ""})}>
                    <SelectTrigger className="h-9 w-40 border-border/40 bg-muted/20">
                      <SelectValue placeholder="Sort Results By" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="return_pct">Sort by Return</SelectItem>
                      <SelectItem value="win_rate_pct">Sort by Win Rate</SelectItem>
                      <SelectItem value="profit_factor">Sort by Profit Factor</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="flex items-center gap-2">
                  <label className="text-xs text-muted-foreground">Min Trades</label>
                  <Input type="number" value={scanParams.min_trades} onChange={(e) => setScanParams({...scanParams, min_trades: Number(e.target.value)})} className="h-9 w-20" />
                </div>

                <label className="flex items-center gap-2 text-sm font-medium cursor-pointer">
                  <input 
                    type="checkbox" 
                    checked={scanParams.profitable_only} 
                    onChange={(e) => setScanParams({...scanParams, profitable_only: e.target.checked})} 
                    className="rounded border-border bg-muted h-4 w-4 accent-teal-500" 
                  />
                  Profitable Only
                </label>

                <label className="flex items-center gap-2 text-sm font-medium cursor-pointer">
                  <input 
                    type="checkbox" 
                    checked={scanParams.adx_filter} 
                    onChange={(e) => setScanParams({...scanParams, adx_filter: e.target.checked})} 
                    className="rounded border-border bg-muted h-4 w-4 accent-teal-500" 
                  />
                  ADX Regime Filter
                </label>

                <label className="flex items-center gap-2 text-sm font-medium cursor-pointer">
                  <input 
                    type="checkbox" 
                    checked={scanParams.live} 
                    onChange={(e) => setScanParams({...scanParams, live: e.target.checked})} 
                    className="rounded border-border bg-muted h-4 w-4 accent-teal-500" 
                  />
                  Use Live Market Data (Prod/Testnet)
                </label>

                <label className="flex items-center gap-2 text-sm font-medium cursor-pointer">
                  <input 
                    type="checkbox" 
                    checked={scanParams.save} 
                    onChange={(e) => setScanParams({...scanParams, save: e.target.checked})} 
                    className="rounded border-border bg-muted h-4 w-4 accent-teal-500" 
                  />
                  Save Runs to DB
                </label>
              </div>

              {/* ADX Sub-config */}
              {scanParams.adx_filter && (
                <div className="p-4 bg-muted/20 border border-teal-500/10 rounded-lg grid grid-cols-2 md:grid-cols-5 gap-4">
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">ADX Length</label>
                    <Input type="number" value={scanParams.adx_len} onChange={(e) => setScanParams({...scanParams, adx_len: Number(e.target.value)})} className="h-9" />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">ADX Trend Min</label>
                    <Input type="number" value={scanParams.adx_trend_min} onChange={(e) => setScanParams({...scanParams, adx_trend_min: Number(e.target.value)})} className="h-9" />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">ADX Range Max</label>
                    <Input type="number" value={scanParams.adx_range_max} onChange={(e) => setScanParams({...scanParams, adx_range_max: Number(e.target.value)})} className="h-9" />
                  </div>
                  <label className="flex items-center gap-2 text-xs font-semibold cursor-pointer pt-6">
                    <input type="checkbox" checked={scanParams.adx_exit_on_flip} onChange={(e) => setScanParams({...scanParams, adx_exit_on_flip: e.target.checked})} className="rounded accent-teal-500" />
                    Exit On ADX Flip
                  </label>
                  <label className="flex items-center gap-2 text-xs font-semibold cursor-pointer pt-6">
                    <input type="checkbox" checked={scanParams.adx_tighten_trail_on_flip} onChange={(e) => setScanParams({...scanParams, adx_tighten_trail_on_flip: e.target.checked})} className="rounded accent-teal-500" />
                    Tighten Trail On Flip
                  </label>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Results Table */}
          {scanResults.length > 0 && (
            <Card className="border-teal-500/15">
              <CardHeader className="flex flex-row justify-between items-center border-b border-border/40 pb-4">
                <div>
                  <CardTitle className="text-lg">Sweep Leaderboard</CardTitle>
                  <CardDescription>Ranked backtest combinations matching your filters.</CardDescription>
                </div>
                <Button onClick={handleDeployTop3} variant="secondary" className="border-teal-500/20 hover:bg-teal-500/10 hover:text-teal-400">
                  Deploy Top 3
                </Button>
              </CardHeader>
              <CardContent className="p-4">
                <SortableTable 
                  data={scanResults} 
                  columns={scanColumns} 
                  searchPlaceholder="Search scan results..."
                  defaultSort={{ key: "return_pct", dir: "desc" }}
                />
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {activeTab === "sweep" && (
        /* STRATEGY SWEEP VIEW */
        <div className="space-y-8">
          <Card className="border-emerald-500/10 bg-card/40 backdrop-blur">
            <CardHeader className="flex flex-row justify-between items-center border-b border-border/40 pb-4">
              <div>
                <CardTitle className="text-xl font-bold flex items-center gap-2">
                  <Sliders className="w-5 h-5 text-emerald-400" />
                  Strategy Sweep
                </CardTitle>
                <CardDescription>Sweep and test all 16+ registered python strategies on a single token to find the best fit.</CardDescription>
              </div>
              <Button 
                onClick={handleRunSweep} 
                disabled={loading} 
                className="bg-emerald-500 hover:bg-emerald-600 text-black font-bold flex items-center gap-2"
              >
                {loading ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    Sweeping token...
                  </>
                ) : (
                  <>
                    <Play className="w-4 h-4 fill-current" />
                    Run Token Sweep
                  </>
                )}
              </Button>
            </CardHeader>
            <CardContent className="space-y-6 pt-6">
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="space-y-2">
                  <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Symbol</label>
                  <Select value={sweepParams.symbol} onValueChange={(val) => setSweepParams({...sweepParams, symbol: val || "BTCUSD"})}>
                    <SelectTrigger className="h-10 border-border/40 bg-muted/20">
                      <SelectValue placeholder="Select Symbol" />
                    </SelectTrigger>
                    <SelectContent>
                      {symbols.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Timeframe</label>
                  <Input 
                    value={sweepParams.resolution} 
                    onChange={(e) => setSweepParams({...sweepParams, resolution: e.target.value})}
                    className="h-10"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Lookback Days</label>
                  <Input 
                    type="number" 
                    value={sweepParams.days} 
                    onChange={(e) => setSweepParams({...sweepParams, days: Number(e.target.value)})}
                    className="h-10"
                  />
                </div>
                <label className="flex items-center gap-2 text-sm font-medium cursor-pointer pt-8">
                  <input 
                    type="checkbox" 
                    checked={sweepParams.live} 
                    onChange={(e) => setSweepParams({...sweepParams, live: e.target.checked})} 
                    className="rounded border-border bg-muted h-4 w-4 accent-emerald-500" 
                  />
                  Live Feed Data
                </label>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 border-t border-border/40 pt-4">
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">Stop Loss % (0 to disable)</label>
                  <Input type="number" step="0.1" value={sweepParams.sl_pct} onChange={(e) => setSweepParams({...sweepParams, sl_pct: Number(e.target.value)})} />
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">Take Profit % (0 to disable)</label>
                  <Input type="number" step="0.1" value={sweepParams.tp_pct} onChange={(e) => setSweepParams({...sweepParams, tp_pct: Number(e.target.value)})} />
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">Trailing Stop % (0 to disable)</label>
                  <Input type="number" step="0.1" value={sweepParams.trail_pct} onChange={(e) => setSweepParams({...sweepParams, trail_pct: Number(e.target.value)})} />
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Strategy Sweep Results Table */}
          {sweepResults.length > 0 && (
            <Card className="border-emerald-500/15">
              <CardHeader>
                <CardTitle className="text-lg">Strategy Leaderboard ({sweepParams.symbol})</CardTitle>
                <CardDescription>All strategies backtested on historical candles, ranked by Net PnL.</CardDescription>
              </CardHeader>
              <CardContent className="p-4">
                <SortableTable 
                  data={sweepResults} 
                  columns={sweepColumns} 
                  searchPlaceholder="Search strategies..."
                  defaultSort={{ key: "pnl", dir: "desc" }}
                />
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {activeTab === "rank" && (
        /* RANK UNIVERSE VIEW */
        <div className="space-y-8">
          <Card className="border-yellow-500/10 bg-card/40 backdrop-blur">
            <CardHeader className="flex flex-row justify-between items-center border-b border-border/40 pb-4">
              <div>
                <CardTitle className="text-xl font-bold flex items-center gap-2">
                  <TrendingUp className="w-5 h-5 text-yellow-400" />
                  Rank Universe
                </CardTitle>
                <CardDescription>Fetch, sort, and rank top assets by trading turnover, volatility, and volume indicators.</CardDescription>
              </div>
              <Button 
                onClick={handleRunRankUniverse} 
                disabled={loading} 
                className="bg-yellow-500 hover:bg-yellow-600 text-black font-bold flex items-center gap-2"
              >
                {loading ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    Ranking coins...
                  </>
                ) : (
                  <>
                    <Play className="w-4 h-4 fill-current" />
                    Rank Market Universe
                  </>
                )}
              </Button>
            </CardHeader>
            <CardContent className="space-y-6 pt-6">
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="space-y-2">
                  <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Top N Coins to List</label>
                  <Input 
                    type="number" 
                    value={rankParams.top} 
                    onChange={(e) => setRankParams({...rankParams, top: Number(e.target.value)})}
                    className="h-10"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Evaluation Timeframe</label>
                  <Input 
                    value={rankParams.resolution} 
                    onChange={(e) => setRankParams({...rankParams, resolution: e.target.value})}
                    className="h-10"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Evaluation Lookback Days</label>
                  <Input 
                    type="number" 
                    value={rankParams.days} 
                    onChange={(e) => setRankParams({...rankParams, days: Number(e.target.value)})}
                    className="h-10"
                  />
                </div>
                <label className="flex items-center gap-2 text-sm font-medium cursor-pointer pt-8">
                  <input 
                    type="checkbox" 
                    checked={rankParams.live} 
                    onChange={(e) => setRankParams({...rankParams, live: e.target.checked})} 
                    className="rounded border-border bg-muted h-4 w-4 accent-yellow-500" 
                  />
                  Live Feed Data
                </label>
              </div>
            </CardContent>
          </Card>

          {/* Rank Universe Results Table */}
          {rankResults.length > 0 && (
            <Card className="border-yellow-500/15">
              <CardHeader>
                <CardTitle className="text-lg">Ranked Universe Assets</CardTitle>
                <CardDescription>Top turnover products with market structure analysis metrics.</CardDescription>
              </CardHeader>
              <CardContent className="p-4">
                <SortableTable 
                  data={rankResults} 
                  columns={rankColumns} 
                  searchPlaceholder="Search ranked assets..."
                  defaultSort={{ key: "rank", dir: "asc" }}
                />
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {activeTab === "auto_deploy" && (
        /* AUTO DEPLOY VIEW */
        <div className="space-y-8">
          <Card className="border-cyan-500/10 bg-card/40 backdrop-blur">
            <CardHeader className="flex flex-row justify-between items-center border-b border-border/40 pb-4">
              <div>
                <CardTitle className="text-xl font-bold flex items-center gap-2">
                  <Sparkles className="w-5 h-5 text-cyan-400" />
                  Auto-Deploy Orchestrator
                </CardTitle>
                <CardDescription>
                  Smart CLI Orchestrator: Ranks universe, sweeps top coins, and deploys the best performing strategy on each.
                </CardDescription>
              </div>
              <Button 
                onClick={handleRunAutoDeploy} 
                disabled={loading} 
                className="bg-cyan-500 hover:bg-cyan-600 text-black font-bold flex items-center gap-2"
              >
                {loading ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    Orchestrating...
                  </>
                ) : (
                  <>
                    <Play className="w-4 h-4 fill-current" />
                    Run Auto-Deploy Engine
                  </>
                )}
              </Button>
            </CardHeader>
            <CardContent className="space-y-6 pt-6">
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="space-y-2">
                  <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Deploy Venue</label>
                  <Select value={autoDeployParams.venue} onValueChange={(val) => setAutoDeployParams({...autoDeployParams, venue: val || ""})}>
                    <SelectTrigger className="h-10 border-border/40 bg-muted/20">
                      <SelectValue placeholder="Select Venue" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="paper">Paper Trading (Simulated)</SelectItem>
                      <SelectItem value="testnet">Testnet Live Execution</SelectItem>
                      <SelectItem value="live">Production (REAL MONEY)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Top Coins Rank Limit</label>
                  <Input 
                    type="number" 
                    value={autoDeployParams.top} 
                    onChange={(e) => setAutoDeployParams({...autoDeployParams, top: Number(e.target.value)})}
                    className="h-10 border-border/40 bg-muted/20"
                  />
                </div>

                <div className="space-y-2">
                  <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Lookback Sweep Days</label>
                  <Input 
                    type="number" 
                    value={autoDeployParams.days} 
                    onChange={(e) => setAutoDeployParams({...autoDeployParams, days: Number(e.target.value)})}
                    className="h-10 border-border/40 bg-muted/20"
                  />
                </div>

                <div className="space-y-2">
                  <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Resolution Timeframe</label>
                  <Input 
                    value={autoDeployParams.resolution} 
                    onChange={(e) => setAutoDeployParams({...autoDeployParams, resolution: e.target.value})}
                    className="h-10 border-border/40 bg-muted/20"
                  />
                </div>
              </div>

              {/* Advanced specs */}
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4 border-t border-border/40 pt-4">
                <div className="space-y-2">
                  <label className="text-xs text-muted-foreground">Lot / Order Size</label>
                  <Input 
                    type="number" 
                    step="0.1" 
                    value={autoDeployParams.size} 
                    onChange={(e) => setAutoDeployParams({...autoDeployParams, size: Number(e.target.value)})}
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-muted-foreground">Stop Loss %</label>
                  <Input 
                    type="number" 
                    step="0.1" 
                    value={autoDeployParams.sl_pct} 
                    onChange={(e) => setAutoDeployParams({...autoDeployParams, sl_pct: Number(e.target.value)})}
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-muted-foreground">Take Profit %</label>
                  <Input 
                    type="number" 
                    step="0.1" 
                    value={autoDeployParams.tp_pct} 
                    onChange={(e) => setAutoDeployParams({...autoDeployParams, tp_pct: Number(e.target.value)})}
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-muted-foreground">Trailing Stop %</label>
                  <Input 
                    type="number" 
                    step="0.1" 
                    value={autoDeployParams.trail_pct} 
                    onChange={(e) => setAutoDeployParams({...autoDeployParams, trail_pct: Number(e.target.value)})}
                  />
                </div>
              </div>

              {/* Force Specific Symbol filter */}
              <div className="border-t border-border/40 pt-4 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
                <div className="space-y-2 w-full md:w-1/3">
                  <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Target Symbol (Optional)</label>
                  <Input 
                    placeholder="e.g. BTCUSD (skips ranking universe)" 
                    value={autoDeployParams.symbol} 
                    onChange={(e) => setAutoDeployParams({...autoDeployParams, symbol: e.target.value.toUpperCase()})}
                    className="h-10"
                  />
                </div>

                <label className="flex items-center gap-2 text-sm font-medium cursor-pointer pt-6">
                  <input 
                    type="checkbox" 
                    checked={autoDeployParams.live} 
                    onChange={(e) => setAutoDeployParams({...autoDeployParams, live: e.target.checked})} 
                    className="rounded border-border bg-muted h-4 w-4 accent-cyan-500" 
                  />
                  Live Feed Data Sync
                </label>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Success Banner */}
      {successStr && (
        <div className="p-4 bg-emerald-500/10 border border-emerald-500/20 rounded-lg flex items-center gap-3">
          <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
          <p className="text-sm font-semibold text-emerald-300">{successStr}</p>
        </div>
      )}

      {/* Error Message Box */}
      {errorStr && (
        <Card className="border-red-500/20 bg-red-950/10">
          <CardHeader>
            <CardTitle className="text-red-400 text-sm font-semibold uppercase tracking-wider">Execution Exception</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="p-4 bg-black/40 text-red-300 rounded border border-red-500/10 font-mono text-xs overflow-x-auto whitespace-pre-wrap">
              {errorStr}
            </pre>
          </CardContent>
        </Card>
      )}

      {/* Live Terminal Output Console */}
      {(loading || terminalConsole) && (
        <Card className="border-cyan-500/20 bg-black/85 shadow-2xl">
          <CardHeader className="border-b border-border/20 py-3 flex flex-row items-center justify-between">
            <div className="flex items-center gap-2">
              <Terminal className="w-4 h-4 text-cyan-400" />
              <span className="text-xs font-bold font-mono text-muted-foreground uppercase tracking-wider">Live System Terminal</span>
            </div>
            {loading && <Badge variant="outline" className="text-cyan-400 border-cyan-400 animate-pulse">RUNNING</Badge>}
          </CardHeader>
          <CardContent className="p-4">
            {loading && !terminalConsole ? (
              <div className="py-16 flex flex-col items-center justify-center space-y-4">
                <RefreshCw className="w-8 h-8 text-cyan-400 animate-spin" />
                <p className="text-sm text-cyan-300 font-mono">Executing daemon task inside Delta CLI subprocess...</p>
                <p className="text-xs text-muted-foreground font-mono">Running index calculations, loading historical candles, and building telemetry data...</p>
              </div>
            ) : (
              <pre className="font-mono text-xs text-teal-300 overflow-x-auto whitespace-pre-wrap leading-relaxed max-h-[500px]">
                {terminalConsole}
              </pre>
            )}
          </CardContent>
        </Card>
      )}

      {/* Recommendation Card */}
      <Card className="border-border/30 bg-muted/10">
        <CardHeader className="py-4">
          <CardTitle className="text-sm font-bold flex items-center gap-2">
            <Target className="w-4 h-4 text-teal-400" />
            Looking for Custom Hunters & Snipers?
          </CardTitle>
        </CardHeader>
        <CardContent className="text-xs text-muted-foreground space-y-2 pb-4">
          <p>
            You can run and monitor more advanced target hunter scripts (e.g. SMC Liquidity Hunters, Price Action engulfing scanners, yield arbitrages) in the Background Tasks menu.
          </p>
          <div className="flex items-center gap-1.5 text-teal-400 font-semibold hover:text-teal-300">
            <LinkIcon className="w-3.5 h-3.5" />
            <Link href="/scheduler">Go to Scheduler & Tasks Menu</Link>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
