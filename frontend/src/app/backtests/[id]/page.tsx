"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { fetchRunSummary, fetchRunEquity, fetchRunTrades } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ArrowLeft, ArrowUpRight, ArrowDownRight } from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

import { useRouter } from "next/navigation";

export default function BacktestDetailPage() {
  const router = useRouter();
  const params = useParams();
  const id = params.id as string;
  const [data, setData] = useState<any>(null);
  const [equity, setEquity] = useState<any[]>([]);
  const [trades, setTrades] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      setLoading(true);
      const [summaryRes, equityRes, tradesRes] = await Promise.all([
        fetchRunSummary(id),
        fetchRunEquity(id),
        fetchRunTrades(id),
      ]);
      setData(summaryRes);
      if (equityRes) setEquity(equityRes);
      if (tradesRes) setTrades(tradesRes);
      setLoading(false);
    }
    load();
  }, [id]);

  const handleDeploy = () => {
    if (!data?.run) return;
    localStorage.setItem("delta_deploy_params", JSON.stringify({
      strategy: data.run.strategy,
      symbol: data.run.symbol,
      timeframe: data.run.resolution,
      params_json: data.run.params_json || "{}",
      sl_pct: data.run.sl_pct || 0,
      tp_pct: data.run.tp_pct || 0,
      trail_pct: data.run.trail_pct || 0
    }));
    router.push("/deployments/create?from_backtest=true");
  };

  // Compute Advanced Metrics
  const wins = trades.filter(t => t.pnl > 0);
  const losses = trades.filter(t => t.pnl < 0);
  const grossProfit = wins.reduce((sum, t) => sum + t.pnl, 0);
  const grossLoss = Math.abs(losses.reduce((sum, t) => sum + t.pnl, 0));
  const avgWin = wins.length > 0 ? grossProfit / wins.length : 0;
  const avgLoss = losses.length > 0 ? grossLoss / losses.length : 0;
  const bestTrade = trades.length > 0 ? Math.max(...trades.map(t => t.pnl)) : 0;
  const worstTrade = trades.length > 0 ? Math.min(...trades.map(t => t.pnl)) : 0;
  const expectancy = trades.length > 0 ? ((wins.length / trades.length) * avgWin) - ((losses.length / trades.length) * avgLoss) : 0;
  const sharpe = data?.metrics?.sharpe ?? (trades.length > 0 ? ((grossProfit - grossLoss) / trades.length) / (Math.abs(worstTrade) || 1) : 0); // basic fallback

  let maxDrawdownPct = data?.run?.max_dd_pct;
  if (maxDrawdownPct == null && equity.length > 0) {
    let peak = equity[0].equity;
    let maxDd = 0;
    for (const pt of equity) {
      if (pt.equity > peak) peak = pt.equity;
      const dd = (peak - pt.equity) / peak;
      if (dd > maxDd) maxDd = dd;
    }
    maxDrawdownPct = maxDd * 100;
  }



  if (loading) return <div className="p-8">Loading...</div>;
  if (!data) return <div className="p-8">Run not found.</div>;

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-4">
          <Link href="/backtests">
            <Button variant="ghost" size="icon" className="hover:bg-zinc-800">
              <ArrowLeft className="h-5 w-5" />
            </Button>
          </Link>
          <div>
            <h1 className="text-4xl font-bold tracking-tight">Run: {id}</h1>
            <p className="text-muted-foreground mt-2">Strategy: {data.run?.strategy} | Symbol: {data.run?.symbol}</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <Badge variant={data.run?.return_pct >= 0 ? "default" : "destructive"} className="text-lg px-4 py-1">
            {data.run?.return_pct?.toFixed(2)}% Return
          </Badge>
          <Link href={`/backtests/${id}/edit`}>
            <Button variant="secondary" className="font-semibold">
              Edit & Rerun
            </Button>
          </Link>
          <Button onClick={handleDeploy} className="bg-primary text-primary-foreground font-semibold">
            Deploy Strategy
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
        <Card className="bg-zinc-900 border-zinc-800">
          <CardHeader className="pb-2">
            <CardDescription className="text-zinc-400">Total Trades</CardDescription>
            <CardTitle className="text-2xl">{trades.length}</CardTitle>
          </CardHeader>
        </Card>
        <Card className="bg-zinc-900 border-zinc-800">
          <CardHeader className="pb-2">
            <CardDescription className="text-zinc-400">Win Rate</CardDescription>
            <CardTitle className="text-2xl">
              {trades.length > 0 ? ((wins.length / trades.length) * 100).toFixed(2) : "0.00"}%
            </CardTitle>
          </CardHeader>
        </Card>
        <Card className="bg-zinc-900 border-zinc-800">
          <CardHeader className="pb-2">
            <CardDescription className="text-zinc-400">Profit Factor</CardDescription>
            <CardTitle className="text-2xl">
              {grossLoss > 0 ? (grossProfit / grossLoss).toFixed(2) : (grossProfit > 0 ? "∞" : "0.00")}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card className="bg-zinc-900 border-zinc-800">
          <CardHeader className="pb-2">
            <CardDescription className="text-zinc-400">Max Drawdown</CardDescription>
            <CardTitle className="text-2xl text-purple-400">
              {maxDrawdownPct != null ? maxDrawdownPct.toFixed(2) : "0.00"}%
            </CardTitle>
          </CardHeader>
        </Card>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
        <Card className="bg-zinc-900 border-zinc-800">
          <CardHeader className="pb-2">
            <CardDescription className="text-zinc-400">Best Trade</CardDescription>
            <CardTitle className="text-2xl text-green-400">${bestTrade.toFixed(2)}</CardTitle>
          </CardHeader>
        </Card>
        <Card className="bg-zinc-900 border-zinc-800">
          <CardHeader className="pb-2">
            <CardDescription className="text-zinc-400">Worst Trade</CardDescription>
            <CardTitle className="text-2xl text-purple-400">${worstTrade.toFixed(2)}</CardTitle>
          </CardHeader>
        </Card>
        <Card className="bg-zinc-900 border-zinc-800">
          <CardHeader className="pb-2">
            <CardDescription className="text-zinc-400">Avg Trade Expectancy</CardDescription>
            <CardTitle className={`text-2xl ${expectancy >= 0 ? 'text-green-400' : 'text-purple-400'}`}>${expectancy.toFixed(2)}</CardTitle>
          </CardHeader>
        </Card>
        <Card className="bg-zinc-900 border-zinc-800">
          <CardHeader className="pb-2">
            <CardDescription className="text-zinc-400">Sharpe Ratio</CardDescription>
            <CardTitle className="text-2xl text-blue-400">{sharpe.toFixed(2)}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      <Card className="bg-black border-zinc-800 shadow-xl overflow-hidden">
        <CardHeader className="border-b border-zinc-800/50 bg-zinc-900/50">
          <CardTitle>Equity Curve</CardTitle>
          <CardDescription>Interactive portfolio value over time</CardDescription>
        </CardHeader>
        <CardContent className="p-6">
          <div className="h-[400px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={equity}>
                <CartesianGrid strokeDasharray="3 3" stroke="#27272a" vertical={false} />
                <XAxis 
                  dataKey="ts" 
                  stroke="#52525b" 
                  fontSize={12}
                  tickFormatter={(val) => new Date(val).toLocaleDateString()}
                  minTickGap={50}
                />
                <YAxis 
                  stroke="#52525b" 
                  fontSize={12}
                  domain={['auto', 'auto']}
                  tickFormatter={(val) => `$${val.toLocaleString(undefined, {maximumFractionDigits: 0})}`}
                />
                <Tooltip
                  contentStyle={{ backgroundColor: '#18181b', border: '1px solid #27272a', borderRadius: '8px' }}
                  labelFormatter={(val: any) => new Date(val).toLocaleString()}
                  formatter={(value: any) => [`$${value.toFixed(2)}`, 'Equity']}
                />
                <Line 
                  type="monotone" 
                  dataKey="equity" 
                  stroke="#4ade80" 
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 6, fill: "#4ade80", stroke: "#18181b", strokeWidth: 2 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <Card className="bg-black border-zinc-800 shadow-xl overflow-hidden">
        <CardHeader className="border-b border-zinc-800/50 bg-zinc-900/50">
          <CardTitle>Trade History</CardTitle>
          <CardDescription>Detailed log of all executions in this run</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {trades.length === 0 ? (
            <div className="p-8 text-center text-zinc-500">No trades executed in this backtest.</div>
          ) : (
            <div className="max-h-[500px] overflow-y-auto">
              <Table>
                <TableHeader className="bg-zinc-900/80 sticky top-0 backdrop-blur-sm">
                  <TableRow className="border-zinc-800 hover:bg-transparent">
                    <TableHead className="text-zinc-400">Entry Time</TableHead>
                    <TableHead className="text-zinc-400">Side</TableHead>
                    <TableHead className="text-zinc-400 text-right">Qty</TableHead>
                    <TableHead className="text-zinc-400 text-right">Entry Price</TableHead>
                    <TableHead className="text-zinc-400 text-right">Exit Price</TableHead>
                    <TableHead className="text-zinc-400 text-right">PnL</TableHead>
                    <TableHead className="text-zinc-400 text-right">Return %</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {trades.map((t, i) => {
                    const isWin = t.pnl > 0;
                    return (
                      <TableRow key={i} className="border-b border-zinc-800/50 hover:bg-zinc-900/50">
                        <TableCell className="font-mono text-xs text-zinc-400">
                          {new Date(t.entry_ts).toLocaleString()}
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className={t.side === 'LONG' ? 'text-green-400 border-green-500/30' : 'text-purple-400 border-purple-500/30'}>
                            {t.side}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right font-mono">{t.qty}</TableCell>
                        <TableCell className="text-right font-mono">${t.entry_price?.toFixed(2)}</TableCell>
                        <TableCell className="text-right font-mono">${t.exit_price?.toFixed(2)}</TableCell>
                        <TableCell className={`text-right font-mono font-medium flex items-center justify-end gap-1 ${isWin ? 'text-green-400' : 'text-purple-400'}`}>
                          {isWin ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
                          ${Math.abs(t.pnl).toFixed(2)}
                        </TableCell>
                        <TableCell className={`text-right font-mono ${isWin ? 'text-green-400' : 'text-purple-400'}`}>
                          {t.return_pct?.toFixed(2)}%
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
