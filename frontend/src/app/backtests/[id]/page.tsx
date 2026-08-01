"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { fetchRunSummary } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export default function BacktestDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      setLoading(true);
      const res = await fetchRunSummary(id);
      setData(res);
      setLoading(false);
    }
    load();
  }, [id]);

  if (loading) return <div className="p-8">Loading...</div>;
  if (!data) return <div className="p-8">Run not found.</div>;

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-4xl font-bold tracking-tight">Run: {id}</h1>
          <p className="text-muted-foreground mt-2">Strategy: {data.run?.strategy} | Symbol: {data.run?.symbol}</p>
        </div>
        <Badge variant={data.run?.return_pct >= 0 ? "default" : "destructive"} className="text-lg px-4 py-1">
          {data.run?.return_pct?.toFixed(2)}% Return
        </Badge>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <Card>
          <CardHeader>
            <CardTitle>Equity Curve</CardTitle>
            <CardDescription>Cumulative portfolio value over time.</CardDescription>
          </CardHeader>
          <CardContent>
            {/* Direct proxy to FastAPI png endpoint */}
            <img src={`/api/runs/${id}/equity.png`} alt="Equity Curve" className="w-full h-auto rounded-md border" />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Monthly Heatmap</CardTitle>
            <CardDescription>PnL breakdown by year and month.</CardDescription>
          </CardHeader>
          <CardContent>
            <img src={`/api/runs/${id}/heatmap.png`} alt="Heatmap" className="w-full h-auto rounded-md border" />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Trade Statistics</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
            <div>
              <p className="text-sm text-muted-foreground">Total Trades</p>
              <p className="text-xl font-medium">{data.metrics?.total_trades}</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Win Rate</p>
              <p className="text-xl font-medium">{data.metrics?.win_rate?.toFixed(2)}%</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Profit Factor</p>
              <p className="text-xl font-medium">{data.metrics?.profit_factor?.toFixed(2)}</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Max Drawdown</p>
              <p className="text-xl font-medium text-red-400">{data.metrics?.max_drawdown_pct?.toFixed(2)}%</p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
