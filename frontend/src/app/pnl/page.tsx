"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fetchPnlSummary } from "@/lib/api";

export default function PnlPage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    const res = await fetchPnlSummary();
    setData(res);
    setLoading(false);
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      <div className="flex justify-between items-center">
        <h1 className="text-4xl font-bold tracking-tight">PnL Analytics</h1>
        <Button onClick={load} variant="outline" disabled={loading}>Refresh</Button>
      </div>

      {!data && !loading && (
        <Card><CardContent className="p-6 text-center text-muted-foreground">No PnL data available.</CardContent></Card>
      )}

      {data && (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Portfolio Overview (Last 30 Days)</CardTitle>
              <CardDescription>Aggregate realized PnL across all strategies.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="space-y-1">
                  <p className="text-sm text-muted-foreground font-medium">Total Realized PnL</p>
                  <p className={`text-2xl font-bold ${data?.total_realized_pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                    ${data?.total_realized_pnl?.toFixed(2)}
                  </p>
                </div>
                <div className="space-y-1">
                  <p className="text-sm text-muted-foreground font-medium">Total Fees</p>
                  <p className="text-2xl font-bold text-red-400">
                    ${data?.total_fees?.toFixed(2)}
                  </p>
                </div>
                <div className="space-y-1">
                  <p className="text-sm text-muted-foreground font-medium">Net PnL</p>
                  <p className={`text-2xl font-bold ${(data?.total_realized_pnl - data?.total_fees) >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                    ${(data?.total_realized_pnl - data?.total_fees)?.toFixed(2)}
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
