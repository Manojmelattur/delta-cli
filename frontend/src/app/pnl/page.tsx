"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { fetchPnlSummary, fetchPnlStrategy, fetchSymbols } from "@/lib/api";
import { 
  AreaChart, Area, BarChart, Bar, LineChart, Line, XAxis, YAxis, 
  CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine 
} from "recharts";
import { 
  TrendingUp, TrendingDown, Scale, DollarSign, Activity, 
  Award, Percent, RefreshCw, BarChart2, ShieldAlert 
} from "lucide-react";

export default function PnlPage() {
  const [summaryData, setSummaryData] = useState<any>(null);
  const [strategyData, setStrategyData] = useState<any[]>([]);
  const [symbols, setSymbols] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  // Filter States
  const [days, setDays] = useState<number>(30);
  const [venue, setVenue] = useState<string>("all");
  const [strategy, setStrategy] = useState<string>("");
  const [symbol, setSymbol] = useState<string>("all");

  async function loadData() {
    setLoading(true);
    const filters = {
      days,
      venue: venue === "all" ? undefined : venue,
      strategy: strategy === "" ? undefined : strategy,
      symbol: symbol === "all" ? undefined : symbol,
    };

    try {
      const [sumRes, stratRes, symRes] = await Promise.all([
        fetchPnlSummary(filters),
        fetchPnlStrategy({ days, venue: filters.venue, symbol: filters.symbol }),
        fetchSymbols(),
      ]);

      setSummaryData(sumRes);
      setStrategyData(Array.isArray(stratRes) ? stratRes : []);
      setSymbols(Array.isArray(symRes) ? symRes : []);
    } catch (e) {
      console.error("Failed to load PnL details:", e);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, [days, venue, strategy, symbol]);

  // Calculations for display
  const totalPnL = summaryData?.total_realized_pnl ?? 0;
  const totalFees = summaryData?.total_fees ?? 0;
  const netPnL = totalPnL - totalFees;
  const winRate = summaryData?.win_rate_pct ?? 0;
  const totalTrades = summaryData?.total_trades ?? 0;
  const wins = summaryData?.wins ?? 0;
  const losses = summaryData?.losses ?? 0;
  const avgWin = summaryData?.avg_win ?? 0;
  const avgLoss = summaryData?.avg_loss ?? 0;
  const profitFactor = summaryData?.profit_factor ?? 0;

  // Format chart data
  const equityData = summaryData?.equity_curve?.map((val: number, idx: number) => ({
    index: idx,
    value: val
  })) || [];

  const dailyData = summaryData?.daily?.map((d: any) => ({
    date: d.date,
    pnl: d.pnl - d.fees,
    rawPnL: d.pnl,
    fees: d.fees,
    trades: d.trades
  })).reverse() || [];

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8 animate-in fade-in duration-300">
      
      {/* HEADER */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h1 className="text-4xl font-bold tracking-tight">PnL Analytics</h1>
          <p className="text-muted-foreground mt-1">Advanced performance analysis, strategy attribution, and metric tracking.</p>
        </div>
        <Button onClick={loadData} variant="outline" className="flex items-center gap-2" disabled={loading}>
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Refresh
        </Button>
      </div>

      {/* FILTER BAR */}
      <Card className="border border-border/80 shadow-sm">
        <CardContent className="p-4 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 gap-4">
          
          <div className="space-y-1">
            <span className="text-xs font-semibold text-muted-foreground uppercase">Lookback Period</span>
            <Select value={days.toString()} onValueChange={v => { if (v) setDays(parseInt(v)); }}>
              <SelectTrigger className="h-10">
                <SelectValue placeholder="Period" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="7">Last 7 Days</SelectItem>
                <SelectItem value="30">Last 30 Days</SelectItem>
                <SelectItem value="90">Last 90 Days</SelectItem>
                <SelectItem value="365">Last 365 Days</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <span className="text-xs font-semibold text-muted-foreground uppercase">Venue</span>
            <Select value={venue} onValueChange={v => { if (v) setVenue(v); }}>
              <SelectTrigger className="h-10">
                <SelectValue placeholder="Venue" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Venues</SelectItem>
                <SelectItem value="paper">Paper</SelectItem>
                <SelectItem value="live">Live</SelectItem>
                <SelectItem value="testnet">Testnet</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <span className="text-xs font-semibold text-muted-foreground uppercase">Symbol</span>
            <Select value={symbol} onValueChange={v => { if (v) setSymbol(v); }}>
              <SelectTrigger className="h-10">
                <SelectValue placeholder="Symbol" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Symbols</SelectItem>
                {symbols.map(sym => (
                  <SelectItem key={sym} value={sym}>{sym}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1 md:col-span-2">
            <span className="text-xs font-semibold text-muted-foreground uppercase">Strategy Filter</span>
            <Input 
              type="text" 
              placeholder="Search strategy..." 
              value={strategy} 
              onChange={e => setStrategy(e.target.value)} 
              className="h-10"
            />
          </div>

        </CardContent>
      </Card>

      {/* NO DATA STATE */}
      {!summaryData && !loading && (
        <Card>
          <CardContent className="p-12 text-center text-muted-foreground flex flex-col items-center justify-center gap-3">
            <ShieldAlert className="h-12 w-12 text-muted-foreground/60" />
            <p className="text-lg font-medium">No matching PnL data found.</p>
            <p className="text-sm">Try relaxing your search parameters or run a new backtest.</p>
          </CardContent>
        </Card>
      )}

      {summaryData && (
        <div className="space-y-8">
          
          {/* ADVANCED PERFORMANCE CARDS */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
            
            {/* NET PNL */}
            <Card className="border border-border/80 shadow-md">
              <CardContent className="p-6 flex items-center justify-between">
                <div className="space-y-1">
                  <p className="text-sm text-muted-foreground font-medium uppercase tracking-wider">Net PnL</p>
                  <p className={`text-3xl font-extrabold tracking-tight ${netPnL >= 0 ? "text-green-500" : "text-red-500"}`}>
                    ${netPnL.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </p>
                  <p className="text-xs text-muted-foreground flex items-center gap-1 pt-1">
                    Gross: <span className="font-semibold text-foreground">${totalPnL.toFixed(1)}</span> | Fees: <span className="font-semibold text-foreground">${totalFees.toFixed(1)}</span>
                  </p>
                </div>
                <div className={`p-3.5 rounded-full ${netPnL >= 0 ? "bg-green-500/10 text-green-500" : "bg-red-500/10 text-red-500"}`}>
                  {netPnL >= 0 ? <TrendingUp className="h-6 w-6" /> : <TrendingDown className="h-6 w-6" />}
                </div>
              </CardContent>
            </Card>

            {/* WIN RATE */}
            <Card className="border border-border/80 shadow-md">
              <CardContent className="p-6 flex items-center justify-between">
                <div className="space-y-1">
                  <p className="text-sm text-muted-foreground font-medium uppercase tracking-wider">Win Rate</p>
                  <p className="text-3xl font-extrabold tracking-tight text-primary">
                    {winRate.toFixed(1)}%
                  </p>
                  <p className="text-xs text-muted-foreground pt-1">
                    Wins: <span className="font-semibold text-foreground">{wins}</span> | Losses: <span className="font-semibold text-foreground">{losses}</span> | Total: <span className="font-semibold text-foreground">{totalTrades}</span>
                  </p>
                </div>
                <div className="p-3.5 bg-primary/10 text-primary rounded-full">
                  <Percent className="h-6 w-6" />
                </div>
              </CardContent>
            </Card>

            {/* PROFIT FACTOR */}
            <Card className="border border-border/80 shadow-md">
              <CardContent className="p-6 flex items-center justify-between">
                <div className="space-y-1">
                  <p className="text-sm text-muted-foreground font-medium uppercase tracking-wider">Profit Factor</p>
                  <p className={`text-3xl font-extrabold tracking-tight ${profitFactor >= 1.5 ? "text-green-500" : profitFactor >= 1.0 ? "text-yellow-500" : "text-red-500"}`}>
                    {profitFactor.toFixed(2)}
                  </p>
                  <p className="text-xs text-muted-foreground pt-1">
                    Ratio of gross profits to gross losses
                  </p>
                </div>
                <div className="p-3.5 bg-zinc-500/10 text-zinc-400 rounded-full">
                  <Scale className="h-6 w-6" />
                </div>
              </CardContent>
            </Card>

            {/* AVG WIN / LOSS */}
            <Card className="border border-border/80 shadow-md">
              <CardContent className="p-6 flex items-center justify-between">
                <div className="space-y-1">
                  <p className="text-sm text-muted-foreground font-medium uppercase tracking-wider">Avg Win / Loss</p>
                  <p className="text-3xl font-extrabold tracking-tight text-foreground">
                    ${avgWin.toFixed(1)} / ${avgLoss.toFixed(1)}
                  </p>
                  <p className="text-xs text-muted-foreground pt-1">
                    Risk Reward Ratio: <span className="font-semibold text-primary">{(avgLoss !== 0 ? Math.abs(avgWin / avgLoss) : 0).toFixed(2)}</span>
                  </p>
                </div>
                <div className="p-3.5 bg-amber-500/10 text-amber-500 rounded-full">
                  <Award className="h-6 w-6" />
                </div>
              </CardContent>
            </Card>

          </div>

          {/* CHARTS CONTAINER */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            
            {/* EQUITY CURVE */}
            <Card className="border border-border/80 shadow-md">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Activity className="h-5 w-5 text-primary" /> Cumulative Portfolio Equity
                </CardTitle>
                <CardDescription>Visual growth of capital over all executions in this lookback.</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="h-80 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={equityData}>
                      <defs>
                        <linearGradient id="colorEquity" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#4ade80" stopOpacity={0.25}/>
                          <stop offset="95%" stopColor="#4ade80" stopOpacity={0}/>
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                      <XAxis dataKey="index" stroke="#52525b" fontSize={11} tickLine={false} />
                      <YAxis stroke="#52525b" fontSize={11} domain={['auto', 'auto']} tickLine={false} tickFormatter={v => `$${v}`} />
                      <Tooltip 
                        contentStyle={{ backgroundColor: '#18181b', border: '1px solid #27272a', borderRadius: '8px' }}
                        labelFormatter={(val) => `Execution #${val}`}
                        formatter={(value: any) => [`$${parseFloat(value).toFixed(2)}`, 'Equity']}
                      />
                      <Area type="monotone" dataKey="value" stroke="#4ade80" strokeWidth={2} fillOpacity={1} fill="url(#colorEquity)" />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>

            {/* DAILY NET PNL */}
            <Card className="border border-border/80 shadow-md">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <BarChart2 className="h-5 w-5 text-primary" /> Daily Realized Net Profit
                </CardTitle>
                <CardDescription>Realized profits less trading commission fees per day.</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="h-80 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={dailyData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                      <XAxis dataKey="date" stroke="#52525b" fontSize={10} tickLine={false} />
                      <YAxis stroke="#52525b" fontSize={11} tickLine={false} tickFormatter={v => `$${v}`} />
                      <Tooltip 
                        contentStyle={{ backgroundColor: '#18181b', border: '1px solid #27272a', borderRadius: '8px' }}
                        formatter={(value: any, name: any, props: any) => {
                          if (name === "pnl") return [`$${parseFloat(value).toFixed(2)}`, 'Net PnL'];
                          return [`$${value}`, name];
                        }}
                      />
                      <ReferenceLine y={0} stroke="#52525b" />
                      <Bar dataKey="pnl">
                        {dailyData.map((entry: any, index: number) => (
                          <rect
                            key={`rect-${index}`}
                            fill={entry.pnl >= 0 ? "#22c55e" : "#ef4444"}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>

          </div>

          {/* LEADERBOARD TABLE */}
          <Card className="border border-border/80 shadow-md">
            <CardHeader>
              <CardTitle>Strategy Performance Leaderboard</CardTitle>
              <CardDescription>Breakdown of realized returns, win rates, and Sharpe ratios per strategy.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow className="border-border">
                      <TableHead>Strategy</TableHead>
                      <TableHead className="text-right">Runs</TableHead>
                      <TableHead className="text-right">Trades</TableHead>
                      <TableHead className="text-right">Win Rate</TableHead>
                      <TableHead className="text-right">Sharpe Ratio</TableHead>
                      <TableHead className="text-right">Max Drawdown</TableHead>
                      <TableHead className="text-right">Realized PnL</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {strategyData.map((strat, idx) => (
                      <TableRow key={strat.strategy || idx} className="hover:bg-muted/40 border-border/60">
                        <TableCell className="font-semibold text-foreground">{strat.strategy}</TableCell>
                        <TableCell className="text-right font-mono text-muted-foreground">{strat.runs}</TableCell>
                        <TableCell className="text-right font-mono text-muted-foreground">{strat.trades}</TableCell>
                        <TableCell className="text-right font-mono text-muted-foreground">
                          {strat.win_rate_pct ? `${strat.win_rate_pct.toFixed(1)}%` : "0.0%"}
                        </TableCell>
                        <TableCell className={`text-right font-mono font-semibold ${strat.sharpe >= 1.5 ? "text-green-500" : strat.sharpe > 0 ? "text-yellow-500" : "text-muted-foreground"}`}>
                          {strat.sharpe ? strat.sharpe.toFixed(2) : "0.00"}
                        </TableCell>
                        <TableCell className="text-right font-mono text-red-400">
                          {strat.max_dd_pct ? `${strat.max_dd_pct.toFixed(1)}%` : "0.0%"}
                        </TableCell>
                        <TableCell className={`text-right font-mono font-bold ${strat.pnl >= 0 ? "text-green-500" : "text-red-500"}`}>
                          ${strat.pnl ? strat.pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "0.00"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>

        </div>
      )}

    </div>
  );
}
