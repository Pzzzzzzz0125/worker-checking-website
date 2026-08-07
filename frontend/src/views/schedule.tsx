import { useEffect, useMemo, useState } from "react"
import { AlertTriangle, CalendarClock, Check, ChevronLeft, ChevronRight, Edit3, LoaderCircle, Plus, RotateCcw, X } from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input, Textarea } from "@/components/ui/input"
import { api, postJSON } from "@/lib/api"
import type { Bootstrap } from "@/lib/types"
import { displayDate, localISO } from "@/lib/utils"

type ScheduleRow = {
  schedule_key: string
  worker_key: string
  worker_name: string
  schedule_date: string
  site: string
  task: string
  start_time: string
  end_time: string
  notes: string
  status: "confirmed" | "pending_approval" | "approved" | "rejected" | "cancelled" | string
  conflict_reason: string
  submitted_by_name: string
  reviewed_by_name: string
}

type FormState = {
  schedule_key: string
  schedule_date: string
  worker_key: string
  site: string
  task: string
  start_time: string
  end_time: string
  notes: string
}

function monday(value: string) {
  const day = new Date(`${value}T12:00:00`)
  const offset = (day.getDay() + 6) % 7
  day.setDate(day.getDate() - offset)
  return localISO(day)
}

function shift(value: string, days: number) {
  const day = new Date(`${value}T12:00:00`)
  day.setDate(day.getDate() + days)
  return localISO(day)
}

function emptyForm(date: string): FormState {
  return { schedule_key: "", schedule_date: date, worker_key: "", site: "", task: "", start_time: "", end_time: "", notes: "" }
}

function statusBadge(status: ScheduleRow["status"]) {
  if (status === "confirmed" || status === "approved") return <Badge variant="success">Confirmed</Badge>
  if (status === "pending_approval") return <Badge variant="warning">Needs approval</Badge>
  if (status === "rejected") return <Badge variant="destructive">Rejected</Badge>
  if (status === "cancelled") return <Badge>Cancelled</Badge>
  return <Badge>{status}</Badge>
}

