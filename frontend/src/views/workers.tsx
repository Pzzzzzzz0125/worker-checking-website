import { useEffect, useMemo, useState } from "react"
import { Archive, ArchiveRestore, LoaderCircle, LockKeyhole, Pencil, Plus, Save, Search, ShieldCheck, UserCheck, Users } from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input, Textarea } from "@/components/ui/input"
import { api, postJSON } from "@/lib/api"
import { compactNumber, initials } from "@/lib/utils"

type WorkerProfile = {
  id: number
  worker_key: string
  name: string
  normalized_name: string
  worker_type: "W2" | "1099"
  active: boolean
  daily_rate: number
  display_order: number
  aliases: string
  notes: string
}

type WorkerResponse = {
  workers: WorkerProfile[]
  totals: { workers: number; active: number; archived: number; w2: number; contractors: number }
}

type WorkerAccess = {
  authorized: boolean
  access_type: "lark_admin" | "password" | ""
  password_configured: boolean
  admin_allowlist_configured: boolean
}

export function WorkersView({ onSaved }: { onSaved: () => void }) {
  const [data, setData] = useState<WorkerResponse | null>(null)
  const [search, setSearch] = useState("")
  const [status, setStatus] = useState<"active" | "archived">("active")
  const [draft, setDraft] = useState<WorkerProfile | null>(null)
  const [saving, setSaving] = useState(false)
  const [removing, setRemoving] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const [access, setAccess] = useState<WorkerAccess | null>(null)
  const [password, setPassword] = useState("")
  const [unlocking, setUnlocking] = useState(false)

  const load = async () => {
    try {
      setData(await api<WorkerResponse>("/api/workers"))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Unable to load workers")
    }
  }
  const checkAccess = async () => {
    try {
      const result = await api<WorkerAccess>("/api/workers/access")
      setAccess(result)
      if (result.authorized) await load()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Unable to check access")
    }
  }
  useEffect(() => { void checkAccess() }, [])

  const unlock = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!password) return
    setUnlocking(true)
    try {
      await postJSON("/api/workers/unlock", { password })
      setPassword("")
      await checkAccess()
      toast.success("Worker Management unlocked for 8 hours.")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Unable to unlock Worker Management")
    } finally {
      setUnlocking(false)
    }
  }

  const workers = useMemo(() => {
    const query = search.trim().toLowerCase()
    return (data?.workers || []).filter(worker => {
      if (status === "active" && !worker.active) return false
      if (status === "archived" && worker.active) return false
      return !query || [worker.name, worker.worker_key, worker.aliases, worker.worker_type]
        .some(value => String(value).toLowerCase().includes(query))
    }).sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }))
  }, [data, search, status])

  const save = async () => {
    if (!draft) return
    if (!draft.name.trim()) return toast.error("Worker name is required.")
    if (Number(draft.daily_rate) < 0) return toast.error("Daily rate cannot be negative.")
    setSaving(true)
    try {
      const result = await postJSON<{ saved: boolean; worker: WorkerProfile }>("/api/workers", draft)
      setDraft(null)
      await load()
      onSaved()
      toast.success(`${result.worker.name}'s worker profile was saved.`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Unable to save worker")
    } finally {
      setSaving(false)
    }
  }

  const addWorker = () => {
    const nextOrder = Math.max(
      0,
      ...(data?.workers || []).map(worker => Number(worker.display_order) || 0),
    ) + 1
    setDraft({
      id: 0,
      worker_key: "",
      name: "",
      normalized_name: "",
      worker_type: "W2",
      active: true,
      daily_rate: 0,
      display_order: nextOrder,
      aliases: "",
      notes: "",
    })
  }

  const remove = async () => {
    if (!draft?.worker_key) return
    const confirmed = window.confirm(
      `Archive ${draft.name}? The worker will disappear from entries and reports, but historical records will be preserved.`,
    )
    if (!confirmed) return
    setRemoving(true)
    try {
      const result = await postJSON<{ mode: "archived"; history_records: number }>(
        "/api/workers/delete",
        { worker_key: draft.worker_key },
      )
      setDraft(null)
      await load()
      onSaved()
      toast.success(`Worker archived. ${result.history_records} historical records were preserved.`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Unable to archive worker")
    } finally {
      setRemoving(false)
    }
  }

  const restore = async () => {
    if (!draft?.worker_key) return
    setRestoring(true)
    try {
      const result = await postJSON<{ restored: boolean; worker: WorkerProfile }>(
        "/api/workers/restore",
        { worker_key: draft.worker_key },
      )
      setDraft(null)
      setStatus("active")
      await load()
      onSaved()
      toast.success(`${result.worker.name} was restored and is available throughout the app.`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Unable to restore worker")
    } finally {
      setRestoring(false)
    }
  }

  if (!access) return <div className="page"><Card><CardContent className="flex items-center justify-center gap-3 py-20 text-sm text-muted-foreground"><LoaderCircle className="size-5 animate-spin" />Checking Worker Management access…</CardContent></Card></div>

  if (!access.authorized) return <div className="page">
    <div className="mx-auto max-w-lg py-10">
      <Card>
        <CardHeader>
          <span className="mb-2 grid size-12 place-items-center rounded-xl bg-blue-50 text-primary"><LockKeyhole className="size-6" /></span>
          <CardTitle>Worker Management is protected</CardTitle>
          <CardDescription>Only configured Lark administrators or users with the separate Worker Management password can view salary and classification data.</CardDescription>
        </CardHeader>
        <CardContent>
          {access.password_configured ? <form className="grid gap-3" onSubmit={unlock}>
            <label className="field-label">Management password<Input autoFocus type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} /></label>
            <Button type="submit" disabled={!password || unlocking}>{unlocking ? <LoaderCircle className="size-4 animate-spin" /> : <LockKeyhole className="size-4" />}{unlocking ? "Unlocking…" : "Unlock Worker Management"}</Button>
          </form> : <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">Password access is not configured yet. Add <code>WORKER_ADMIN_PASSWORD</code> in Vercel and redeploy, or add this user's Lark open ID to <code>LARK_ADMIN_OPEN_IDS</code>.</div>}
        </CardContent>
      </Card>
    </div>
  </div>

  return <div className="page">
    <div className="mb-6">
      <h1 className="page-title">Worker management</h1>
      <p className="page-subtitle">View and edit worker-only profile, classification, and payroll-rate information.</p>
    </div>

    <div className="metric-grid mb-5">
      <ProfileMetric icon={Users} label="Total records" value={data?.totals.workers || 0} />
      <ProfileMetric icon={UserCheck} label="Active" value={data?.totals.active || 0} />
      <ProfileMetric icon={Archive} label="Archived" value={data?.totals.archived || 0} />
      <ProfileMetric icon={ShieldCheck} label="W-2" value={data?.totals.w2 || 0} />
    </div>

    <Card>
      <CardHeader className="!flex-col justify-between gap-3 lg:!flex-row lg:items-center">
        <div>
          <CardTitle>Worker profiles</CardTitle>
          <CardDescription>Daily rate is worker master data used by estimated payroll calculations.</CardDescription>
        </div>
        <div className="flex w-full flex-col gap-2 sm:flex-row lg:w-auto">
          <div className="relative min-w-64 flex-1">
            <Search className="absolute left-3 top-3.5 size-4 text-muted-foreground" />
            <Input className="pl-9" value={search} onChange={event => setSearch(event.target.value)} placeholder="Search name, ID, alias…" />
          </div>
          <select className="h-11 rounded-lg border bg-white px-3 text-sm" value={status} onChange={event => setStatus(event.target.value as typeof status)}>
            <option value="active">Active workers</option>
            <option value="archived">Archived workers</option>
          </select>
          <Button onClick={addWorker}><Plus className="size-4" />Add worker</Button>
        </div>
      </CardHeader>
      <CardContent>
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>Worker</th><th>Type</th><th>Daily rate</th><th>Aliases</th><th>Status</th><th></th></tr></thead>
            <tbody>{workers.map(worker => <tr className="cursor-pointer" key={worker.worker_key} onClick={() => setDraft({ ...worker })}>
              <td><div className="flex items-center gap-2"><span className="avatar">{initials(worker.name)}</span><div><strong>{worker.name}</strong><small className="block text-muted-foreground">ID {worker.worker_key}</small></div></div></td>
              <td><Badge variant={worker.worker_type === "W2" ? "warning" : "secondary"}>{worker.worker_type === "W2" ? "W-2" : "1099"}</Badge></td>
              <td className="font-semibold tabular-nums">${compactNumber(worker.daily_rate)}</td>
              <td className="max-w-64 truncate text-muted-foreground">{worker.aliases || "—"}</td>
              <td><Badge variant={worker.active ? "success" : "secondary"}>{worker.active ? "Active" : "Archived"}</Badge></td>
              <td><Button size="sm" variant="ghost"><Pencil className="size-4" />Edit</Button></td>
            </tr>)}</tbody>
          </table>
        </div>
        {!workers.length && <div className="py-14 text-center text-sm text-muted-foreground">No workers match the current filters.</div>}
      </CardContent>
    </Card>

    <Dialog open={!!draft} onOpenChange={open => { if (!open) setDraft(null) }}>
      {draft && <DialogContent>
        <DialogHeader>
          <DialogTitle>{draft.worker_key ? "Edit worker profile" : "Add worker"}</DialogTitle>
          <DialogDescription>{draft.worker_key ? "Update the worker’s master information." : "The worker ID and display order are assigned automatically."}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          {draft.worker_key && <label className="field-label">Worker key<Input value={draft.worker_key} disabled /></label>}
          {draft.worker_key && <label className="field-label">Normalized name<Input value={draft.normalized_name} disabled /></label>}
          <label className="field-label sm:col-span-2">Worker name<Input value={draft.name} onChange={event => setDraft({ ...draft, name: event.target.value })} /></label>
          <label className="field-label">Worker type<select className="h-11 rounded-lg border bg-white px-3 text-sm" value={draft.worker_type} onChange={event => setDraft({ ...draft, worker_type: event.target.value as WorkerProfile["worker_type"] })}><option value="W2">W-2 employee</option><option value="1099">1099 contractor</option></select></label>
          <label className="field-label">Daily salary / rate<Input type="number" min="0" step=".01" value={draft.daily_rate} onChange={event => setDraft({ ...draft, daily_rate: Number(event.target.value) })} /></label>
          <label className="field-label">Display order<Input type="number" min="0" step="1" value={draft.display_order} onChange={event => setDraft({ ...draft, display_order: Number(event.target.value) })} /></label>
          <div className="flex items-center gap-3 rounded-lg border p-3 text-sm font-semibold"><Badge variant={draft.active ? "success" : "secondary"}>{draft.active ? "Active worker" : "Archived worker"}</Badge></div>
          <label className="field-label sm:col-span-2">Aliases<Input value={draft.aliases} onChange={event => setDraft({ ...draft, aliases: event.target.value })} placeholder="Separate alternate names with semicolons" /></label>
          <label className="field-label sm:col-span-2">Worker notes<Textarea value={draft.notes} onChange={event => setDraft({ ...draft, notes: event.target.value })} placeholder="Payment schedule, payment method, work status, or other worker-only notes" /></label>
        </div>
        {draft.id > 0 && draft.active && <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-red-200 bg-red-50 p-4">
          <div><strong className="block text-sm text-red-900">Archive this worker</strong><p className="mt-1 text-xs text-red-700">The worker disappears from all operational pages. Historical records remain available if the worker is restored later.</p></div>
          <Button variant="danger" onClick={() => void remove()} disabled={saving || removing}><Archive className="size-4" />{removing ? "Archiving…" : "Archive worker"}</Button>
        </div>}
        {draft.id > 0 && !draft.active && <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-sky-200 bg-sky-50 p-4">
          <div><strong className="block text-sm text-sky-950">Restore this worker</strong><p className="mt-1 text-xs text-sky-800">The worker will return to entry, overview, payroll, and site pages.</p></div>
          <Button onClick={() => void restore()} disabled={saving || restoring}><ArchiveRestore className="size-4" />{restoring ? "Restoring…" : "Restore worker"}</Button>
        </div>}
        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={() => setDraft(null)}>Cancel</Button>
          <Button onClick={() => void save()} disabled={saving || removing || restoring}><Save className="size-4" />{saving ? "Saving…" : draft.worker_key ? "Save worker" : "Add worker"}</Button>
        </div>
      </DialogContent>}
    </Dialog>
  </div>
}

function ProfileMetric({ icon: Icon, label, value }: { icon: typeof Users; label: string; value: number }) {
  return <Card><CardContent className="flex items-center gap-3 !pt-5"><span className="grid size-11 place-items-center rounded-xl bg-blue-50 text-accent"><Icon className="size-5" /></span><div><p className="text-xs font-semibold text-muted-foreground">{label}</p><strong className="text-2xl tabular-nums">{value}</strong></div></CardContent></Card>
}
