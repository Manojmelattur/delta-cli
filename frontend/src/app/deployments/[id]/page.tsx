"use client";

import { useEffect, useState, useMemo } from "react";
import { useParams } from "next/navigation";
import { fetchDeploymentEvents, fetchDeployment } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { ArrowUpRight, ArrowDownRight, Activity, Hash, Percent } from "lucide-react";

export default function DeploymentDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [deployment, setDeployment] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      setLoading(true);
      const [depRes, evRes] = await Promise.all([
        fetchDeployment(id),
        fetchDeploymentEvents(id)
      ]);
      setDeployment(depRes);
      // Backend returns them in descending order (newest first). 
      // For charting, we want them in ascending order (oldest first).
      setEvents(evRes.rows ? [...evRes.rows].reverse() : [...evRes].reverse());
      setLoading(false);
    }
    load();
    const interval = setInterval(async () => {
      const [depRes, evRes] = await Promise.all([
        fetchDeployment(id),
        fetchDeploymentEvents(id)
      ]);
      setDeployment(depRes);
      setEvents(evRes.rows ? [...evRes.rows].reverse() : [...evRes].reverse());
    }, 10000);
    return () => clearInterval(interval);
  }, [id]);

  const metrics = useMemo(() => {
    let totalPnl = 0;
    let winningTrades = 0;
    let totalTrades = 0;
    let peakEquity = 0;
    let currentDrawdown = 0;
    
    events.forEach(ev => {
      if (ev.kind === 'trade' && ev.pnl !== null) {
        totalTrades++;
        if (ev.pnl > 0) winningTrades++;
      }
      if (ev.equity_after !== undefined && ev.equity_after !== null) {
        totalPnl = ev.equity_after; // Assuming it starts at 0
        if (ev.equity_after > peakEquity) peakEquity = ev.equity_after;
        const drawdown = peakEquity > 0 ? (peakEquity - ev.equity_after) / peakEquity * 100 : 0;
        if (drawdown > currentDrawdown) currentDrawdown = drawdown;
      }
    });

    const winRate = totalTrades > 0 ? (winningTrades / totalTrades) * 100 : 0;

    // Build chart data
    const chartData = events
      .filter(ev => ev.equity_after !== undefined && ev.equity_after !== null)
      .map(ev => ({
        time: new Date(ev.ts || ev.created_at || Date.now()).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}),
        equity: ev.equity_after,
        pnl: ev.pnl
      }));

    return { totalPnl, winRate, totalTrades, currentDrawdown, chartData };
  }, [events]);

  if (loading && !deployment) {
    return <div className="p-8 text-center animate-pulse">Loading analytics...</div>;
  }

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-4xl font-bold tracking-tight mb-2">
            {deployment?.name || `Deployment #${id}`}
          </h1>
          <div className="flex gap-2 items-center text-sm text-muted-foreground">
            <Badge variant="outline">{deployment?.symbol}</Badge>
            <span>•</span>
            <span>{deployment?.strategy}</span>
            <span>•</span>
            <Badge variant={deployment?.status === 'running' ? 'default' : 'secondary'}>
              {deployment?.status || 'Unknown'}
            </Badge>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Realized PnL</CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold ${metrics.totalPnl >= 0 ? 'text-green-500' : 'text-purple-500'}`}>
              {metrics.totalPnl >= 0 ? '+' : ''}${metrics.totalPnl.toFixed(2)}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Win Rate</CardTitle>
            <Percent className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{metrics.winRate.toFixed(1)}%</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Total Trades</CardTitle>
            <Hash className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{metrics.totalTrades}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Max Drawdown</CardTitle>
            <ArrowDownRight className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-purple-400">{metrics.currentDrawdown.toFixed(2)}%</div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Equity Curve</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-[400px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={metrics.chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                <XAxis dataKey="time" stroke="#888" />
                <YAxis stroke="#888" domain={['auto', 'auto']} />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#1f2937', borderColor: '#374151', color: '#fff' }}
                  itemStyle={{ color: '#10b981' }}
                />
                <Line type="stepAfter" dataKey="equity" stroke="#10b981" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Event History</CardTitle>
          <CardDescription>Chronological log of orders, execution events, and errors.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="max-h-[500px] overflow-y-auto border rounded-md">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[180px]">Time</TableHead>
                  <TableHead className="w-[120px]">Type</TableHead>
                  <TableHead>Message</TableHead>
                  <TableHead className="text-right">PnL</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {/* Render events back in descending order for the table */}
                {[...events].reverse().map((ev: any, i: number) => (
                  <TableRow key={i}>
                    <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                      {new Date(ev.ts || ev.created_at || Date.now()).toLocaleString()}
                    </TableCell>
                    <TableCell>
                      <Badge variant={ev.kind === 'error' ? 'destructive' : ev.kind === 'trade' ? 'default' : 'secondary'}>
                        {ev.kind || ev.event_type || 'info'}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {ev.message} 
                      {ev.order_id ? ` (Order: ${ev.order_id})` : ''}
                      {ev.price ? ` @ $${ev.price}` : ''}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">
                      {ev.pnl ? (
                        <span className={ev.pnl > 0 ? 'text-green-500' : 'text-purple-500'}>
                          {ev.pnl > 0 ? '+' : ''}{ev.pnl.toFixed(2)}
                        </span>
                      ) : '-'}
                    </TableCell>
                  </TableRow>
                ))}
                {events.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={4} className="text-center text-muted-foreground py-8">
                      No events recorded for this deployment yet.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