export function ScheduleView({ bootstrap }: { bootstrap: Bootstrap }) {
  const [weekStart, setWeekStart] = useState(() => monday(localISO()))
  const [rows, setRows] = useState<ScheduleRow[]>([])
  const [form, setForm] = useState<FormState>(() => emptyForm(monday(localISO())))
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [reviewing, setReviewing] = useState<string | null>(null)
  const [search, setSearch] = useState("")

  const weekEnd = shift(weekStart, 6)
  const workers = useMemo(() => bootstrap.workers.filter(worker => worker.active !== 0), [bootstrap.workers])
  const visibleRows = rows.filter(row => {
    const needle = search.trim().toLowerCase()
    return !needle || [row.worker_name, row.site, row.task, row.status].some(value => value.toLowerCase().includes(needle))
  })

  const load = async () => {
    setLoading(true)
    try {
      const result = await api<{ rows: ScheduleRow[] }>(`/api/schedule?from=${weekStart}&to=${weekEnd}`)
      setRows(result.rows || [])
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { void load() }, [weekStart])

  const setField = (key: keyof FormState, value: string) => setForm(current => ({ ...current, [key]: value }))
  const resetForm = () => setForm(emptyForm(weekStart))
  const edit = (row: ScheduleRow) => setForm({
    schedule_key: row.schedule_key,
    schedule_date: row.schedule_date,
    worker_key: row.worker_key,
    site: row.site,
    task: row.task,
    start_time: row.start_time,
    end_time: row.end_time,
    notes: row.notes,
  })

  const save = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!form.worker_key || !form.site.trim() || !form.task.trim()) {
      toast.error("Choose a worker and enter both Site and work task.")
      return
    }
    setSaving(true)
    try {
      const result = await postJSON<{ schedule: ScheduleRow; submitted_for_approval: boolean }>("/api/schedule", { action: "save", ...form })
      toast.success(result.submitted_for_approval ? "Conflict submitted for approval. It is not a confirmed schedule yet." : "Schedule confirmed.")
      resetForm()
      await load()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setSaving(false)
    }
  }

  const review = async (row: ScheduleRow, decision: "approved" | "rejected") => {
    setReviewing(row.schedule_key)
    try {
      await postJSON("/api/schedule", { action: "review", schedule_key: row.schedule_key, decision })
      toast.success(decision === "approved" ? "Schedule approved." : "Schedule rejected.")
      await load()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setReviewing(null)
    }
  }

  const cancel = async (row: ScheduleRow) => {
    if (!window.confirm(`Cancel ${row.worker_name}'s schedule at ${row.site}?`)) return
    setReviewing(row.schedule_key)
    try {
      await postJSON("/api/schedule", { action: "cancel", schedule_key: row.schedule_key })
      toast.success("Schedule cancelled.")
      await load()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setReviewing(null)
    }
  }

  return <div className="page">
    <div className="mb-6 flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
      <div><div className="mb-2 inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-xs font-bold text-blue-700"><CalendarClock className="size-3" />Schedule manager only</div><h1 className="page-title">Schedule</h1><p className="page-subtitle">Plan who goes to which Site and what they will do. Site and task are required; schedule times are optional.</p></div>
      <div className="flex items-center gap-2"><Button variant="outline" size="icon" onClick={() => setWeekStart(value => shift(value, -7))}><ChevronLeft className="size-4" /></Button><div className="min-w-44 text-center text-sm font-semibold">{displayDate(weekStart, true)} – {displayDate(weekEnd, true)}</div><Button variant="outline" size="icon" onClick={() => setWeekStart(value => shift(value, 7))}><ChevronRight className="size-4" /></Button><Button variant="outline" onClick={() => setWeekStart(monday(localISO()))}><RotateCcw className="size-4" />This week</Button></div>
    </div>

    <Card className="mb-5">
      <CardHeader><CardTitle>{form.schedule_key ? "Edit schedule" : "Add schedule"}</CardTitle><CardDescription>Overlapping Site assignments for one worker cannot be confirmed directly. They are saved only as a pending approval request.</CardDescription></CardHeader>
      <CardContent><form className="grid gap-4" onSubmit={save}>
        <div className="grid gap-4 md:grid-cols-3">
          <label className="field-label">Date<Input type="date" value={form.schedule_date} onChange={event => setField("schedule_date", event.target.value)} required /></label>
          <label className="field-label">Worker<select className="h-11 w-full rounded-lg border border-input bg-background px-3 text-sm" value={form.worker_key} onChange={event => setField("worker_key", event.target.value)} required><option value="">Select worker…</option>{workers.map(worker => <option key={worker.worker_key || worker.id} value={worker.worker_key || String(worker.id)}>{worker.name}</option>)}</select></label>
          <label className="field-label">Site<Input list="locations" value={form.site} onChange={event => setField("site", event.target.value)} placeholder="Select or enter a Site" required /></label>
        </div>
        <div className="grid gap-4 md:grid-cols-[1.2fr_.4fr_.4fr]">
          <label className="field-label">Work task<Input value={form.task} onChange={event => setField("task", event.target.value)} placeholder="e.g. Framing, cleanup, inspection" required /></label>
          <label className="field-label">Start time<Input type="time" value={form.start_time} onChange={event => setField("start_time", event.target.value)} /></label>
          <label className="field-label">End time<Input type="time" value={form.end_time} onChange={event => setField("end_time", event.target.value)} /></label>
        </div>
        <label className="field-label">Notes<Textarea value={form.notes} onChange={event => setField("notes", event.target.value)} placeholder="Optional planning notes" /></label>
        <div className="flex flex-wrap justify-end gap-2"><Button type="button" variant="ghost" onClick={resetForm}>Clear</Button><Button type="submit" disabled={saving}>{saving ? <LoaderCircle className="size-4 animate-spin" /> : form.schedule_key ? <Edit3 className="size-4" /> : <Plus className="size-4" />}{saving ? "Saving…" : form.schedule_key ? "Save changes" : "Add schedule"}</Button></div>
      </form></CardContent>
    </Card>

    <Card>
      <CardHeader><div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center"><div><CardTitle>Weekly assignments</CardTitle><CardDescription>Confirmed schedules can be copied to Entry later. Pending conflicts stay out of Entry until approved.</CardDescription></div><Input className="sm:max-w-xs" value={search} onChange={event => setSearch(event.target.value)} placeholder="Search worker, Site, task…" /></div></CardHeader>
      <CardContent>{loading ? <div className="flex items-center gap-2 py-10 text-sm text-muted-foreground"><LoaderCircle className="size-4 animate-spin" />Loading schedule…</div> : visibleRows.length ? <div className="grid gap-3">{visibleRows.map(row => <div key={row.schedule_key} className={`rounded-xl border p-4 ${row.status === "pending_approval" ? "border-amber-300 bg-amber-50/50" : row.status === "rejected" || row.status === "cancelled" ? "opacity-60" : ""}`}><div className="flex flex-col gap-3 lg:flex-row lg:items-start"><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><strong>{displayDate(row.schedule_date, true)}</strong>{statusBadge(row.status)}{row.status === "pending_approval" && <AlertTriangle className="size-4 text-amber-600" />}</div><p className="mt-1 text-sm"><strong>{row.worker_name}</strong><span className="mx-2 text-muted-foreground">·</span>{row.site}<span className="mx-2 text-muted-foreground">·</span>{row.task}</p><p className="mt-1 text-xs text-muted-foreground">{row.start_time && row.end_time ? `${row.start_time}–${row.end_time}` : "Time not set"}{row.notes ? ` · ${row.notes}` : ""}</p>{row.conflict_reason && <p className="mt-2 text-xs font-semibold text-amber-800">{row.conflict_reason}</p>}{row.submitted_by_name && <p className="mt-2 text-[11px] text-muted-foreground">Submitted by {row.submitted_by_name}{row.reviewed_by_name ? ` · reviewed by ${row.reviewed_by_name}` : ""}</p>}</div><div className="flex flex-wrap gap-2 lg:justify-end">{row.status === "pending_approval" && <><Button size="sm" variant="outline" disabled={reviewing === row.schedule_key} onClick={() => void review(row, "rejected")}><X className="size-4" />Reject</Button><Button size="sm" disabled={reviewing === row.schedule_key} onClick={() => void review(row, "approved")}><Check className="size-4" />Approve</Button></>}{row.status !== "cancelled" && row.status !== "rejected" && <><Button size="sm" variant="outline" onClick={() => edit(row)}><Edit3 className="size-4" />Edit</Button><Button size="sm" variant="ghost" className="text-red-600 hover:text-red-700" disabled={reviewing === row.schedule_key} onClick={() => void cancel(row)}><X className="size-4" />Cancel</Button></>}</div></div></div>)}</div> : <div className="rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">No schedules for this week.</div>}</CardContent>
    </Card>
  </div>
}
