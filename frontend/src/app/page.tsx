import { fetchDeployments, fetchRuns, fetchSchedulerStatus } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export default async function Dashboard() {
  const [deployments, runs, scheduler] = await Promise.all([
    fetchDeployments(),
    fetchRuns(),
    fetchSchedulerStatus()
  ]);

  const activeBots = deployments.filter((d: any) => d.status === "running");
  
  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      <div className="flex justify-between items-center">
        <h1 className="text-4xl font-bold tracking-tight">Delta-BT Dashboard</h1>
        <div className="flex items-center gap-3">
          <Badge variant={scheduler?.alive ? "default" : "destructive"}>
            Scheduler {scheduler?.alive ? "Alive" : "Dead"}
          </Badge>
          <span className="text-sm text-muted-foreground">
            Heartbeat: {scheduler?.heartbeat_age_sec?.toFixed(1) || "-"}s ago
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Active Deployments</CardDescription>
            <CardTitle className="text-4xl">{activeBots.length}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-sm text-muted-foreground">Out of {deployments.length} total</div>
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Total Backtests</CardDescription>
            <CardTitle className="text-4xl">{runs.length}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-sm text-muted-foreground">Historical runs</div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Recent Deployments</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Strategy</TableHead>
                <TableHead>Symbol</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Venue</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {deployments.slice(0, 5).map((dep: any) => (
                <TableRow key={dep.id}>
                  <TableCell className="font-medium">{dep.name}</TableCell>
                  <TableCell>{dep.strategy}</TableCell>
                  <TableCell>{dep.symbol}</TableCell>
                  <TableCell>
                    <Badge variant={dep.status === 'running' ? 'default' : 'secondary'}>
                      {dep.status}
                    </Badge>
                  </TableCell>
                  <TableCell>{dep.venue}</TableCell>
                </TableRow>
              ))}
              {deployments.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-muted-foreground py-6">
                    No deployments found. Start a bot via CLI or API.
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
