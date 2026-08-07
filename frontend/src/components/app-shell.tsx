import { AlertTriangle, BrainCircuit, CalendarDays, CalendarClock, CheckCircle2, ClipboardCheck, Download, LayoutDashboard, LoaderCircle, MapPin, Menu, Settings, Upload, UserRound, Users, X } from "lucide-react"
import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { api, type LarkSyncStatus } from "@/lib/api"
import { cn } from "@/lib/utils"

export type View = "overview" | "payroll" | "sites" | "ai" | "daily" | "worker" | "schedule" | "workers" | "import" | "export" | "settings"
const groups: { label: string; items: { id: View; label: string; icon: typeof LayoutDashboard }[] }[] = [
  { label: "Check", items: [
    { id: "overview", label: "Overview", icon: LayoutDashboard }, { id: "payroll", label: "Payroll check", icon: ClipboardCheck }, { id: "sites", label: "Sites", icon: MapPin },
  ]},
  { label: "Record", items: [
    { id: "ai", label: "AI reading", icon: BrainCircuit }, { id: "daily", label: "Daily entry", icon: CalendarDays }, { id: "worker", label: "Worker entry", icon: UserRound },
  ]},
  { label: "Plan", items: [
    { id: "schedule", label: "Schedule", icon: CalendarClock },
  ]},
  { label: "Data", items: [
    { id: "workers", label: "Workers", icon: Users }, { id: "import", label: "Import", icon: Upload }, { id: "export", label: "Export", icon: Download },
  ]},
  { label: "Account", items: [
    { id: "settings", label: "Settings & access", icon: Settings },
  ]},
]
const allItems = groups.flatMap(g => g.items)

export function AppShell({ view, setView, children }: { view: View; setView: (v: View) => void; children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  const [sync, setSync] = useState<LarkSyncStatus | null>(null)
  const [canEnter, setCanEnter] = useState<boolean | null>(null)
  const [canManageSchedule, setCanManageSchedule] = useState<boolean | null>(null)
  const [pendingAccess, setPendingAccess] = useState(0)
  useEffect(() => {
    const update = (event: Event) => setSync((event as CustomEvent<LarkSyncStatus>).detail)
    addEventListener("speed-lark-sync", update)
    return () => removeEventListener("speed-lark-sync", update)
  }, [])
  useEffect(() => {
    const apply = (value: any) => {
      setCanEnter(Boolean(value?.permissions?.can_enter))
      setCanManageSchedule(Boolean(value?.permissions?.can_manage_schedule))
      setPendingAccess(Array.isArray(value?.pending_requests) ? value.pending_requests.length : 0)
    }
    void api<any>("/api/settings/access").then(apply).catch(() => setCanEnter(null))
    const changed = (event: Event) => apply((event as CustomEvent).detail)
    addEventListener("speed-permissions-changed", changed)
    return () => removeEventListener("speed-permissions-changed", changed)
  }, [])
  const visibleGroups = groups
    .map(group => ({
      ...group,
      items: group.label === "Record" && canEnter === false ? [] : group.items,
    }))
    .map(group => ({
      ...group,
      items: group.label === "Plan" && canManageSchedule !== true ? [] : group.items,
    }))
    .filter(group => group.items.length)
  const visibleItems = visibleGroups.flatMap(group => group.items)
  useEffect(() => {
    if (canEnter === false && (["ai", "daily", "worker"] as View[]).includes(view)) {
      setView("settings")
    }
    if (canManageSchedule === false && view === "schedule") setView("settings")
  }, [canEnter, canManageSchedule, view, setView])
  const active = allItems.find(i => i.id === view)!
  const navigate = (id: View) => { setView(id); setOpen(false); window.scrollTo({ top: 0, behavior: "smooth" }) }
  const syncLabel = !sync || sync.phase === "disabled"
    ? "Shared database connected"
    : sync.phase === "syncing"
      ? "Syncing Lark…"
      : sync.phase === "synced"
        ? "AWS and Lark synced"
        : "Saved · Lark sync pending"
  const SyncIcon = sync?.phase === "syncing"
    ? LoaderCircle
    : sync?.phase === "pending" || sync?.phase === "error"
      ? AlertTriangle
      : CheckCircle2
  return <div className="app-grid">
    <aside className={cn("sidebar", open && "!flex !fixed inset-y-0 left-0 w-[270px]")}>
      <div className="mb-7 flex items-center gap-3 px-2">
        <img className="brand-logo" src="/logo.png" onError={e => { e.currentTarget.style.display = "none" }} />
        <div><strong className="block text-sm">Speed Construction</strong><span className="text-[11px] text-[#a9c8f3]">Worker Schedule</span></div>
        {open && <Button variant="ghost" size="icon" className="ml-auto text-white" onClick={() => setOpen(false)}><X className="size-5" /></Button>}
      </div>
      <nav className="flex-1 overflow-y-auto">
        {visibleGroups.map(group => <div key={group.label}><div className="nav-heading">{group.label}</div>{group.items.map(item => <button className={cn("nav-item", view === item.id && "active")} onClick={() => navigate(item.id)} key={item.id}><item.icon className="size-[17px]" /><span>{item.label}</span>{item.id === "settings" && pendingAccess > 0 && <span className="ml-auto rounded-full bg-amber-400 px-2 py-0.5 text-[10px] font-bold text-slate-950">{pendingAccess}</span>}</button>)}</div>)}
      </nav>
      <p className="mt-4 px-2 text-[10px] text-[#7fa6d8]">Developed by Zihao (Paul) Zhao</p>
    </aside>
    <main className="main">
      <header className="topbar"><div className="flex items-center gap-3"><Button className="md:hidden" variant="ghost" size="icon" onClick={() => setOpen(true)}><Menu className="size-5" /></Button><active.icon className="size-5 text-primary" /><span className="font-semibold">{active.label}</span></div><div className="hidden items-center gap-2 text-xs text-muted-foreground sm:flex"><SyncIcon className={cn("size-4", sync?.phase === "syncing" && "animate-spin", (sync?.phase === "pending" || sync?.phase === "error") && "text-amber-600", sync?.phase === "synced" && "text-emerald-700")} />{syncLabel}</div></header>
      {children}
    </main>
    <nav className="mobile-nav safe-bottom">{visibleItems.slice(0, 6).map(item => <button key={item.id} onClick={() => navigate(item.id)} className={view === item.id ? "active" : ""}><item.icon className="size-[18px]" /><span>{item.label.replace(" entry", "")}</span></button>)}</nav>
  </div>
}
