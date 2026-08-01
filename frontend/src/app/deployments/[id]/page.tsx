"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { fetchDeploymentEvents } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";

export default function DeploymentDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [events, setEvents] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      setLoading(true);
      const res = await fetchDeploymentEvents(id);
      setEvents(res);
      setLoading(false);
    }
    load();
    const interval = setInterval(load, 10000); // Live poll every 10s
    return () => clearInterval(interval);
  }, [id]);

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      <div>
        <h1 className="text-4xl font-bold tracking-tight">Deployment: {id}</h1>
        <p className="text-muted-foreground mt-2">Live activity feed and execution events.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Event Log</CardTitle>
          <CardDescription>All state changes, orders, and errors.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Message</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {events.map((ev: any, i: number) => (
                <TableRow key={i}>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                    {new Date(ev.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell>
                    <Badge variant={ev.level === 'error' ? 'destructive' : ev.level === 'info' ? 'default' : 'secondary'}>
                      {ev.event_type}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-mono text-xs">{ev.message}</TableCell>
                </TableRow>
              ))}
              {events.length === 0 && !loading && (
                <TableRow>
                  <TableCell colSpan={3} className="text-center text-muted-foreground py-6">
                    No events recorded for this deployment.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
