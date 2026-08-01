const API_URL = typeof window !== 'undefined' ? '/api' : 'http://127.0.0.1:8000/api';

export async function fetchDeployments() {
  try {
    const res = await fetch(`${API_URL}/deployments`, { cache: 'no-store' });
    if (!res.ok) return [];
    const data = await res.json();
    return data.rows || [];
  } catch (e) {
    return [];
  }
}

export async function fetchRuns() {
  try {
    const res = await fetch(`${API_URL}/runs`, { cache: 'no-store' });
    if (!res.ok) return [];
    const data = await res.json();
    return data.rows || [];
  } catch (e) {
    return [];
  }
}

export async function fetchSchedulerStatus() {
  try {
    const res = await fetch(`${API_URL}/scheduler/status`, { cache: 'no-store' });
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    return null;
  }
}

export async function actionDeployment(id: string | number, action: 'pause' | 'resume' | 'stop' | 'delete') {
  const res = await fetch(`${API_URL}/deployments/${id}/${action}`, {
    method: 'POST',
  });
  return res.json();
}

export async function scanMarket(params: any) {
  const res = await fetch(`${API_URL}/scan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params)
  });
  return res.json();
}

export async function fetchPnlSummary() {
  try {
    const res = await fetch(`${API_URL}/pnl/summary`, { cache: 'no-store' });
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    return null;
  }
}

export async function fetchSchedulerLogs() {
  try {
    const res = await fetch(`${API_URL}/scheduler/logs`, { cache: 'no-store' });
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    return null;
  }
}

export async function restartScheduler() {
  const res = await fetch(`${API_URL}/scheduler/restart`, { method: 'POST' });
  return res.json();
}

export async function fetchSymbols() {
  const res = await fetch(`${API_URL}/symbols`, { cache: 'no-store' });
  if (!res.ok) return [];
  return res.json();
}

export async function fetchStrategies() {
  const res = await fetch(`${API_URL}/strategies`, { cache: 'no-store' });
  if (!res.ok) return [];
  return res.json();
}

export async function fetchTasks() {
  try {
    const res = await fetch(`${API_URL}/tasks`, { cache: 'no-store' });
    if (!res.ok) return [];
    return await res.json();
  } catch (e) {
    return [];
  }
}

export async function toggleTask(taskId: string) {
  const res = await fetch(`${API_URL}/tasks/${taskId}/toggle`, { method: 'POST' });
  return res.json();
}

export async function runTask(taskId: string) {
  const res = await fetch(`${API_URL}/tasks/${taskId}/run`, { method: 'POST' });
  return res.json();
}

export async function fetchRunSummary(runId: string) {
  try {
    const res = await fetch(`${API_URL}/runs/${runId}/summary`, { cache: 'no-store' });
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    return null;
  }
}

export async function fetchDeploymentEvents(depId: string) {
  try {
    const res = await fetch(`${API_URL}/deployments/${depId}/events`, { cache: 'no-store' });
    if (!res.ok) return [];
    return await res.json();
  } catch (e) {
    return [];
  }
}

export async function createBacktest(data: any) {
  const res = await fetch(`${API_URL}/backtest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createDeployment(data: any) {
  const res = await fetch(`${API_URL}/deployments/create`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function editDeployment(id: string | number, data: any) {
  const res = await fetch(`${API_URL}/deployments/${id}/edit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  return res.json();
}

export async function testTradeDeployment(id: string | number) {
  const res = await fetch(`${API_URL}/deployments/${id}/test_trade`, {
    method: 'POST'
  });
  return res.json();
}

export async function createTask(params: any) {
  const res = await fetch(`${API_URL}/tasks/create`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params)
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function editTask(id: string, params: any) {
  const res = await fetch(`${API_URL}/tasks/${id}/edit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params)
  });
  return res.json();
}

export async function deleteTask(id: string) {
  const res = await fetch(`${API_URL}/tasks/${id}/delete`, {
    method: 'POST'
  });
  return res.json();
}

export async function fetchSettings() {
  try {
    const res = await fetch(`${API_URL}/settings`, { cache: 'no-store' });
    if (!res.ok) return {};
    return await res.json();
  } catch (e) {
    return {};
  }
}

export async function updateSettings(data: any) {
  const res = await fetch(`${API_URL}/settings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  return res.json();
}

export async function fetchTaskCatalog() {
  const res = await fetch(`${API_URL}/tasks/catalog`, { cache: 'no-store' });
  if (!res.ok) return [];
  return res.json();
}

export async function fetchTaskLogs(id: string | number) {
  const res = await fetch(`${API_URL}/tasks/${id}/logs`, { cache: 'no-store' });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function actionAllTasks(action: 'pause-all' | 'resume-all') {
  const res = await fetch(`${API_URL}/tasks/action_all?action=${action}`, {
    method: 'POST'
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function fetchDeploymentLogs(id: string | number) {
  const res = await fetch(`${API_URL}/deployments/${id}/logs`, { cache: 'no-store' });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
