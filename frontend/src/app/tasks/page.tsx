"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { fetchTasks, toggleTask, runTask, editTask, deleteTask, createTask, fetchTaskCatalog, fetchTaskLogs, actionAllTasks } from "@/lib/api";
import { Input } from "@/components/ui/input";

export default function TasksPage() {
  const [tasks, setTasks] = useState<any[]>([]);
  const [catalog, setCatalog] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  
  const [openNew, setOpenNew] = useState(false);
  const [newTask, setNewTask] = useState({ name: "", script: "", interval: 900, desc: "" });
  const [newParamsStr, setNewParamsStr] = useState("{}");

  const [openEdit, setOpenEdit] = useState(false);
  const [editId, setEditId] = useState("");
  const [editParams, setEditParams] = useState("{}");
  
  const [openLogs, setOpenLogs] = useState(false);
  const [logs, setLogs] = useState<string>("");
  const [logTaskName, setLogTaskName] = useState("");

  async function load() {
    setLoading(true);
    const res = await fetchTasks();
    setTasks(res);
    const cat = await fetchTaskCatalog();
    setCatalog(cat);
    setLoading(false);
  }

  useEffect(() => {
    load();
  }, []);

  async function handleToggle(id: string) {
    await toggleTask(id);
    await load();
  }

  async function handleRun(id: string) {
    await runTask(id);
    await load();
  }

  async function handleCreate() {
    let parsed = {};
    try {
      parsed = JSON.parse(newParamsStr);
    } catch(e) {
      alert("Invalid JSON params");
      return;
    }
    if (!newTask.name) newTask.name = newTask.script.replace(".py", "") + "_" + Math.floor(Math.random()*1000);
    try {
      await createTask({ ...newTask, params: parsed });
      setOpenNew(false);
      load();
    } catch (e: any) {
      alert("Failed to create task: " + e.message);
    }
  }

  async function handleEdit() {
    try {
      await editTask(editId, JSON.parse(editParams));
      setOpenEdit(false);
      load();
    } catch (e) {
      alert("Invalid JSON params");
    }
  }

  async function handleDelete(id: string) {
    if (confirm("Are you sure you want to delete this task?")) {
      await deleteTask(id);
      load();
    }
  }
  
  async function handleViewLogs(id: string, name: string) {
    setLogs("Loading...");
    setLogTaskName(name);
    setOpenLogs(true);
    try {
      const res = await fetchTaskLogs(id);
      setLogs(res.logs || "No logs found.");
    } catch(e: any) {
      setLogs("Error: " + e.message);
    }
  }

  async function handleActionAll(action: 'pause-all'|'resume-all') {
    if (!confirm(`Are you sure you want to ${action}?`)) return;
    await actionAllTasks(action);
    load();
  }

  function handleDeployFromCatalog(catItem: any) {
    setNewTask({
      name: catItem.script.replace(".py", "") + "_" + Math.floor(Math.random()*1000),
      script: catItem.script.replace(".py", ""),
      interval: catItem.default_interval,
      desc: catItem.desc || ""
    });
    setNewParamsStr(JSON.stringify(catItem.params || {}, null, 2));
    setOpenNew(true);
  }

  // Group catalog by category
  const categorized: Record<string, any[]> = {};
  catalog.forEach(c => {
    const cat = c.category || "General";
    if (!categorized[cat]) categorized[cat] = [];
    categorized[cat].push(c);
  });

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      <div className="flex justify-between items-center">
        <h1 className="text-4xl font-bold tracking-tight">Background Tasks</h1>
        <div className="flex gap-4">
          <Button onClick={() => handleActionAll('pause-all')} variant="outline">Pause All</Button>
          <Button onClick={() => handleActionAll('resume-all')} variant="outline">Resume All</Button>
          <Button onClick={load} variant="outline" disabled={loading}>Refresh</Button>
          <Button onClick={() => {
            setNewTask({ name: "", script: "", interval: 900, desc: "" });
            setNewParamsStr("{}");
            setOpenNew(true);
          }}>New Custom Task</Button>
        </div>
      </div>

      <Dialog open={openNew} onOpenChange={setOpenNew}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>Add New Scheduled Task</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">Task Name</label>
                <Input value={newTask.name} onChange={e => setNewTask({...newTask, name: e.target.value})} placeholder="my_unique_task" />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Script File</label>
                <Input value={newTask.script} onChange={e => setNewTask({...newTask, script: e.target.value})} placeholder="anti_correlation_deployer" />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">Interval (Seconds)</label>
                <Input type="number" value={newTask.interval} onChange={e => setNewTask({...newTask, interval: Number(e.target.value)})} />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Description</label>
                <Input value={newTask.desc} onChange={e => setNewTask({...newTask, desc: e.target.value})} placeholder="Short info" />
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">JSON Parameters</label>
              <textarea 
                className="w-full h-32 p-3 font-mono text-sm bg-black text-green-400 rounded-md"
                value={newParamsStr}
                onChange={e => setNewParamsStr(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button onClick={handleCreate}>Create Task</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      
      <Dialog open={openLogs} onOpenChange={setOpenLogs}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>Logs for {logTaskName}</DialogTitle>
          </DialogHeader>
          <pre className="p-4 bg-black text-green-400 rounded-md overflow-x-auto text-xs font-mono whitespace-pre-wrap h-[500px] overflow-y-auto">
            {logs}
          </pre>
        </DialogContent>
      </Dialog>

      <Dialog open={openEdit} onOpenChange={setOpenEdit}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit Task Params (JSON)</DialogTitle>
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

      <Tabs defaultValue="active" className="w-full">
        <TabsList className="mb-4">
          <TabsTrigger value="active">Active Tasks</TabsTrigger>
          <TabsTrigger value="catalog">Task Catalog</TabsTrigger>
        </TabsList>
        
        <TabsContent value="active">
          <Card>
            <CardHeader>
              <CardTitle>Automated Jobs</CardTitle>
              <CardDescription>Manage background scheduler scripts</CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>ID</TableHead>
                    <TableHead>Name</TableHead>
                    <TableHead>Script</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Interval</TableHead>
                    <TableHead>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {tasks.map(t => (
                    <TableRow key={t.id}>
                      <TableCell className="font-medium">#{t.id}</TableCell>
                      <TableCell>{t.name}</TableCell>
                      <TableCell>{t.script}</TableCell>
                      <TableCell>
                        <Badge variant={t.status === 'running' ? 'default' : 'secondary'}>
                          {t.status}
                        </Badge>
                      </TableCell>
                      <TableCell>{t.interval_sec}s</TableCell>
                      <TableCell>
                        <div className="flex gap-2">
                          <Button size="sm" variant="outline" onClick={() => handleToggle(t.id)}>
                            {t.status === 'running' ? 'Pause' : 'Resume'}
                          </Button>
                          <Button size="sm" variant="secondary" onClick={() => handleRun(t.id)}>
                            Run Now
                          </Button>
                          <Button size="sm" variant="secondary" onClick={() => handleViewLogs(t.id, t.name)}>
                            Logs
                          </Button>
                          <Button size="sm" variant="secondary" onClick={() => { setEditId(t.id); setEditParams(t.params_json); setOpenEdit(true); }}>
                            Edit Params
                          </Button>
                          <Button size="sm" variant="destructive" onClick={() => handleDelete(t.id)}>
                            Delete
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                  {tasks.length === 0 && !loading && (
                    <TableRow>
                      <TableCell colSpan={6} className="text-center py-6 text-muted-foreground">
                        No background tasks configured.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>
        
        <TabsContent value="catalog">
          <div className="space-y-8">
            {Object.keys(categorized).map(cat => (
              <Card key={cat}>
                <CardHeader>
                  <CardTitle>{cat}</CardTitle>
                </CardHeader>
                <CardContent>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Name</TableHead>
                        <TableHead>Script</TableHead>
                        <TableHead>Description</TableHead>
                        <TableHead>Action</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {categorized[cat].map(c => (
                        <TableRow key={c.script}>
                          <TableCell className="font-medium">{c.name}</TableCell>
                          <TableCell className="text-muted-foreground">{c.script}</TableCell>
                          <TableCell>{c.desc}</TableCell>
                          <TableCell>
                            <Button size="sm" onClick={() => handleDeployFromCatalog(c)}>Deploy Task</Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
