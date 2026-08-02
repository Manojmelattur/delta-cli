"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { 
  fetchSystemIp, 
  clearBacktests, 
  clearDeployments, 
  seedDefaultTasks, 
  factoryReset,
  fetchSchedulerLogs,
  restartScheduler
} from "@/lib/api";
import { Copy, RefreshCw, Trash2, AlertTriangle, Play, CheckCircle2 } from "lucide-react";

export default function SettingsPage() {
  const [ipData, setIpData] = useState<any>(null);
  const [logs, setLogs] = useState<string>("");
  const [loadingIp, setLoadingIp] = useState(false);
  const [loadingLogs, setLoadingLogs] = useState(false);
  const [copied, setCopied] = useState(false);
  const [actionStatus, setActionStatus] = useState<{ [key: string]: { loading: boolean; message: string; success?: boolean } }>({
    backtests: { loading: false, message: "" },
    deployments: { loading: false, message: "" },
    tasks: { loading: false, message: "" },
    reset: { loading: false, message: "" },
    daemon: { loading: false, message: "" },
  });

  async function loadIp() {
    setLoadingIp(true);
    try {
      const data = await fetchSystemIp();
      setIpData(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingIp(false);
    }
  }

  async function loadLogs() {
    setLoadingLogs(true);
    try {
      const logData = await fetchSchedulerLogs();
      setLogs(logData?.logs || "No logs available.");
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingLogs(false);
    }
  }

  useEffect(() => {
    loadIp();
    loadLogs();
  }, []);

  const copyToClipboard = () => {
    if (ipData?.ip) {
      navigator.clipboard.writeText(ipData.ip);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const updateActionStatus = (key: string, loading: boolean, message: string, success?: boolean) => {
    setActionStatus(prev => ({
      ...prev,
      [key]: { loading, message, success }
    }));
  };

  const handleClearBacktests = async () => {
    if (!confirm("⚠️ Are you sure you want to clear ALL backtest runs, trades, and equity data? This action is irreversible.")) return;
    updateActionStatus("backtests", true, "Clearing backtest database tables...");
    try {
      const res = await clearBacktests();
      if (res.ok) {
        updateActionStatus("backtests", false, "Successfully cleared all backtest data!", true);
      } else {
        updateActionStatus("backtests", false, `Error: ${res.detail || "Failed to clear backtests"}`, false);
      }
    } catch (e: any) {
      updateActionStatus("backtests", false, `Failed: ${e.message}`, false);
    }
  };

  const handleClearDeployments = async () => {
    if (!confirm("⚠️ Are you sure you want to delete ALL active/paused/stopped deployments? This will clear all historical bot logs and events.")) return;
    updateActionStatus("deployments", true, "Clearing deployments database tables...");
    try {
      const res = await clearDeployments();
      if (res.ok) {
        updateActionStatus("deployments", false, "Successfully cleared all deployments!", true);
      } else {
        updateActionStatus("deployments", false, `Error: ${res.detail || "Failed to clear deployments"}`, false);
      }
    } catch (e: any) {
      updateActionStatus("deployments", false, `Failed: ${e.message}`, false);
    }
  };

  const handleSeedTasks = async () => {
    if (!confirm("Are you sure you want to reset all background tasks and re-seed defaults? Any custom task changes will be reset.")) return;
    updateActionStatus("tasks", true, "Re-seeding background tasks...");
    try {
      const res = await seedDefaultTasks();
      if (res.ok) {
        updateActionStatus("tasks", false, "Successfully re-seeded default background tasks!", true);
      } else {
        updateActionStatus("tasks", false, `Error: ${res.detail || "Failed to re-seed tasks"}`, false);
      }
    } catch (e: any) {
      updateActionStatus("tasks", false, `Failed: ${e.message}`, false);
    }
  };

  const handleFactoryReset = async () => {
    const doubleCheck = confirm("🚨 DANGER ZONE: Are you sure you want to FACTORY RESET the entire application?\n\nThis will purge all backtest data, delete all bot deployments, reset default background tasks, and delete all reports inside the folder.");
    if (!doubleCheck) return;
    updateActionStatus("reset", true, "Executing Master Factory Reset...");
    try {
      const res = await factoryReset();
      if (res.ok) {
        updateActionStatus("reset", false, "Application successfully reset to factory settings!", true);
      } else {
        updateActionStatus("reset", false, `Error: ${res.detail || "Failed to factory reset"}`, false);
      }
    } catch (e: any) {
      updateActionStatus("reset", false, `Failed: ${e.message}`, false);
    }
  };

  const handleRestartDaemon = async () => {
    updateActionStatus("daemon", true, "Sending restart request to Scheduler Daemon...");
    try {
      const res = await restartScheduler();
      if (res.ok) {
        updateActionStatus("daemon", false, "Daemon restart signal dispatched successfully!", true);
        setTimeout(loadLogs, 3000);
      } else {
        updateActionStatus("daemon", false, `Error: ${res.detail || "Failed to restart daemon"}`, false);
      }
    } catch (e: any) {
      updateActionStatus("daemon", false, `Failed: ${e.message}`, false);
    }
  };

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8 animate-in fade-in duration-300">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-4xl font-bold tracking-tight">System Settings</h1>
          <p className="text-muted-foreground mt-1">Manage system databases, environment configurations, and monitor scheduler daemons.</p>
        </div>
        <Button onClick={() => { loadIp(); loadLogs(); }} variant="outline" className="flex items-center gap-2">
          <RefreshCw className="h-4 w-4" /> Refresh All
        </Button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        
        {/* LEFT COLUMN: IP TOOL & LOGS */}
        <div className="lg:col-span-2 space-y-8">
          
          {/* IP TOOL & ENVIRONMENT */}
          <Card className="border border-border/80 shadow-md">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <div>
                <CardTitle className="text-2xl font-bold">Public IP & Clock Sync</CardTitle>
                <CardDescription>Network details and server time offsets for the Delta API connection.</CardDescription>
              </div>
              <Button onClick={loadIp} variant="ghost" size="icon" disabled={loadingIp}>
                <RefreshCw className={`h-4 w-4 ${loadingIp ? "animate-spin" : ""}`} />
              </Button>
            </CardHeader>
            <CardContent className="space-y-6 pt-4">
              {ipData ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="p-4 bg-muted/40 border border-border/50 rounded-lg space-y-2">
                    <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Public IP Address</p>
                    <div className="flex items-center justify-between">
                      <span className="text-lg font-mono font-bold tracking-tight text-primary">
                        {ipData.ip}
                      </span>
                      <Button onClick={copyToClipboard} variant="outline" size="sm" className="h-8 gap-2">
                        <Copy className="h-3.5 w-3.5" />
                        {copied ? "Copied" : "Copy"}
                      </Button>
                    </div>
                  </div>

                  <div className="p-4 bg-muted/40 border border-border/50 rounded-lg space-y-2">
                    <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Clock Skew Status</p>
                    <div className="flex items-center gap-2.5">
                      <Badge variant={ipData.skew_status === "OK" ? "default" : "destructive"} className="px-2.5 py-1 text-sm font-semibold">
                        {ipData.skew_status === "OK" ? "Clock Sync OK" : "Skew Detected"}
                      </Badge>
                      <span className="text-sm font-mono text-muted-foreground">
                        ({ipData.skew}s offset)
                      </span>
                    </div>
                  </div>

                  <div className="md:col-span-2 space-y-3">
                    <div className="flex justify-between text-sm py-1.5 border-b border-border/40">
                      <span className="text-muted-foreground">Delta Server Time Header</span>
                      <span className="font-mono font-semibold">{ipData.server_date}</span>
                    </div>
                    <div className="flex justify-between text-sm py-1.5 border-b border-border/40">
                      <span className="text-muted-foreground">Local Server Timestamp</span>
                      <span className="font-mono font-semibold">{ipData.local_timestamp}</span>
                    </div>
                    {ipData.error && (
                      <div className="p-3 bg-destructive/10 text-destructive text-xs rounded border border-destructive/20 font-mono mt-2">
                        {ipData.error}
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-8 text-center text-muted-foreground">
                  <Play className="h-8 w-8 text-muted-foreground/50 animate-pulse mb-3" />
                  <p>Click refresh or wait for environment details to load.</p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* SCHEDULER LOGS */}
          <Card className="border border-border/80 shadow-md">
            <CardHeader className="flex flex-row items-center justify-between pb-4">
              <div>
                <CardTitle className="text-2xl font-bold">Scheduler Logs</CardTitle>
                <CardDescription>Live streaming process stdout and interval updates from `watcher.log`.</CardDescription>
              </div>
              <div className="flex gap-2">
                <Button onClick={loadLogs} variant="outline" size="sm" disabled={loadingLogs} className="gap-2">
                  <RefreshCw className={`h-3.5 w-3.5 ${loadingLogs ? "animate-spin" : ""}`} /> Reload Logs
                </Button>
                <Button onClick={handleRestartDaemon} variant="destructive" size="sm" disabled={actionStatus.daemon.loading} className="gap-2">
                  <AlertTriangle className="h-3.5 w-3.5" /> Restart Daemon
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {actionStatus.daemon.message && (
                <div className={`p-3 text-sm rounded border ${actionStatus.daemon.success ? "bg-green-500/10 border-green-500/20 text-green-600" : "bg-destructive/10 border-destructive/20 text-destructive"}`}>
                  {actionStatus.daemon.message}
                </div>
              )}
              <pre className="p-4 bg-zinc-950 text-emerald-400 rounded-lg overflow-x-auto text-xs font-mono h-96 overflow-y-auto border border-zinc-800 shadow-inner whitespace-pre-wrap">
                {logs}
              </pre>
            </CardContent>
          </Card>

        </div>

        {/* RIGHT COLUMN: DANGER ZONE & ACTIONS */}
        <div className="space-y-8">
          
          {/* DATA MANAGEMENT */}
          <Card className="border border-border/80 shadow-md">
            <CardHeader>
              <CardTitle className="text-xl font-bold">Maintenance Actions</CardTitle>
              <CardDescription>Clear specific subsets of trading framework data.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              
              {/* Clear Backtests */}
              <div className="space-y-3 pb-5 border-b border-border/50">
                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <h4 className="font-semibold text-sm">Clear Backtests</h4>
                    <p className="text-xs text-muted-foreground">Purge runs, trades, and curves.</p>
                  </div>
                  <Button onClick={handleClearBacktests} variant="outline" size="sm" className="text-destructive hover:bg-destructive/5 gap-1.5" disabled={actionStatus.backtests.loading}>
                    <Trash2 className="h-3.5 w-3.5" /> Clear
                  </Button>
                </div>
                {actionStatus.backtests.message && (
                  <p className={`text-xs ${actionStatus.backtests.success ? "text-green-500 font-semibold" : "text-destructive"}`}>
                    {actionStatus.backtests.message}
                  </p>
                )}
              </div>

              {/* Clear Deployments */}
              <div className="space-y-3 pb-5 border-b border-border/50">
                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <h4 className="font-semibold text-sm">Clear Deployments</h4>
                    <p className="text-xs text-muted-foreground">Purge live bots and events.</p>
                  </div>
                  <Button onClick={handleClearDeployments} variant="outline" size="sm" className="text-destructive hover:bg-destructive/5 gap-1.5" disabled={actionStatus.deployments.loading}>
                    <Trash2 className="h-3.5 w-3.5" /> Clear
                  </Button>
                </div>
                {actionStatus.deployments.message && (
                  <p className={`text-xs ${actionStatus.deployments.success ? "text-green-500 font-semibold" : "text-destructive"}`}>
                    {actionStatus.deployments.message}
                  </p>
                )}
              </div>

              {/* Reset/Re-seed Tasks */}
              <div className="space-y-3 pb-2">
                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <h4 className="font-semibold text-sm">Re-seed Background Tasks</h4>
                    <p className="text-xs text-muted-foreground">Reset to default schedule lists.</p>
                  </div>
                  <Button onClick={handleSeedTasks} variant="outline" size="sm" className="gap-1.5" disabled={actionStatus.tasks.loading}>
                    <RefreshCw className="h-3.5 w-3.5" /> Reset Tasks
                  </Button>
                </div>
                {actionStatus.tasks.message && (
                  <p className={`text-xs ${actionStatus.tasks.success ? "text-green-500 font-semibold" : "text-destructive"}`}>
                    {actionStatus.tasks.message}
                  </p>
                )}
              </div>

            </CardContent>
          </Card>

          {/* DANGER ZONE (FACTORY RESET) */}
          <Card className="border border-red-500/20 bg-red-500/[0.02] shadow-md">
            <CardHeader>
              <CardTitle className="text-xl font-bold text-red-500 flex items-center gap-2">
                <AlertTriangle className="h-5 w-5" /> Danger Zone
              </CardTitle>
              <CardDescription className="text-red-500/80">Cleans slate for a brand new user by resetting everything.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-xs text-muted-foreground leading-relaxed">
                A Master Factory Reset purges all tables, stops any active scheduler watchers, recreates default background tasks, and purges all reports CSV logs.
              </p>
              <Button onClick={handleFactoryReset} variant="destructive" className="w-full font-bold gap-2" disabled={actionStatus.reset.loading}>
                <Trash2 className="h-4 w-4" /> Master Factory Reset
              </Button>
              {actionStatus.reset.message && (
                <div className={`p-3 text-xs rounded border ${actionStatus.reset.success ? "bg-green-500/10 border-green-500/20 text-green-600 font-semibold" : "bg-destructive/10 border-destructive/20 text-destructive"}`}>
                  {actionStatus.reset.message}
                </div>
              )}
            </CardContent>
          </Card>

        </div>

      </div>
    </div>
  );
}
