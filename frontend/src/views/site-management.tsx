import { useEffect, useMemo, useRef, useState } from "react"
import { Archive, ArchiveRestore, CheckCircle2, FileSpreadsheet, LoaderCircle, LockKeyhole, MapPin, Pencil, Plus, Save, Search, ShieldCheck, Upload } from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input, Textarea } from "@/components/ui/input"
import { api, postJSON } from "@/lib/api"

type SiteProfile = {
  site_key: string
  name: string
  full_address: string
  address_line_1: string
  city: string
  state: string
  zip_code: string
  aliases: string
  default_cost_code_ids: string
  active: boolean
  verified: boolean
  source: string
  notes: string
  updated_at: string
}

type SiteResponse = {
  sites: SiteProfile[]
  totals: { sites: number; active: number; archived: number; verified: number; needs_review: number }
}

type Access = {
  authorized: boolean
  access_type: "lark_admin" | "password" | ""
  password_configured: boolean
  admin_allowlist_configured: boolean
}

const blankSite = (): SiteProfile => ({
  site_key: "",
  name: "",
  full_address: "",
  address_line_1: "",
  city: "",
  state: "CA",
  zip_code: "",
  aliases: "",
  default_cost_code_ids: "",
  active: true,
  verified: true,
  source: "app",
  notes: "",
  updated_at: "",
})

