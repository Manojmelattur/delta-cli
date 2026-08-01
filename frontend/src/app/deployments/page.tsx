"use client";

import { useEffect, useState } from "react";
import { fetchDeployments, actionDeployment, editDeployment, testTradeDeployment, fetchDeploymentLogs } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";

import { Input } from "@/components/ui/input";
export default function DeploymentsPage() {
  const [deployments, setDeployments] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  
  const [openNew, setOpenNew] = useState(false);
  const [newDep, setNewDep] = useState({ 
    name: "", venue: "paper", strategy: "time_breakout", symbol: "BTC-USDT", timeframe: "15m", 
    lot: 1.0, sl_pct: 0.0, tp_pct: 0.0, trail_pct: 0.0 
  });
  const [newParamsStr, setNewParamsStr] = useState("{}");

  const [openEdit, setOpenEdit] = useState(false);
  const [editId, setEditId] = useState("");
  const [editParams, setEditParams] = useState("{}");
  
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

  async function handleEdit() {
    try {
      await editDeployment(editId, JSON.parse(editParams));
      setOpenEdit(false);
      load();
    } catch(e) {
      alert("Invalid JSON format");
    }
  }

  async function handleCreate() {
    let parsedParams = {};
    try {
      parsedParams = JSON.parse(newParamsStr);
    } catch (e) {
      alert("Invalid JSON format");
      return;
    }
    try {
      const { createDeployment } = await import("@/lib/api");
      if (!newDep.name) newDep.name = newDep.strategy + "_" + newDep.symbol + "_" + Math.floor(Math.random()*1000);
      await createDeployment({ ...newDep, params: parsedParams });
      setOpenNew(false);
      load();
    } catch(e: any) {
      alert("Error: " + e.message);
    }
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
          <Button onClick={() => setOpenNew(true)}>New Deployment</Button>
        </div>
      </div>

      <Dialog open={openNew} onOpenChange={setOpenNew}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Deploy New Live Bot</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Deployment Name</label>
              <Input value={newDep.name} onChange={(e: any) => setNewDep({...newDep, name: e.target.value})} placeholder="Auto-generated if empty" />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">Strategy</label>
                <select className="flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm" value={newDep.strategy} onChange={e => setNewDep({...newDep, strategy: e.target.value})}>
                  {strategies.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Symbol</label>
                <select className="flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm" value={newDep.symbol} onChange={e => setNewDep({...newDep, symbol: e.target.value})}>
                  {symbols.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">Timeframe</label>
                <Input value={newDep.timeframe} onChange={(e: any) => setNewDep({...newDep, timeframe: e.target.value})} />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Venue</label>
                <select className="flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm" value={newDep.venue} onChange={e => setNewDep({...newDep, venue: e.target.value})}>
                  <option value="paper">Paper Trading</option>
                  <option value="binance">Binance (Live)</option>
                  <option value="bybit">Bybit (Live)</option>
                </select>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Position Lot (Qty)</label>
                <Input type="number" step="0.1" value={newDep.lot} onChange={(e: any) => setNewDep({...newDep, lot: Number(e.target.value)})} />
              </div>
            </div>
            
            <h3 className="font-semibold text-lg border-b pb-2 pt-4">Risk Management</h3>
            <div className="grid grid-cols-3 gap-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">Stop Loss %</label>
                <Input type="number" step="0.1" value={newDep.sl_pct} onChange={(e: any) => setNewDep({...newDep, sl_pct: Number(e.target.value)})} />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Take Profit %</label>
                <Input type="number" step="0.1" value={newDep.tp_pct} onChange={(e: any) => setNewDep({...newDep, tp_pct: Number(e.target.value)})} />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Trailing Stop %</label>
                <Input type="number" step="0.1" value={newDep.trail_pct} onChange={(e: any) => setNewDep({...newDep, trail_pct: Number(e.target.value)})} />
              </div>
            </div>
            
            <h3 className="font-semibold text-lg border-b pb-2 pt-4">Strategy Parameters</h3>
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">JSON overrides (e.g. <code>{`{"ema_fast": 9, "ema_slow": 21}`}</code>)</p>
              <textarea 
                className="w-full h-24 p-3 font-mono text-sm bg-black text-green-400 rounded-md"
                value={newParamsStr}
                onChange={e => setNewParamsStr(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button onClick={handleCreate}>Deploy Bot</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={openEdit} onOpenChange={setOpenEdit}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit Strategy Params (JSON)</DialogTitle>
          </DialogHeader>
          <textarea 
            className="w-full h-64 p-3 font-mono text-sm bg-black text-green-400 rounded-md mt-4"
            value={editParams}
            onChange={e => setEditParams(e.target.value)}
          />
          <DialogFooter>
            <Button onClick={handleEdit}>Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      
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
                    <TableCell className={l.pnl > 0 ? 'text-green-500' : l.pnl < 0 ? 'text-red-500' : ''}>
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
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Strategy</TableHead>
                <TableHead>Symbol</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {deployments.map(dep => (
                <TableRow key={dep.id}>
                  <TableCell className="font-medium">#{dep.id}</TableCell>
                  <TableCell>{dep.name}</TableCell>
                  <TableCell>{dep.strategy}</TableCell>
                  <TableCell>{dep.symbol}</TableCell>
                  <TableCell>
                    <Badge variant={dep.status === 'running' ? 'default' : 'secondary'}>
                      {dep.status}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-2 flex-wrap">
                      <Button size="sm" variant="outline" onClick={() => handleAction(dep.id, dep.status === 'active' || dep.status === 'running' ? 'pause' : 'resume')}>
                        {dep.status === 'active' || dep.status === 'running' ? 'Pause' : 'Resume'}
                      </Button>
                      <Button size="sm" variant="secondary" onClick={() => { setEditId(dep.id); setEditParams(dep.params_json); setOpenEdit(true); }}>
                        Edit
                      </Button>
                      <Button size="sm" variant="secondary" onClick={() => handleTestTrade(dep.id)}>
                        Test Trade
                      </Button>
                      <Button size="sm" variant="secondary" onClick={() => handleViewLogs(dep.id)}>
                        Events
                      </Button>
                      {dep.status === 'stopped' ? (
                        <Button size="sm" variant="destructive" onClick={() => handleAction(dep.id, 'delete')}>
                          Delete
                        </Button>
                      ) : (
                        <Button size="sm" variant="destructive" onClick={() => handleAction(dep.id, 'stop')}>
                          Stop
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
              {deployments.length === 0 && !loading && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground py-6">
                    No active deployments.
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
