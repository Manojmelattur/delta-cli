"use client";

import { useEffect, useState } from "react";
import { fetchRuns, fetchSymbols, fetchStrategies, createBacktest } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SortableTable, ColumnDef } from "@/components/ui/sortable-table";
import Link from "next/link";
import { FileText, Pencil } from "lucide-react";

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

export default function BacktestsPage() {
  const [runs, setRuns] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  

  
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



  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      <div className="flex justify-between items-center">
        <h1 className="text-4xl font-bold tracking-tight">Historical Backtests</h1>
        <div className="flex gap-4">
          <Button onClick={load} variant="outline" disabled={loading}>Refresh</Button>
          <Link href="/backtests/create">
            <Button>New Backtest</Button>
          </Link>
        </div>
      </div>
      
      <Card>
        <CardHeader>
          <CardTitle>Run History</CardTitle>
          <CardDescription>View all historical backtest runs and their performance.</CardDescription>
        </CardHeader>
        <CardContent>
          <SortableTable
            data={runs}
            loading={loading}
            emptyMessage="No backtest runs found. Click 'New Backtest' to run one."
            searchPlaceholder="Search by strategy, symbol..."
            defaultSort={{ key: "created_at", dir: "desc" }}
            columns={[
              { key: "run_id", header: "Run ID", sortable: true, className: "font-mono text-xs",
                render: (v: any) => <a href={`/backtests/${v}`} className="text-primary hover:underline">{v}</a> },
              { key: "strategy", header: "Strategy", sortable: true, className: "font-medium" },
              { key: "symbol", header: "Symbol", sortable: true },
              { key: "resolution", header: "TF", sortable: true },
              { key: "trades", header: "Trades", sortable: true },
              { key: "return_pct", header: "Return %", sortable: true,
                render: (v: any) => (
                  <Badge variant={v >= 0 ? 'default' : 'destructive'}>
                    {v?.toFixed(2)}%
                  </Badge>
                ) },
              { key: "max_dd_pct", header: "Max DD%", sortable: true,
                render: (v: any) => v != null ? <span className="text-purple-400">{v.toFixed(2)}%</span> : "—" },
              { key: "sharpe", header: "Sharpe", sortable: true,
                render: (v: any) => v?.toFixed(2) },
              { key: "created_at", header: "Date", sortable: true, className: "text-muted-foreground",
                render: (v: any) => v ? new Date(v).toLocaleDateString() : "—" },
              { key: "actions", header: "Actions", sortable: false, className: "text-right",
                render: (_, row: any) => (
                  <div className="flex items-center justify-end gap-2">
                    <Link href={`/backtests/${row.run_id}`}>
                      <Button variant="ghost" size="icon" title="View Report">
                        <FileText className="h-4 w-4 text-blue-400" />
                      </Button>
                    </Link>
                    <Link href={`/backtests/${row.run_id}/edit`}>
                      <Button variant="ghost" size="icon" title="Edit & Rerun">
                        <Pencil className="h-4 w-4 text-orange-400" />
                      </Button>
                    </Link>
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