export function SiteManagementView({ onSaved }: { onSaved: () => void }) {
  const [access, setAccess] = useState<Access | null>(null)
  const [password, setPassword] = useState("")
  const [unlocking, setUnlocking] = useState(false)
  const [data, setData] = useState<SiteResponse | null>(null)
  const [search, setSearch] = useState("")
  const [status, setStatus] = useState<"active" | "archived" | "review">("active")
  const [draft, setDraft] = useState<SiteProfile | null>(null)
  const [saving, setSaving] = useState(false)
  const [changingStatus, setChangingStatus] = useState(false)
  const [importing, setImporting] = useState(false)
  const [replaceLibrary, setReplaceLibrary] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const load = async () => setData(await api<SiteResponse>("/api/sites/library"))
  const checkAccess = async () => {
    try {
      const value = await api<Access>("/api/workers/access")
      setAccess(value)
      if (value.authorized) await load()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Unable to check Site Management access")
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
      toast.success("Site Management unlocked for 8 hours.")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Unable to unlock Site Management")
    } finally {
      setUnlocking(false)
    }
  }

  const sites = useMemo(() => {
    const query = search.trim().toLocaleLowerCase()
    return (data?.sites || []).filter(site => {
      if (status === "active" && !site.active) return false
      if (status === "archived" && site.active) return false
      if (status === "review" && site.verified) return false
      return !query || [site.name, site.full_address, site.address_line_1, site.city, site.zip_code, site.aliases]
        .some(value => value.toLocaleLowerCase().includes(query))
    })
  }, [data, search, status])

  const refreshEverywhere = async () => {
    try { localStorage.removeItem("speed-bootstrap-details-v2") } catch {}
    await load()
    onSaved()
  }

  const save = async () => {
    if (!draft) return
    if (!draft.name.trim() && !draft.full_address.trim()) return toast.error("Site name or full address is required.")
    setSaving(true)
    try {
      const result = await postJSON<{ site: SiteProfile }>("/api/sites/library", draft)
      setDraft(null)
      await refreshEverywhere()
      toast.success(`${result.site.name} was saved.`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Unable to save Site")
    } finally {
      setSaving(false)
    }
  }

  const setActive = async (active: boolean) => {
    if (!draft?.site_key) return
    if (!active && !window.confirm(
      `Archive ${draft.name}? It will disappear from new Entry and Schedule selections; historical records remain unchanged.`,
    )) return
    setChangingStatus(true)
    try {
      const result = await postJSON<{ site: SiteProfile }>(
        active ? "/api/sites/restore" : "/api/sites/delete",
        { site_key: draft.site_key },
      )
      setDraft(null)
      setStatus(active ? "active" : "archived")
      await refreshEverywhere()
      toast.success(active ? `${result.site.name} was restored.` : `${result.site.name} was archived.`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Unable to update Site status")
    } finally {
      setChangingStatus(false)
    }
  }

  const importFile = async (file?: File) => {
    if (!file) return
    if (replaceLibrary && !window.confirm(
      "Replace mode archives every currently active Site that is not in this file. Continue?",
    )) {
      if (fileRef.current) fileRef.current.value = ""
      return
    }
    setImporting(true)
    try {
      const result = await api<{ created: number; updated: number; archived: number; duplicates_skipped: number }>(
        `/api/sites/import?replace=${replaceLibrary ? "1" : "0"}`,
        {
          method: "POST",
          headers: {
            "Content-Type": file.type || "application/octet-stream",
            "X-Filename": file.name.replace(/[^\x20-\x7E]/g, "_"),
          },
          body: file,
        },
      )
      await refreshEverywhere()
      toast.success(
        `Address library updated: ${result.created} added, ${result.updated} updated` +
        (result.archived ? `, ${result.archived} archived.` : "."),
      )
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Unable to import the address file")
    } finally {
      setImporting(false)
      if (fileRef.current) fileRef.current.value = ""
    }
  }

  if (!access) return <div className="page"><Card><CardContent className="flex items-center justify-center gap-3 py-20 text-sm text-muted-foreground"><LoaderCircle className="size-5 animate-spin" />Checking Site Management access…</CardContent></Card></div>
  if (!access.authorized) return <div className="page"><div className="mx-auto max-w-lg py-10"><Card>
    <CardHeader><span className="mb-2 grid size-12 place-items-center rounded-xl bg-blue-50 text-primary"><LockKeyhole className="size-6" /></span><CardTitle>Site Management is protected</CardTitle><CardDescription>Use the same administrator access as Worker Management.</CardDescription></CardHeader>
    <CardContent>{access.password_configured ? <form className="grid gap-3" onSubmit={unlock}><label className="field-label">Management password<Input autoFocus type="password" value={password} onChange={event => setPassword(event.target.value)} /></label><Button type="submit" disabled={!password || unlocking}>{unlocking ? <LoaderCircle className="size-4 animate-spin" /> : <LockKeyhole className="size-4" />}{unlocking ? "Unlocking…" : "Unlock Site Management"}</Button></form> : <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">Configure <code>WORKER_ADMIN_PASSWORD</code> or use an administrator Lark account.</div>}</CardContent>
  </Card></div></div>

  return <div className="page">
    <div className="mb-6"><h1 className="page-title">Site management</h1><p className="page-subtitle">Maintain the formal address library used by Entry, Schedule, invoices, and Site selection.</p></div>
    <div className="metric-grid mb-5">
      <Metric icon={MapPin} label="Total records" value={data?.totals.sites || 0} />
      <Metric icon={CheckCircle2} label="Active" value={data?.totals.active || 0} />
      <Metric icon={ShieldCheck} label="Verified" value={data?.totals.verified || 0} />
      <Metric icon={Archive} label="Needs review" value={data?.totals.needs_review || 0} />
    </div>
    <Card className="mb-5">
      <CardHeader><CardTitle>Update the address library</CardTitle><CardDescription>Upload an XLSX or UTF-8 CSV. Merge adds and updates matching addresses. Replace also archives active addresses omitted from the file.</CardDescription></CardHeader>
      <CardContent className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center gap-3"><FileSpreadsheet className="size-8 text-accent" /><div><strong className="text-sm">Formalized Site address file</strong><p className="text-xs text-muted-foreground">Recognizes Full Address, Site Name, City, State, ZIP, Aliases, Active, and Verified columns.</p></div></div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={replaceLibrary} onChange={event => setReplaceLibrary(event.target.checked)} />Replace active library</label>
          <input ref={fileRef} className="hidden" type="file" accept=".xlsx,.csv" onChange={event => void importFile(event.target.files?.[0])} />
          <Button variant="outline" onClick={() => fileRef.current?.click()} disabled={importing}>{importing ? <LoaderCircle className="size-4 animate-spin" /> : <Upload className="size-4" />}{importing ? "Importing…" : "Import addresses"}</Button>
        </div>
      </CardContent>
    </Card>
    <Card>
      <CardHeader className="!flex-col justify-between gap-3 lg:!flex-row lg:items-center"><div><CardTitle>Site address book</CardTitle><CardDescription>Archived Sites remain attached to historical work records but cannot be selected for new work.</CardDescription></div><div className="flex w-full flex-col gap-2 sm:flex-row lg:w-auto"><div className="relative min-w-64 flex-1"><Search className="absolute left-3 top-3.5 size-4 text-muted-foreground" /><Input className="pl-9" value={search} onChange={event => setSearch(event.target.value)} placeholder="Search address, city, ZIP, alias…" /></div><select className="h-11 rounded-lg border bg-white px-3 text-sm" value={status} onChange={event => setStatus(event.target.value as typeof status)}><option value="active">Active Sites</option><option value="archived">Archived Sites</option><option value="review">Needs review</option></select><Button onClick={() => setDraft(blankSite())}><Plus className="size-4" />Add Site</Button></div></CardHeader>
      <CardContent className="overflow-x-auto p-0"><table className="data-table min-w-[860px]"><thead><tr><th>Site</th><th>City</th><th>State / ZIP</th><th>Source</th><th>Status</th><th className="w-24">Action</th></tr></thead><tbody>{sites.map(site => <tr key={site.site_key}><td><strong>{site.name}</strong>{site.aliases && <div className="mt-1 text-xs text-muted-foreground">Aliases: {site.aliases}</div>}</td><td>{site.city || "—"}</td><td>{[site.state, site.zip_code].filter(Boolean).join(" ") || "—"}</td><td className="text-xs text-muted-foreground">{site.source || "app"}</td><td><div className="flex flex-wrap gap-1"><Badge variant={site.active ? "success" : "secondary"}>{site.active ? "Active" : "Archived"}</Badge>{!site.verified && <Badge variant="warning">Needs review</Badge>}</div></td><td><Button variant="ghost" size="sm" onClick={() => setDraft({ ...site })}><Pencil className="size-4" />Edit</Button></td></tr>)}{!sites.length && <tr><td colSpan={6} className="py-16 text-center text-sm text-muted-foreground">No Sites match this filter.</td></tr>}</tbody></table></CardContent>
    </Card>
    <Dialog open={Boolean(draft)} onOpenChange={open => !open && setDraft(null)}>{draft && <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto"><DialogHeader><DialogTitle>{draft.site_key ? "Edit Site" : "Add Site"}</DialogTitle><DialogDescription>Use a complete postal address where available. Aliases help match older short Site names during future imports.</DialogDescription></DialogHeader><div className="grid gap-4 sm:grid-cols-2"><label className="field-label sm:col-span-2">Site display name<Input value={draft.name} onChange={event => setDraft({ ...draft, name: event.target.value })} placeholder="e.g. 444 Pocatello Dr, San Jose, CA 95111" /></label><label className="field-label sm:col-span-2">Full address<Input value={draft.full_address} onChange={event => setDraft({ ...draft, full_address: event.target.value, name: draft.name || event.target.value })} /></label><label className="field-label sm:col-span-2">Address line 1<Input value={draft.address_line_1} onChange={event => setDraft({ ...draft, address_line_1: event.target.value })} /></label><label className="field-label">City<Input value={draft.city} onChange={event => setDraft({ ...draft, city: event.target.value })} /></label><div className="grid grid-cols-2 gap-3"><label className="field-label">State<Input maxLength={2} value={draft.state} onChange={event => setDraft({ ...draft, state: event.target.value.toUpperCase() })} /></label><label className="field-label">ZIP Code<Input value={draft.zip_code} onChange={event => setDraft({ ...draft, zip_code: event.target.value })} /></label></div><label className="field-label sm:col-span-2">Aliases<Input value={draft.aliases} onChange={event => setDraft({ ...draft, aliases: event.target.value })} placeholder="Separate old or short Site names with semicolons" /></label><label className="field-label sm:col-span-2">Default Cost Code IDs<Input value={draft.default_cost_code_ids} onChange={event => setDraft({ ...draft, default_cost_code_ids: event.target.value })} placeholder="Optional; separate IDs with semicolons" /></label><label className="field-label sm:col-span-2">Notes<Textarea value={draft.notes} onChange={event => setDraft({ ...draft, notes: event.target.value })} /></label><label className="flex items-center gap-2 rounded-xl border p-4 text-sm font-semibold"><input type="checkbox" checked={draft.active} onChange={event => setDraft({ ...draft, active: event.target.checked })} />Active Site</label><label className="flex items-center gap-2 rounded-xl border p-4 text-sm font-semibold"><input type="checkbox" checked={draft.verified} onChange={event => setDraft({ ...draft, verified: event.target.checked })} />Address verified</label></div>{draft.site_key && <div className={`mt-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border p-4 ${draft.active ? "border-red-200 bg-red-50" : "border-sky-200 bg-sky-50"}`}><div><strong className="block text-sm">{draft.active ? "Archive this Site" : "Restore this Site"}</strong><p className="mt-1 text-xs text-muted-foreground">Historical work records are always preserved.</p></div><Button variant={draft.active ? "danger" : "default"} onClick={() => void setActive(!draft.active)} disabled={saving || changingStatus}>{draft.active ? <Archive className="size-4" /> : <ArchiveRestore className="size-4" />}{changingStatus ? "Updating…" : draft.active ? "Archive Site" : "Restore Site"}</Button></div>}<div className="mt-5 flex justify-end gap-2"><Button variant="ghost" onClick={() => setDraft(null)}>Cancel</Button><Button onClick={() => void save()} disabled={saving || changingStatus}><Save className="size-4" />{saving ? "Saving…" : "Save Site"}</Button></div></DialogContent>}</Dialog>
  </div>
}

function Metric({ icon: Icon, label, value }: { icon: typeof MapPin; label: string; value: number }) {
  return <Card><CardContent className="flex items-center gap-3 !pt-5"><span className="grid size-11 place-items-center rounded-xl bg-blue-50 text-accent"><Icon className="size-5" /></span><div><p className="text-xs font-semibold text-muted-foreground">{label}</p><strong className="text-2xl tabular-nums">{value}</strong></div></CardContent></Card>
}
