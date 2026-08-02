"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { use } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardFooter, CardDescription } from "@/components/ui/card";
import { editDeployment, fetchDeployments } from "@/lib/api";

export default function EditDeploymentPage({ params }: { params: Promise<{ id: string }> }) {
  const router = useRouter();
  const { id } = use(params);
  
  const [editDep, setEditDep] = useState({ lot: 1.0, sl_pct: 0.0, tp_pct: 0.0, trail_pct: 0.0 });
  const [editParamsStr, setEditParamsStr] = useState("{}");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const deployments = await fetchDeployments();
        const dep = deployments.find((d: any) => d.id.toString() === id);
        if (dep) {
          setEditDep({
            lot: dep.size ?? 1.0,
            sl_pct: dep.sl_pct ?? 0.0,
            tp_pct: dep.tp_pct ?? 0.0,
            trail_pct: dep.trail_pct ?? 0.0
          });
          
          let pStr = dep.params_json ?? '{}';
          // Ensure requested risk features exist in the JSON
          try {
            const p = JSON.parse(pStr);
            if (p.use_kelly_sizer === undefined) {
              p.use_kelly_sizer = true;
              p.kelly_fraction = 0.5;
            }
            if (p.use_maker_limit === undefined) {
              p.use_maker_limit = true;
              p.maker_limit_offset_bps = 5;
            }
            if (p.use_atr_risk === undefined) {
              p.use_atr_risk = true;
              p.atr_multiplier = 2.0;
            }
            if (p.risk_type === undefined) p.risk_type = "percentage";
            if (p.multiple_tp === undefined) {
              p.multiple_tp = true;
              p.tp_levels = p.tp_levels || [
                { price_pct: 1.5, qty_pct: 50 },
                { price_pct: 3.0, qty_pct: 50 }
              ];
            }
            if (p.multiple_sl === undefined) {
              p.multiple_sl = true;
              p.sl_levels = p.sl_levels || [
                { price_pct: -1.0, qty_pct: 50 },
                { price_pct: -2.0, qty_pct: 50 }
              ];
            }
            if (p.multiple_tsl === undefined) {
              p.multiple_tsl = true;
              p.tsl_levels = p.tsl_levels || [
                { activation_pct: 1.0, trail_pct: 0.5, qty_pct: 50 },
                { activation_pct: 2.0, trail_pct: 1.0, qty_pct: 50 }
              ];
            }
            pStr = JSON.stringify(p, null, 2);
          } catch {}
          setEditParamsStr(pStr);
        }
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [id]);

  async function handleEdit() {
    try {
      await editDeployment(id, {
        params: JSON.parse(editParamsStr),
        size: editDep.lot,
        sl_pct: editDep.sl_pct,
        tp_pct: editDep.tp_pct,
        trail_pct: editDep.trail_pct
      });
      router.push("/deployments");
    } catch(e: any) {
      alert("Invalid JSON format or network error: " + e.message);
    }
  }

  if (loading) {
    return <div className="p-8 text-muted-foreground">Loading...</div>;
  }

  return (
    <div className="p-8 max-w-4xl mx-auto space-y-8">
      <div className="flex items-center gap-4">
        <Button variant="outline" onClick={() => router.push("/deployments")}>← Back</Button>
        <h1 className="text-4xl font-bold tracking-tight">Edit Deployment #{id}</h1>
      </div>

      <Card>
        <CardContent className="space-y-6 pt-6">
          <div className="space-y-4">
            <h3 className="font-semibold text-sm text-muted-foreground uppercase tracking-wider">Settings & Risk</h3>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">Position Lot</label>
                <Input type="number" step="0.1" value={editDep.lot} onChange={(e) => setEditDep({...editDep, lot: Number(e.target.value)})} />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Stop Loss %</label>
                <Input type="number" step="0.1" value={editDep.sl_pct} onChange={(e) => setEditDep({...editDep, sl_pct: Number(e.target.value)})} />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Take Profit %</label>
                <Input type="number" step="0.1" value={editDep.tp_pct} onChange={(e) => setEditDep({...editDep, tp_pct: Number(e.target.value)})} />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Trailing %</label>
                <Input type="number" step="0.1" value={editDep.trail_pct} onChange={(e) => setEditDep({...editDep, trail_pct: Number(e.target.value)})} />
              </div>
            </div>
          </div>
          <div className="space-y-4">
            <div className="flex justify-between items-center">
              <h3 className="font-semibold text-sm text-muted-foreground uppercase tracking-wider">Strategy Params & Advanced Risk</h3>
              <span className="text-[10px] text-muted-foreground">JSON Overrides</span>
            </div>
            <textarea 
              className="w-full h-96 p-4 font-mono text-sm bg-black text-green-400 rounded-md border border-zinc-800 focus:outline-none focus:border-green-500 placeholder:text-zinc-600"
              value={editParamsStr}
              onChange={e => setEditParamsStr(e.target.value)}
              placeholder={`{
  "use_kelly_sizer": true,
  "kelly_fraction": 0.5,
  "use_maker_limit": true,
  "maker_limit_offset_bps": 5,
  "use_atr_risk": true,
  "atr_multiplier": 2.0,
  "risk_type": "percentage",
  "multiple_tp": true,
  "tp_levels": [
    { "price_pct": 1.5, "qty_pct": 50 },
    { "price_pct": 3.0, "qty_pct": 50 }
  ],
  "multiple_sl": true,
  "sl_levels": [
    { "price_pct": -1.0, "qty_pct": 50 },
    { "price_pct": -2.0, "qty_pct": 50 }
  ],
  "multiple_tsl": true,
  "tsl_levels": [
    { "activation_pct": 1.0, "trail_pct": 0.5, "qty_pct": 50 },
    { "activation_pct": 2.0, "trail_pct": 1.0, "qty_pct": 50 }
  ]
}`}
            />
          </div>
        </CardContent>
        <CardFooter className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => router.push("/deployments")}>Cancel</Button>
          <Button onClick={handleEdit}>Save Changes</Button>
        </CardFooter>
      </Card>
    </div>
  );
}
