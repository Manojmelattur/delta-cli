"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  PieChart,
  Rocket,
  History,
  Radar,
  Clock,
  ListTodo,
  PanelLeftClose,
  PanelLeftOpen
} from "lucide-react";
import { Button } from "./ui/button";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/dashboard", label: "PnL Dashboard", icon: PieChart },
  { href: "/pnl", label: "PnL Analytics", icon: PieChart },
  { href: "/deployments", label: "Deployments", icon: Rocket },
  { href: "/backtests", label: "Backtests", icon: History },
  { href: "/scan", label: "Market Scanner", icon: Radar },
  { href: "/scheduler", label: "Scheduler", icon: Clock },
  { href: "/tasks", label: "Tasks", icon: ListTodo },
];

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const pathname = usePathname();

  return (
    <aside 
      className={`border-r border-border bg-sidebar flex-shrink-0 flex flex-col transition-all duration-300 ease-in-out ${
        collapsed ? "w-[72px]" : "w-64"
      }`}
    >
      <div className="flex items-center justify-between p-4 h-[72px] border-b border-border/50">
        {!collapsed && <div className="font-bold text-xl tracking-tight overflow-hidden whitespace-nowrap">Delta-BT</div>}
        <Button 
          variant="ghost" 
          size="icon" 
          onClick={() => setCollapsed(!collapsed)}
          className={`shrink-0 ${collapsed ? "mx-auto" : ""}`}
        >
          {collapsed ? <PanelLeftOpen className="h-5 w-5" /> : <PanelLeftClose className="h-5 w-5" />}
        </Button>
      </div>
      
      <nav className="flex-1 space-y-1 p-3 overflow-y-auto overflow-x-hidden">
        {NAV_ITEMS.map((item) => {
          const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
          return (
            <Link 
              key={item.href} 
              href={item.href}
              className={`flex items-center gap-3 p-3 rounded-md transition-colors font-medium ${
                isActive 
                  ? "bg-primary/10 text-primary" 
                  : "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground text-muted-foreground"
              } ${collapsed ? "justify-center" : "justify-start"}`}
              title={collapsed ? item.label : undefined}
            >
              <item.icon className="h-5 w-5 shrink-0" />
              {!collapsed && <span className="whitespace-nowrap">{item.label}</span>}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
