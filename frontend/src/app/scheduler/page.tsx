"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { 
  fetchSchedulerStatus, fetchSchedulerLogs, restartScheduler, 
  fetchSettings, updateSettings, fetchTasks, toggleTask 
} from "@/lib/api";
import { 
  Cpu, Activity, Clock, RefreshCw, AlertTriangle, ShieldCheck, 
  Terminal, Settings, Calendar, Play, Pause 
} from "lucide-react";

export default function SchedulerPage() {
  const [status, setStatus] = useState<any>(null);
  const [logRows, setLogRows] = useState<any[]>([]);
  const [tasks, setTasks] = useState<any[]>([]);
  const [settings, setSettings] = useState<any>({});
  const [loading, setLoading] = useState(true);

  // Dialog States
  const [restartModalOpen, setRestartModalOpen] = useState(false);
  const [restartReason, setRestartReason] = useState("");

  // Log filter
  const [logLevel, setLogLevel] = useState<string>("");

  async function loadData() {
    setLoading(true);
    try {
      const [stat, logRes, sets, tasksRes] = await Promise.all([
        fetchSchedulerStatus(),
        fetchSchedulerLogs(),
        fetchSettings(),
        fetchTasks()
      ]);
      
      setStatus(stat);
      setLogRows(logRes?.rows || []);
      setSettings(sets || {});
      setTasks(Array.isArray(tasksRes) ? tasksRes : []);
    } catch (e) {
      console.error("Failed to load scheduler data:", e);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 5000); // Auto-refresh every 5s
    return () => clearInterval(interval);
  }, []);

  async function handleRestartConfirm() {
    setRestartModalOpen(false);
    setLoading(true);
    try {
      await restartScheduler(restartReason);
      setRestartReason("");
      // Wait briefly for daemon to write status, then reload
      setTimeout(loadData, 1500);
    } catch (e) {
      alert("Failed to submit restart request");
    }
  }

  async function handleToggleTask(taskId: number, currentStatus: string) {
    const nextStatus = currentStatus === "active" ? "paused" : "active";
    try {
      await toggleTask(taskId.toString(), nextStatus);
      loadData();
    } catch (e) {
      alert("Failed to update task state");
    }
  }

  async function handleSaveSettings() {
    setLoading(true);
    try {
      await updateSettings(settings);
      loadData();
    } catch (e) {
      alert("Failed to save global configuration");
    }
  }

  // Format log row to plain text for downloading or viewing raw
  const formatRawLogs = () => {
    return logRows
      .filter(r => !logLevel || r.level === logLevel)
      .map(r => `[${r.ts}] [${r.level}] ${r.msg}`)
      .join("\n");
  };

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8 animate-in fade-in duration-300">
      
      {/* HEADER */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-4xl font-bold tracking-tight">System Scheduler</h1>
          <p className="text-muted-foreground mt-1">Monitor background event dispatcher, manage scheduled tasks, and view daemon health.</p>
        </div>
        <div className="flex items-center gap-3">
          <Button onClick={loadData} variant="outline" className="flex items-center gap-2" disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Refresh
          </Button>
          <Button onClick={() => setRestartModalOpen(true)} variant="destructive" className="flex items-center gap-2">
            <RefreshCw className="h-4 w-4" /> Restart Daemon
          </Button>
        </div>
      </div>

      {/* PENDING RESTART WARNING BANNER */}
      {status?.restart_requested === 1 && (
        <Card className="border-amber-500/50 bg-amber-500/10 text-amber-200">
          <CardContent className="p-4 flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 mt-0.5 text-amber-500 flex-shrink-0" />
            <div>
              <p className="font-semibold text-amber-300">Scheduler Restart Requested</p>
              <p className="text-sm mt-0.5">
                The daemon is scheduled to restart shortly. Reason: <span className="font-semibold text-white">"{status?.restart_reason || "No reason given"}"</span> (Requested at {status?.restart_requested_at})
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* SYSTEM HEALTH GRID */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        
        {/* SCHEDULER DAEMON STATE */}
        <Card className="border border-border/80 shadow-md">
          <CardContent className="p-6 flex items-center justify-between">
            <div className="space-y-1.5">
              <p className="text-xs text-muted-foreground font-semibold uppercase tracking-wider">Scheduler State</p>
              <div className="flex items-center gap-2">
                <Badge className="text-sm px-2.5 py-0.5" variant={status?.alive ? "default" : "destructive"}>
                  {status?.alive ? "ALIVE" : "OFFLINE"}
                </Badge>
              </div>
              <p className="text-[11px] text-muted-foreground">Version: {status?.version || "Unknown"}</p>
            </div>
            <div className={`p-3.5 rounded-full ${status?.alive ? "bg-green-500/10 text-green-500" : "bg-red-500/10 text-red-500"}`}>
              <ShieldCheck className="h-6 w-6" />
            </div>
          </CardContent>
        </Card>

        {/* HEARTBEAT AGE */}
        <Card className="border border-border/80 shadow-md">
          <CardContent className="p-6 flex items-center justify-between">
            <div className="space-y-1.5">
              <p className="text-xs text-muted-foreground font-semibold uppercase tracking-wider">Last Heartbeat</p>
              <p className="text-2xl font-bold tracking-tight">
                {status?.heartbeat_age_sec != null ? `${status.heartbeat_age_sec.toFixed(1)}s ago` : "-"}
              </p>
              <p className="text-[11px] text-muted-foreground">Tolerance threshold: {status?.threshold_sec || "60"}s</p>
            </div>
            <div className="p-3.5 bg-primary/10 text-primary rounded-full">
              <Activity className="h-6 w-6" />
            </div>
          </CardContent>
        </Card>

        {/* SYSTEM PID */}
        <Card className="border border-border/80 shadow-md">
          <CardContent className="p-6 flex items-center justify-between">
            <div className="space-y-1.5">
              <p className="text-xs text-muted-foreground font-semibold uppercase tracking-wider">Watcher PID</p>
              <p className="text-2xl font-bold tracking-tight font-mono">
                {status?.pid || "-"}
              </p>
              <p className="text-[11px] text-muted-foreground">Last Heartbeat timestamp: {status?.last_heartbeat_at?.split("T")[1]?.slice(0, 8) || "-"}</p>
            </div>
            <div className="p-3.5 bg-zinc-500/10 text-zinc-400 rounded-full">
              <Cpu className="h-6 w-6" />
            </div>
          </CardContent>
        </Card>

        {/* LAST RESTART TIME */}
        <Card className="border border-border/80 shadow-md">
          <CardContent className="p-6 flex items-center justify-between">
            <div className="space-y-1.5">
              <p className="text-xs text-muted-foreground font-semibold uppercase tracking-wider">Last Restarted</p>
              <p className="text-lg font-bold tracking-tight truncate max-w-[200px]">
                {status?.last_restart_at ? status.last_restart_at.split("T")[1]?.slice(0, 8) : "N/A"}
              </p>
              <p className="text-[11px] text-muted-foreground">Date: {status?.last_restart_at ? status.last_restart_at.split("T")[0] : "Never"}</p>
            </div>
            <div className="p-3.5 bg-amber-500/10 text-amber-500 rounded-full">
              <Clock className="h-6 w-6" />
            </div>
          </CardContent>
        </Card>

      </div>

      {/* DETAILED VIEWS */}
      <Tabs defaultValue="logs" className="w-full">
        <TabsList className="grid grid-cols-3 max-w-md">
          <TabsTrigger value="logs" className="flex items-center gap-2">
            <Terminal className="h-4 w-4" /> Live Logs
          </TabsTrigger>
          <TabsTrigger value="tasks" className="flex items-center gap-2">
            <Calendar className="h-4 w-4" /> System Tasks
          </TabsTrigger>
          <TabsTrigger value="settings" className="flex items-center gap-2">
            <Settings className="h-4 w-4" /> Configuration
          </TabsTrigger>
        </TabsList>

        {/* LIVE LOGS TAB */}
        <TabsContent value="logs" className="mt-6">
          <Card className="border border-border/80 shadow-md">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
              <div>
                <CardTitle>Scheduler Watcher Logs</CardTitle>
                <CardDescription>Live diagnostic execution log events stored in DB ring buffer.</CardDescription>
              </div>
              <div className="flex gap-2">
                <Select value={logLevel} onValueChange={v => { if (v !== null) setLogLevel(v); }}>
                  <SelectTrigger className="w-32 h-8">
                    <SelectValue placeholder="All Levels" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="">All Levels</SelectItem>
                    <SelectItem value="INFO">INFO</SelectItem>
                    <SelectItem value="WARNING">WARNING</SelectItem>
                    <SelectItem value="ERROR">ERROR</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </CardHeader>
            <CardContent>
              <div className="p-4 bg-black rounded-lg border border-border/60 overflow-hidden">
                <pre className="h-96 overflow-y-auto font-mono text-xs text-zinc-300 space-y-1.5 select-text whitespace-pre-wrap">
                  {logRows.length === 0 ? (
                    <span className="text-muted-foreground italic">No logs available matching filters.</span>
                  ) : (
                    logRows
                      .filter(r => !logLevel || r.level === logLevel)
                      .map((r, i) => (
                        <div key={i} className="flex gap-2 hover:bg-zinc-900/60 p-0.5 rounded transition">
                          <span className="text-zinc-500 flex-shrink-0">[{r.ts.split("T")[1]?.slice(0, 8)}]</span>
                          <span className={`flex-shrink-0 font-bold ${
                            r.level === 'ERROR' ? 'text-red-500' :
                            r.level === 'WARNING' ? 'text-yellow-500' : 'text-green-500'
                          }`}>
                            [{r.level}]
                          </span>
                          <span className="text-zinc-200">{r.msg}</span>
                        </div>
                      ))
                  )}
                </pre>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* SYSTEM TASKS TAB */}
        <TabsContent value="tasks" className="mt-6">
          <Card className="border border-border/80 shadow-md">
            <CardHeader>
              <CardTitle>Active Scheduled Tasks</CardTitle>
              <CardDescription>Quick overview of scheduled background routines run by the scheduler.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow className="border-border">
                      <TableHead>Task / Cron Path</TableHead>
                      <TableHead>Trigger Rule</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead className="text-right">Last Triggered</TableHead>
                      <TableHead className="text-right">Action</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {tasks.map((task: any) => (
                      <TableRow key={task.id} className="hover:bg-muted/40 border-border/60">
                        <TableCell className="font-semibold text-foreground">
                          <div>
                            <p>{task.name}</p>
                            <p className="text-xs text-muted-foreground font-mono mt-0.5">{task.command || "N/A"}</p>
                          </div>
                        </TableCell>
                        <TableCell className="font-mono text-xs text-primary">{task.schedule_rule}</TableCell>
                        <TableCell>
                          <Badge variant={task.status === 'active' ? 'default' : 'secondary'}>
                            {task.status}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs text-muted-foreground">
                          {task.last_run ? task.last_run.replace("T", " ").slice(0, 19) : "Never"}
                        </TableCell>
                        <TableCell className="text-right">
                          <Button 
                            size="sm" 
                            variant="outline" 
                            onClick={() => handleToggleTask(task.id, task.status)}
                            className="h-8"
                          >
                            {task.status === 'active' ? (
                              <><Pause className="h-3 w-3 mr-1" /> Pause</>
                            ) : (
                              <><Play className="h-3 w-3 mr-1" /> Resume</>
                            )}
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                    {tasks.length === 0 && (
                      <TableRow>
                        <TableCell colSpan={5} className="text-center py-6 text-muted-foreground">No tasks seeded.</TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* SCHEDULER CONFIGURATION TAB */}
        <TabsContent value="settings" className="mt-6">
          <Card className="border border-border/80 shadow-md">
            <CardHeader>
              <CardTitle>Global Scheduler Settings</CardTitle>
              <CardDescription>Configure properties inside the global `app_settings` database tables.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {Object.keys(settings).length === 0 && (
                <p className="text-muted-foreground text-sm">No global settings records discovered.</p>
              )}
              {Object.keys(settings).map(key => (
                <div key={key} className="space-y-2">
                  <label className="text-sm font-semibold text-foreground uppercase tracking-wider">{key}</label>
                  <textarea
                    className="w-full h-32 p-3 font-mono text-sm bg-black text-green-400 border border-border/85 rounded-md focus:outline-none focus:ring-1 focus:ring-primary"
                    value={typeof settings[key] === 'object' ? JSON.stringify(settings[key], null, 2) : settings[key]}
                    onChange={(e) => {
                      try {
                        const val = JSON.parse(e.target.value);
                        setSettings({...settings, [key]: val});
                      } catch(err) {
                        // permit typing raw string or partial objects
                        setSettings({...settings, [key]: e.target.value});
                      }
                    }}
                  />
                </div>
              ))}
              <Button onClick={handleSaveSettings} className="w-full sm:w-auto">
                Save Global Config
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

      </Tabs>

      {/* RESTART CONFIRMATION DIALOG */}
      <Dialog open={restartModalOpen} onOpenChange={setRestartModalOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-destructive">
              <AlertTriangle className="h-5 w-5" /> Restart Scheduler Daemon
            </DialogTitle>
            <DialogDescription>
              Are you sure you want to request a scheduler restart? Active deployments will momentarily pause processing ticks while the system re-initializes.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-4">
            <label className="text-sm font-semibold">Reason for Restart (Optional)</label>
            <Input 
              placeholder="e.g. Configuration update, strategy manifest refresh" 
              value={restartReason} 
              onChange={e => setRestartReason(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRestartModalOpen(false)}>Cancel</Button>
            <Button variant="destructive" onClick={handleRestartConfirm}>Restart Daemon</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

    </div>
  );
}
