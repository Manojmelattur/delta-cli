"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { fetchTaskLogs } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ArrowLeft, Terminal, RefreshCw } from "lucide-react";

export default function TaskLogsPage() {
  const params = useParams();
  const id = params.id as string;
  const [logs, setLogs] = useState<string>("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try {
      const data = await fetchTaskLogs(id);
      setLogs(data.logs || "No logs found.");
    } catch(e: any) {
      setLogs("Error: " + e.message);
    }
    setLoading(false);
  }

  useEffect(() => {
    load();
    const timer = setInterval(load, 5000); // Auto-refresh every 5s
    return () => clearInterval(timer);
  }, [id]);

  return (
    <div className="p-8 space-y-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link href="/tasks">
            <Button variant="ghost" size="icon" className="hover:bg-zinc-800">
              <ArrowLeft className="h-5 w-5" />
            </Button>
          </Link>
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-white flex items-center gap-2">
              <Terminal className="h-7 w-7 text-green-400" />
              Task #{id} Logs
            </h1>
            <p className="text-muted-foreground mt-1 text-sm">Real-time execution logs for this scheduled task</p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading} className="gap-2">
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      <div className="rounded-lg border bg-card text-card-foreground shadow-sm bg-black overflow-hidden p-6">
        <pre className="font-mono text-sm text-zinc-300 whitespace-pre-wrap max-h-[70vh] overflow-y-auto">
          {logs}
        </pre>
      </div>
    </div>
  );
}
