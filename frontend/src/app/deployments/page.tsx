"use client";
import Link from "next/link";

import { useEffect, useState } from "react";
import { fetchDeployments, actionDeployment, editDeployment, testTradeDeployment, fetchDeploymentLogs } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { SortableTable, ColumnDef } from "@/components/ui/sortable-table";
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

export default function DeploymentsPage() {
  const [deployments, setDeployments] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  
  
  const [symbols, setSymbols] = useState<string[]>([]);
  const [strategies, setStrategies] = useState<string[]>([]);
  
  const [openLogs, setOpenLogs] = useState(false);
  const [logs, setLogs] = useState<any[]>([]);

  async function load() {
    setLoading(true);
    const res = await fetchDeployments();
    setDeployments(res);
    setLoading(false);
  }

  useEffect(() => {
    load();
    import("@/lib/api").then(api => {
      api.fetchSymbols().then(setSymbols).catch(() => {});
      api.fetchStrategies().then(setStrategies).catch(() => {});
    });
  }, []);

  async function handleAction(id: string | number, action: 'pause' | 'resume' | 'stop' | 'delete') {
    if (action === 'stop' && !confirm("Are you sure you want to stop this bot?")) return;
    if (action === 'delete' && !confirm("Are you sure you want to delete this bot?")) return;
    await actionDeployment(id, action);
    load();
  }


  async function handleTestTrade(id: string | number) {
    if (!confirm("Are you sure you want to run a test trade on this live deployment?")) return;
    try {
      await testTradeDeployment(id);
      alert("Test trade scheduled");
    } catch(e: any) {
      alert(e.message);
    }
  }
  
  async function handleViewLogs(id: string | number) {
    setLogs([]);
    setOpenLogs(true);
    try {
      const res = await fetchDeploymentLogs(id);
      setLogs(res);
    } catch(e: any) {
      alert("Error: " + e.message);
    }
  }

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      <div className="flex justify-between items-center">
        <h1 className="text-4xl font-bold tracking-tight">Deployments</h1>
        <div className="flex gap-4">
          <Button onClick={load} variant="outline" disabled={loading}>Refresh</Button>
          <Link href="/deployments/create">
            <Button>New Deployment</Button>
          </Link>
        </div>
      </div>


      
      <Dialog open={openLogs} onOpenChange={setOpenLogs}>
        <DialogContent className="max-w-4xl">
          <DialogHeader>
            <DialogTitle>Deployment Logs & Events</DialogTitle>
          </DialogHeader>
          <div className="max-h-[600px] overflow-y-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Time</TableHead>
                  <TableHead>Event</TableHead>
                  <TableHead>Message</TableHead>
                  <TableHead>PnL</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {logs.map((l: any, i: number) => (
                  <TableRow key={i}>
                    <TableCell className="whitespace-nowrap">{l.ts}</TableCell>
                    <TableCell><Badge variant={l.kind === 'error' ? 'destructive' : 'outline'}>{l.kind}</Badge></TableCell>
                    <TableCell>{l.message}</TableCell>
                    <TableCell className={l.pnl > 0 ? 'text-green-500' : l.pnl < 0 ? 'text-purple-500' : ''}>
                      {l.pnl ? l.pnl.toFixed(4) : ''}
                    </TableCell>
                  </TableRow>
                ))}
                {logs.length === 0 && (
                  <TableRow><TableCell colSpan={4} className="text-center py-4">No events found.</TableCell></TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </DialogContent>
      </Dialog>

      <Card>
        <CardHeader>
          <CardTitle>Active Bots</CardTitle>
          <CardDescription>Manage running algorithmic trading deployments.</CardDescription>
        </CardHeader>
        <CardContent>
          <SortableTable
            data={deployments}
            loading={loading}
            emptyMessage="No deployments found. Create one with 'New Deployment'."
            searchPlaceholder="Search by name, strategy, symbol..."
            defaultSort={{ key: "id", dir: "desc" }}
            columns={[
              { key: "id", header: "#", sortable: true, className: "font-medium w-12",
                render: (v: any, dep: any) => (
                  <Link href={`/deployments/${dep.id}`} className="hover:underline text-primary">
                    #{v}
                  </Link>
                ) },
              { key: "name", header: "Name", sortable: true,
                render: (v: any, dep: any) => (
                  <Link href={`/deployments/${dep.id}`} className="hover:underline font-semibold text-primary">
                    {v}
                  </Link>
                ) },
              { key: "strategy", header: "Strategy", sortable: true },
              { key: "symbol", header: "Symbol", sortable: true },
              { key: "timeframe", header: "TF", sortable: true },
              { key: "venue", header: "Venue", sortable: true },
              { key: "realized_pnl", header: "PnL", sortable: true,
                render: (v: any) => (
                  <span className={v > 0 ? "text-green-400 font-mono" : v < 0 ? "text-purple-400 font-mono" : "text-zinc-400 font-mono"}>
                    {v != null ? `$${Math.abs(v).toFixed(2)}${v < 0 ? '-' : ''}`.replace('$-', '-$') : "$0.00"}
                  </span>
                ) 
              },
              { key: "profit_pct", header: "PnL %", sortable: false,
                render: (_: any, dep: any) => {
                  const pct = dep.profit_pct != null ? dep.profit_pct : (dep.size ? (dep.realized_pnl / (dep.size * (dep.contract_value || 1))) * 100 : 0);
                  return (
                    <Badge variant={pct >= 0 ? 'default' : 'destructive'}>
                      {pct?.toFixed(2)}%
                    </Badge>
                  );
                } 
              },
              { key: "day_pnl", header: "Day PnL", sortable: false,
                render: (_: any, dep: any) => {
                  const daypnl = dep.day_pnl ?? dep.daypnl ?? 0;
                  return (
                    <span className={daypnl > 0 ? "text-green-400 font-mono" : daypnl < 0 ? "text-purple-400 font-mono" : "text-zinc-400 font-mono"}>
                      {daypnl != null ? `$${Math.abs(daypnl).toFixed(2)}${daypnl < 0 ? '-' : ''}`.replace('$-', '-$') : "$0.00"}
                    </span>
                  );
                } 
              },
              { key: "status", header: "Status", sortable: true,
                render: (v: any) => (
                  <Badge variant={v === 'running' ? 'default' : v === 'paused' ? 'secondary' : 'outline'}>
                    {v}
                  </Badge>
                ) },
              { key: "_actions", header: "Actions", sortable: false, searchable: false,
                render: (_: any, dep: any) => (
                  <div className="flex gap-1.5 flex-wrap">
                    <Button size="sm" variant="outline" onClick={() => handleAction(dep.id, dep.status === 'active' || dep.status === 'running' ? 'pause' : 'resume')}>
                      {dep.status === 'active' || dep.status === 'running' ? 'Pause' : 'Resume'}
                    </Button>
                    <Link href={`/deployments/${dep.id}/edit`}>
                      <Button size="sm" variant="secondary">Edit</Button>
                    </Link>
                    <Button size="sm" variant="secondary" onClick={() => handleTestTrade(dep.id)}>Test</Button>
                    <Link href={`/deployments/${dep.id}`}>
                      <Button size="sm" variant="secondary">Events</Button>
                    </Link>
                    {dep.status === 'stopped' ? (
                      <Button size="sm" variant="destructive" onClick={() => handleAction(dep.id, 'delete')}>Delete</Button>
                    ) : (
                      <Button size="sm" variant="destructive" onClick={() => handleAction(dep.id, 'stop')}>Stop</Button>
                    )}
                  </div>
                )
              },
            ] as ColumnDef[]}
          />
        </CardContent>
      </Card>
    </div>
  );
}
