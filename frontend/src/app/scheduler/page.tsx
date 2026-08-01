"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fetchSchedulerStatus, fetchSchedulerLogs, restartScheduler, fetchSettings, updateSettings } from "@/lib/api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export default function SchedulerPage() {
  const [status, setStatus] = useState<any>(null);
  const [logs, setLogs] = useState<string>("");
  const [settings, setSettings] = useState<any>({});
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    const [stat, logData, sets] = await Promise.all([
      fetchSchedulerStatus(),
      fetchSchedulerLogs(),
      fetchSettings()
    ]);
    setStatus(stat);
    setLogs(logData?.logs || "No logs available.");
    setSettings(sets);
    setLoading(false);
  }

  useEffect(() => {
    load();
    const interval = setInterval(load, 10000); // Auto-refresh every 10s
    return () => clearInterval(interval);
  }, []);

  async function handleRestart() {
    setLoading(true);
    await restartScheduler();
    setTimeout(load, 2000); // wait for restart
  }

  async function handleSaveSettings() {
    setLoading(true);
    await updateSettings(settings);
    load();
  }

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      <div className="flex justify-between items-center">
        <h1 className="text-4xl font-bold tracking-tight">System Scheduler</h1>
        <div className="flex gap-4">
          <Button onClick={load} variant="outline" disabled={loading}>Refresh</Button>
          <Button onClick={handleRestart} variant="destructive" disabled={loading}>Restart Daemon</Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-3">
            Scheduler Status
            <Badge variant={status?.alive ? "default" : "destructive"}>
              {status?.alive ? "Alive" : "Dead"}
            </Badge>
          </CardTitle>
          <CardDescription>Background process responsible for tick processing and CRON jobs.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
            <div>
              <p className="text-sm text-muted-foreground">Heartbeat Age</p>
              <p className="font-medium">{status?.heartbeat_age_sec?.toFixed(1) || "-"}s</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Threshold</p>
              <p className="font-medium">{status?.threshold_sec || "-"}s</p>
            </div>
          </div>
        </CardContent>
      </Card>

      <Tabs defaultValue="logs">
        <TabsList>
          <TabsTrigger value="logs">Live Logs</TabsTrigger>
          <TabsTrigger value="settings">Configuration</TabsTrigger>
        </TabsList>
        <TabsContent value="logs">
          <Card>
            <CardHeader>
              <CardTitle>Live Logs (watcher.log)</CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="p-4 bg-black text-green-400 rounded-md overflow-x-auto text-xs font-mono whitespace-pre-wrap h-96 overflow-y-auto">
                {logs}
              </pre>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="settings">
          <Card>
            <CardHeader>
              <CardTitle>Scheduler Configuration</CardTitle>
              <CardDescription>Global App Settings (app_settings table)</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {Object.keys(settings).length === 0 && <p className="text-muted-foreground text-sm">No settings found.</p>}
              {Object.keys(settings).map(key => (
                <div key={key} className="space-y-2">
                  <label className="text-sm font-medium">{key}</label>
                  <textarea
                    className="w-full p-2 font-mono text-sm bg-black text-green-400 rounded-md border"
                    value={JSON.stringify(settings[key], null, 2)}
                    onChange={(e) => {
                      try {
                        const val = JSON.parse(e.target.value);
                        setSettings({...settings, [key]: val});
                      } catch(err) {
                        // ignore unparseable json during typing
                      }
                    }}
                  />
                </div>
              ))}
              <Button onClick={handleSaveSettings}>Save Configuration</Button>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
