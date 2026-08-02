"use client";

import { useState, useEffect } from "react";
import { fetchPnlSummary, fetchPnlStrategy } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, BarChart, Bar, CartesianGrid } from "recharts";

export default function DashboardPage() {
  const [summary, setSummary] = useState<any>(null);
  const [dailyPnl, setDailyPnl] = useState<any[]>([]);
  const [strategyPnl, setStrategyPnl] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadData() {
      setLoading(true);
      const sumRes = await fetchPnlSummary();
      if (sumRes && !sumRes.error) {
        setSummary(sumRes.summary);
        // Reverse daily data to display chronologically (left to right)
        if (sumRes.daily) {
          setDailyPnl([...sumRes.daily].reverse());
        }
      }
      const stratRes = await fetchPnlStrategy();
      if (stratRes && !stratRes.error) {
        setStrategyPnl(stratRes);
      }
      setLoading(false);
    }
    loadData();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-lg font-semibold animate-pulse">Loading Advanced PnL Dashboard...</div>
      </div>
    );
  }

  // Pre-calculate cumulative equity curve if we only have daily_pnl
  let currentEquity = summary?.starting_capital || 10000;
  const chartData = dailyPnl.map((d) => {
    currentEquity += d.pnl;
    return {
      date: d.date,
      pnl: d.pnl,
      equity: currentEquity,
    };
  });

  const winRate = summary ? (summary.winning_trades / summary.total_trades) * 100 : 0;
  const netPnlColor = summary?.net_pnl >= 0 ? "text-green-500" : "text-red-500";

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      <div>
        <h1 className="text-4xl font-bold tracking-tight">Advanced PnL Dashboard</h1>
        <p className="text-muted-foreground mt-2">Comprehensive performance and portfolio analytics.</p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-4 gap-6">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Starting Capital</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">${summary?.starting_capital?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Net PnL</CardTitle>
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold ${netPnlColor}`}>
              {summary?.net_pnl >= 0 ? "+" : ""}${summary?.net_pnl?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Win Rate</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{summary?.win_rate_pct?.toFixed(1)}%</div>
            <p className="text-xs text-muted-foreground mt-1">
              {summary?.winning_trades} W / {summary?.losing_trades} L
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Sharpe / Max DD</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{summary?.avg_sharpe?.toFixed(2)}</div>
            <p className="text-xs text-red-500 mt-1">Max DD: {summary?.avg_max_dd_pct?.toFixed(2)}%</p>
          </CardContent>
        </Card>
      </div>

      {/* Charts */}
      <div className="grid grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Cumulative Equity Curve</CardTitle>
            <CardDescription>Visual growth of account capital over time.</CardDescription>
          </CardHeader>
          <CardContent className="h-96">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorEquity" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <XAxis dataKey="date" stroke="#888888" fontSize={12} tickLine={false} axisLine={false} />
                <YAxis stroke="#888888" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(v) => `$${v}`} />
                <Tooltip formatter={(value: any) => [`$${parseFloat(value).toFixed(2)}`, "Equity"]} />
                <Area type="monotone" dataKey="equity" stroke="#10b981" fillOpacity={1} fill="url(#colorEquity)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Daily PnL</CardTitle>
            <CardDescription>Daily realized profit and loss volatility.</CardDescription>
          </CardHeader>
          <CardContent className="h-96">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} opacity={0.1} />
                <XAxis dataKey="date" stroke="#888888" fontSize={12} tickLine={false} axisLine={false} />
                <YAxis stroke="#888888" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(v) => `$${v}`} />
                <Tooltip formatter={(value: any) => [`$${parseFloat(value).toFixed(2)}`, "Daily PnL"]} />
                <Bar dataKey="pnl" fill="#3b82f6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* Breakdown per Strategy */}
      <Card>
        <CardHeader>
          <CardTitle>Performance Breakdown per Strategy</CardTitle>
          <CardDescription>Granular metric analysis for each deployed strategy.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Strategy</TableHead>
                <TableHead>Runs</TableHead>
                <TableHead>Trades</TableHead>
                <TableHead>Win Rate %</TableHead>
                <TableHead>Net PnL ($)</TableHead>
                <TableHead>Sharpe</TableHead>
                <TableHead>Max DD %</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {strategyPnl.map((r, i) => (
                <TableRow key={i}>
                  <TableCell className="font-semibold">{r.strategy}</TableCell>
                  <TableCell>{r.runs}</TableCell>
                  <TableCell>{r.trades}</TableCell>
                  <TableCell>{r.win_rate_pct?.toFixed(1)}%</TableCell>
                  <TableCell className={r.pnl >= 0 ? "text-green-500" : "text-red-500"}>
                    ${r.pnl?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </TableCell>
                  <TableCell>{r.sharpe?.toFixed(2)}</TableCell>
                  <TableCell className="text-red-400">{r.max_dd_pct?.toFixed(2)}%</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
