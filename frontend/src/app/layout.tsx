import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Delta-BT | Algorithmic Trading",
  description: "Web Dashboard for Delta-BT algorithmic trading framework",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} dark h-full antialiased`}
    >
      <body className="min-h-full flex text-sm">
        <aside className="w-64 border-r border-border bg-sidebar flex-shrink-0 flex flex-col p-6">
          <div className="font-bold text-xl tracking-tight mb-8">Delta-BT</div>
          <nav className="space-y-2 flex-1">
            <a href="/" className="block p-3 rounded-md hover:bg-sidebar-accent hover:text-sidebar-accent-foreground font-medium transition-colors">Dashboard</a>
            <a href="/pnl" className="block p-3 rounded-md hover:bg-sidebar-accent hover:text-sidebar-accent-foreground font-medium transition-colors">PnL Analytics</a>
            <a href="/deployments" className="block p-3 rounded-md hover:bg-sidebar-accent hover:text-sidebar-accent-foreground font-medium transition-colors">Deployments</a>
            <a href="/backtests" className="block p-3 rounded-md hover:bg-sidebar-accent hover:text-sidebar-accent-foreground font-medium transition-colors">Backtests</a>
            <a href="/scan" className="block p-3 rounded-md hover:bg-sidebar-accent hover:text-sidebar-accent-foreground font-medium transition-colors">Market Scanner</a>
            <a href="/scheduler" className="block p-3 rounded-md hover:bg-sidebar-accent hover:text-sidebar-accent-foreground font-medium transition-colors">Scheduler</a>
            <a href="/tasks" className="block p-3 rounded-md hover:bg-sidebar-accent hover:text-sidebar-accent-foreground font-medium transition-colors">Tasks</a>
          </nav>
        </aside>
        <main className="flex-1 overflow-y-auto">
          {children}
        </main>
      </body>
    </html>
  );
}
