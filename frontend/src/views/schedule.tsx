import { useEffect, useMemo, useState } from "react"
import { AlertTriangle, Bell, CalendarClock, Check, ChevronLeft, ChevronRight, Edit3, LoaderCircle, Plus, RotateCcw, X } from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
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
  cost_code_ids: string[]
  cost_code_names: string[]
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
  schedule_end_date: string
  worker_key: string
  site: string
  cost_code_ids: string[]
  start_time: string
  end_time: string
  notes: string
}

type NotificationRecipient = {
  open_id: string
  name: string
  role: "schedule_manager" | "super_admin" | string
  role_label: string
  required: boolean
  current: boolean
}

type NotificationResult = {
  attempted: number
  sent: number
  failed: number
  recipients: string[]
  warning?: string
  errors?: { name?: string; code?: number | null; error: string }[] | string[]
}

type ConflictDetail = {
  schedule_date: string
  reason: string
  proposed: ScheduleRow
  existing: ScheduleRow[]
}

type ScheduleSaveResult = {
  schedule: ScheduleRow
  schedules?: ScheduleRow[]
  submitted_for_approval: boolean
  requires_conflict_approval?: boolean
  conflicts?: ConflictDetail[]
  notification?: NotificationResult
}

type PendingConflict = {
  payload: Record<string, unknown>
  dates: string[]
  conflicts: ConflictDetail[]
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
  return { schedule_key: "", schedule_date: date, schedule_end_date: date, worker_key: "", site: "", cost_code_ids: [], start_time: "", end_time: "", notes: "" }
}

function scheduleDays(start: string, end: string) {
  if (!start || !end || start > end) return 0
  return Math.floor((new Date(`${end}T12:00:00`).getTime() - new Date(`${start}T12:00:00`).getTime()) / 86_400_000) + 1
}

function calendarCells(month: string) {
  const first = new Date(`${month}-01T12:00:00`)
  const offset = (first.getDay() + 6) % 7
  const daysInMonth = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate()
  const cells = Array.from({ length: offset }, () => "")
  for (let day = 1; day <= daysInMonth; day += 1) {
    cells.push(`${month}-${String(day).padStart(2, "0")}`)
  }
  while (cells.length % 7) cells.push("")
  return cells
}

function monthLabel(month: string) {
  return new Date(`${month}-01T12:00:00`).toLocaleDateString(undefined, { month: "long", year: "numeric" })
}

type ScheduleCalendarProps = {
  month: string
  onMonthChange: (month: string) => void
  mode: "range" | "dates"
  rangeStart: string
  rangeEnd: string
  selectedDates: string[]
  onRangeDate: (date: string) => void
  onToggleDate: (date: string) => void
}

function ScheduleCalendar({ month, onMonthChange, mode, rangeStart, rangeEnd, selectedDates, onRangeDate, onToggleDate }: ScheduleCalendarProps) {
  const cells = calendarCells(month)
  const rangeFrom = rangeStart && rangeEnd ? (rangeStart < rangeEnd ? rangeStart : rangeEnd) : ""
  const rangeTo = rangeStart && rangeEnd ? (rangeStart < rangeEnd ? rangeEnd : rangeStart) : ""
  return <div className="grid gap-3">
    <div className="flex flex-wrap items-center justify-between gap-2"><div><strong className="text-sm">{monthLabel(month)}</strong>{mode === "range" && <p className="mt-1 text-xs text-muted-foreground">{rangeStart && !rangeEnd ? "Now choose the end date" : "Click a start date, then an end date"}</p>}</div><div className="flex gap-1"><Button type="button" variant="outline" size="icon" onClick={() => onMonthChange(shift(`${month}-01`, -1).slice(0, 7))}><ChevronLeft className="size-4" /></Button><Button type="button" variant="outline" size="icon" onClick={() => onMonthChange(shift(`${month}-01`, 31).slice(0, 7))}><ChevronRight className="size-4" /></Button></div></div>
    <div className="grid grid-cols-7 gap-1 text-center text-[10px] font-bold uppercase text-muted-foreground">{["M", "T", "W", "T", "F", "S", "S"].map((day, index) => <span key={`${day}-${index}`}>{day}</span>)}</div>
    <div className="grid grid-cols-7 gap-1">{cells.map((value, index) => {
      if (!value) return <span key={`blank-${index}`} />
      const selected = selectedDates.includes(value)
      const isStart = mode === "range" && value === rangeStart
      const isEnd = mode === "range" && Boolean(rangeEnd) && value === rangeEnd
      const inRange = mode === "range" && Boolean(rangeFrom && rangeTo) && value >= rangeFrom && value <= rangeTo
      return <button type="button" key={value} onClick={() => mode === "range" ? onRangeDate(value) : onToggleDate(value)} className={`relative grid min-h-10 place-items-center rounded-lg text-xs font-semibold transition-colors ${mode === "dates" && selected ? "bg-primary text-primary-foreground" : ""} ${mode === "dates" && !selected ? "bg-white hover:bg-blue-50" : ""} ${mode === "range" && inRange && !isStart && !isEnd ? "bg-blue-100 text-blue-950 hover:bg-blue-200" : ""} ${mode === "range" && (isStart || isEnd) ? "bg-primary text-primary-foreground shadow-sm" : ""} ${mode === "range" && !inRange && !isStart && !isEnd ? "bg-white hover:bg-blue-50" : ""}`} aria-label={displayDate(value, true)}>{Number(value.slice(-2))}</button>
    })}</div>
    {mode === "range" ? <div className="flex flex-wrap items-center gap-2 text-xs"><span className="font-semibold">{rangeStart ? `From ${displayDate(rangeStart, true)}` : "No start date"}</span><span className="text-muted-foreground">→</span><span className="font-semibold">{rangeEnd ? `To ${displayDate(rangeEnd, true)}` : "Choose end date"}</span>{(rangeStart || rangeEnd) && <button type="button" className="ml-auto text-red-600 underline" onClick={() => onRangeDate("")}>Clear range</button>}</div> : <div className="flex flex-wrap items-center gap-2 text-xs"><span className="font-semibold">{selectedDates.length} selected</span>{selectedDates.length > 0 && <button type="button" className="text-red-600 underline" onClick={() => onToggleDate("")}>Clear dates</button>}</div>}
  </div>
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
  const [form, setForm] = useState<FormState>(() => emptyForm(localISO()))
  const [workerSearch, setWorkerSearch] = useState("")
  const [planMode, setPlanMode] = useState<"single" | "multiple">("single")
  const [multipleMode, setMultipleMode] = useState<"range" | "dates">("range")
  const [selectedDates, setSelectedDates] = useState<string[]>([])
  const [calendarMonth, setCalendarMonth] = useState(() => localISO().slice(0, 7))
  const [rangeStep, setRangeStep] = useState<"start" | "end">("start")
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [reviewing, setReviewing] = useState<string | null>(null)
  const [search, setSearch] = useState("")
  const [notificationRecipients, setNotificationRecipients] = useState<NotificationRecipient[]>([])
  const [pendingConflict, setPendingConflict] = useState<PendingConflict | null>(null)
  const [conflictRecipientIds, setConflictRecipientIds] = useState<string[]>([])
  const [submittingConflict, setSubmittingConflict] = useState(false)

  const weekEnd = shift(weekStart, 6)
  const workers = useMemo(() => bootstrap.workers.filter(worker => worker.active !== 0), [bootstrap.workers])
  const visibleRows = rows.filter(row => {
    const needle = search.trim().toLowerCase()
    return !needle || [row.worker_name, row.site, ...row.cost_code_names, row.status].some(value => value.toLowerCase().includes(needle))
  })

  const load = async () => {
    setLoading(true)
    try {
      const result = await api<{ rows: ScheduleRow[]; notification_recipients?: NotificationRecipient[] }>(`/api/schedule?from=${weekStart}&to=${weekEnd}`)
      setRows(result.rows || [])
      const recipients = result.notification_recipients || []
      setNotificationRecipients(recipients)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { void load() }, [weekStart])

  const setField = (key: keyof FormState, value: string) => setForm(current => ({ ...current, [key]: value }))
  const resetForm = () => {
    const blank = emptyForm(localISO())
    setForm(planMode === "multiple" ? { ...blank, schedule_date: "", schedule_end_date: "" } : blank)
    setSelectedDates([])
    setWorkerSearch("")
    setRangeStep("start")
  }
  const edit = (row: ScheduleRow) => {
    setWorkerSearch(row.worker_name)
    setForm({
      schedule_key: row.schedule_key,
      schedule_date: row.schedule_date,
      schedule_end_date: row.schedule_date,
      worker_key: row.worker_key,
      site: row.site,
      cost_code_ids: row.cost_code_ids,
      start_time: row.start_time,
      end_time: row.end_time,
      notes: row.notes,
    })
  }

  const chooseWorker = (value: string) => {
    setWorkerSearch(value)
    const normalized = value.trim().toLowerCase()
    const exact = workers.find(worker => worker.name.trim().toLowerCase() === normalized)
    setForm(current => ({
      ...current,
      worker_key: exact ? exact.worker_key || String(exact.id) : "",
    }))
  }

  const editRow = (row: ScheduleRow) => {
    setPlanMode("single")
    setSelectedDates([])
    setCalendarMonth(row.schedule_date.slice(0, 7))
    edit(row)
  }

  const save = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!form.worker_key || !form.site.trim() || !form.cost_code_ids.length) {
      toast.error("Choose a worker, Site, and Cost Code.")
      return
    }
    setSaving(true)
    try {
      const dates = planMode === "single"
        ? [form.schedule_date]
        : multipleMode === "range"
          ? (() => {
              const count = scheduleDays(form.schedule_date, form.schedule_end_date)
              if (!count || count > 31) return []
              return Array.from({ length: count }, (_, index) => shift(form.schedule_date, index))
            })()
          : [...selectedDates].sort()
      if (!dates.length || dates.length > 31) {
        toast.error("Choose at least one date and no more than 31 dates.")
        return
      }
      const payload = { action: "save", ...form, schedule_dates: dates, schedule_end_date: dates[dates.length - 1], confirm_conflicts: false }
      const result = await postJSON<ScheduleSaveResult>("/api/schedule", payload)
      if (result.requires_conflict_approval) {
        setPendingConflict({ payload, dates, conflicts: result.conflicts || [] })
        setConflictRecipientIds([])
        return
      }
      const savedCount = result.schedules?.length || 1
      toast.success(result.submitted_for_approval ? `${savedCount} schedule${savedCount === 1 ? "" : "s"} saved; conflicts need approval.` : `${savedCount} schedule${savedCount === 1 ? "" : "s"} confirmed.`)
      if (result.submitted_for_approval && result.notification) {
        const notice = result.notification
        if (notice.sent > 0 && notice.failed === 0) {
          toast.success(`Lark approval notice sent to ${notice.sent} recipient${notice.sent === 1 ? "" : "s"}.`)
        } else if (notice.sent > 0) {
          toast.warning(`Lark notice sent to ${notice.sent}; ${notice.failed} recipient${notice.failed === 1 ? "" : "s"} failed.`)
        } else {
          const firstError = notice.errors?.[0]
          const detail = typeof firstError === "string" ? firstError : firstError?.error
          toast.error(`Conflict saved, but the Lark notice was not sent.${detail ? ` ${detail}` : notice.warning ? ` ${notice.warning}` : ""}`)
        }
      }
      setWeekStart(monday(dates[0]))
      resetForm()
      await load()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setSaving(false)
    }
  }

  const submitConflictApproval = async () => {
    if (!pendingConflict) return
    const selectableManagers = notificationRecipients.filter(item => !item.required)
    if (selectableManagers.length && !conflictRecipientIds.length) {
      toast.error("Select at least one Schedule Manager to request approval.")
      return
    }
    setSubmittingConflict(true)
    try {
      const result = await postJSON<ScheduleSaveResult>("/api/schedule", {
        ...pendingConflict.payload,
        confirm_conflicts: true,
        notification_recipient_ids: conflictRecipientIds,
      })
      const savedCount = result.schedules?.length || 1
      toast.success(`${savedCount} conflict${savedCount === 1 ? "" : "s"} saved for approval.`)
      const notice = result.notification
      if (notice?.sent && notice.failed === 0) toast.success(`Lark approval request sent to ${notice.sent} recipient${notice.sent === 1 ? "" : "s"}.`)
      else if (notice?.sent) toast.warning(`Lark request sent to ${notice.sent}; ${notice.failed} failed.`)
      else toast.error(`Conflict saved, but no Lark approval message was sent.${notice?.warning ? ` ${notice.warning}` : ""}`)
      const firstDate = pendingConflict.dates[0]
      setPendingConflict(null)
      setConflictRecipientIds([])
      setWeekStart(monday(firstDate))
      resetForm()
      await load()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setSubmittingConflict(false)
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

  const [costCodeSearch, setCostCodeSearch] = useState("")
  const visibleCostCodes = bootstrap.cost_centers.filter(code => {
    const needle = costCodeSearch.trim().toLowerCase()
    return !needle || `${code.id} ${code.name}`.toLowerCase().includes(needle)
  }).slice(0, 80)
  const toggleCostCode = (id: string) => setForm(current => ({
    ...current,
    cost_code_ids: current.cost_code_ids.includes(id)
      ? current.cost_code_ids.filter(value => value !== id)
      : [...current.cost_code_ids, id],
  }))
  const requiredRecipients = notificationRecipients.filter(item => item.required)
  const optionalManagers = notificationRecipients.filter(item => !item.required)
  const toggleConflictRecipient = (openId: string) => setConflictRecipientIds(current => current.includes(openId)
    ? current.filter(value => value !== openId)
    : [...current, openId])
  const toggleDate = (value: string) => setSelectedDates(current => current.includes(value)
    ? current.filter(date => date !== value)
    : value ? current.length >= 31 ? current : [...current, value].sort() : [])
  const selectRangeDate = (value: string) => {
    if (!value) {
      setForm(current => ({ ...current, schedule_date: "", schedule_end_date: "" }))
      setRangeStep("start")
      return
    }
    if (rangeStep === "start" || !form.schedule_date) {
      setForm(current => ({ ...current, schedule_date: value, schedule_end_date: "" }))
      setRangeStep("end")
      setCalendarMonth(value.slice(0, 7))
      return
    }
    const start = form.schedule_date
    if (value < start) {
      setForm(current => ({ ...current, schedule_date: value, schedule_end_date: start }))
    } else {
      setForm(current => ({ ...current, schedule_end_date: value }))
    }
    setRangeStep("start")
  }
  const beginSingleMode = () => {
    setPlanMode("single")
    setSelectedDates([])
    setRangeStep("start")
    setForm(current => ({ ...current, schedule_date: current.schedule_date || localISO(), schedule_end_date: current.schedule_date || localISO() }))
  }
  const beginMultipleMode = () => {
    setPlanMode("multiple")
    setMultipleMode("range")
    setSelectedDates([])
    setRangeStep("start")
    setForm(current => ({ ...current, schedule_date: "", schedule_end_date: "" }))
    setCalendarMonth(localISO().slice(0, 7))
  }
  const formDateCount = planMode === "single"
    ? (form.schedule_date ? 1 : 0)
    : multipleMode === "range"
      ? scheduleDays(form.schedule_date, form.schedule_end_date)
      : selectedDates.length

  return <div className="page">
    <div className="mb-6 flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
      <div><div className="mb-2 inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-xs font-bold text-blue-700"><CalendarClock className="size-3" />Schedule manager only</div><h1 className="page-title">Schedule</h1><p className="page-subtitle">Plan a worker's Site and Cost Code. Site and Cost Code are required; schedule times are optional.</p></div>
      <div className="flex items-center gap-2"><Button variant="outline" size="icon" onClick={() => setWeekStart(value => shift(value, -7))}><ChevronLeft className="size-4" /></Button><div className="min-w-44 text-center text-sm font-semibold">{displayDate(weekStart, true)} – {displayDate(weekEnd, true)}</div><Button variant="outline" size="icon" onClick={() => setWeekStart(value => shift(value, 7))}><ChevronRight className="size-4" /></Button><Button variant="outline" onClick={() => setWeekStart(monday(localISO()))}><RotateCcw className="size-4" />This week</Button></div>
    </div>

    <Card className="mb-5">
      <CardHeader>
        <CardTitle>{form.schedule_key ? "Edit schedule" : "Plan work"}</CardTitle>
        <CardDescription>When an assignment conflicts, nothing is saved until you review the conflict and choose managers for approval.</CardDescription>
        {!form.schedule_key && <div className="mt-4 grid gap-2 sm:grid-cols-2">
          <button type="button" className={`rounded-xl border px-4 py-3 text-left transition-colors ${planMode === "single" ? "border-primary bg-primary text-primary-foreground" : "bg-white hover:border-primary/40"}`} onClick={beginSingleMode}>
            <span className="block text-sm font-bold">Single day</span><span className={`mt-1 block text-xs ${planMode === "single" ? "text-blue-100" : "text-muted-foreground"}`}>Plan one worker assignment for one date.</span>
          </button>
          <button type="button" className={`rounded-xl border px-4 py-3 text-left transition-colors ${planMode === "multiple" ? "border-primary bg-primary text-primary-foreground" : "bg-white hover:border-primary/40"}`} onClick={beginMultipleMode}>
            <span className="block text-sm font-bold">Multiple days</span><span className={`mt-1 block text-xs ${planMode === "multiple" ? "text-blue-100" : "text-muted-foreground"}`}>Repeat this assignment across a range or selected dates.</span>
          </button>
        </div>}
      </CardHeader>
      <CardContent><form className="grid gap-4" onSubmit={save}>
        <div className="grid gap-4 md:grid-cols-4">
          {planMode === "single" || form.schedule_key ? <label className="field-label">Schedule date<Input type="date" value={form.schedule_date} onChange={event => setField("schedule_date", event.target.value)} required /><span className="mt-1 block text-xs text-muted-foreground">One assignment date</span></label> : <div className="md:col-span-2 grid gap-3 rounded-xl border bg-slate-50 p-3">
            <div className="flex flex-wrap gap-2"><button type="button" className={`rounded-lg px-3 py-2 text-xs font-semibold ${multipleMode === "range" ? "bg-primary text-primary-foreground" : "bg-white"}`} onClick={() => { setMultipleMode("range"); setSelectedDates([]); setForm(current => ({ ...current, schedule_date: "", schedule_end_date: "" })); setRangeStep("start") }}>Date range</button><button type="button" className={`rounded-lg px-3 py-2 text-xs font-semibold ${multipleMode === "dates" ? "bg-primary text-primary-foreground" : "bg-white"}`} onClick={() => { setMultipleMode("dates"); setForm(current => ({ ...current, schedule_date: "", schedule_end_date: "" })); setRangeStep("start") }}>Select dates</button></div>
            <ScheduleCalendar mode={multipleMode} month={calendarMonth} onMonthChange={setCalendarMonth} rangeStart={form.schedule_date} rangeEnd={form.schedule_end_date} selectedDates={selectedDates} onRangeDate={selectRangeDate} onToggleDate={toggleDate} />
            <span className="text-xs text-muted-foreground">{formDateCount || 0} date{formDateCount === 1 ? "" : "s"} will be created. Maximum 31 dates.</span>
          </div>}
          <label className="field-label">Worker<Input list="schedule-workers" value={workerSearch} onChange={event => chooseWorker(event.target.value)} placeholder="Type to search workers…" autoComplete="off" required/><datalist id="schedule-workers">{workers.map(worker => <option key={worker.worker_key || worker.id} value={worker.name}/>)}</datalist>{workerSearch&&!form.worker_key&&<span className="mt-1 block text-xs text-amber-700">Choose an exact worker from the suggestions.</span>}</label>
          <label className="field-label">Site<Input list="locations" value={form.site} onChange={event => setField("site", event.target.value)} placeholder="Select or enter a Site" required /></label>
        </div>
        <div className="grid gap-3 rounded-xl border bg-slate-50 p-3">
          <label className="field-label">Cost Code <span className="text-red-600">required</span><Input value={costCodeSearch} onChange={event => setCostCodeSearch(event.target.value)} placeholder="Search by Cost Code ID or name…" /></label>
          <div className="flex flex-wrap gap-2">{form.cost_code_ids.map(id => { const code = bootstrap.cost_centers.find(item => item.id === id); return <button type="button" key={id} className="rounded-full bg-blue-100 px-3 py-1 text-xs font-semibold text-blue-900" onClick={() => toggleCostCode(id)}>{code ? `${code.name} (${code.id})` : id} ×</button> })}{!form.cost_code_ids.length && <span className="text-xs text-red-700">Select at least one Cost Code.</span>}</div>
          <div className="grid max-h-40 gap-1 overflow-auto rounded-lg border bg-white p-2 sm:grid-cols-2">{visibleCostCodes.map(code => <label key={code.id} className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-xs hover:bg-blue-50"><input type="checkbox" checked={form.cost_code_ids.includes(code.id)} onChange={() => toggleCostCode(code.id)} /><span className="truncate">{code.name} <span className="text-muted-foreground">({code.id})</span></span></label>)}{!visibleCostCodes.length && <span className="p-2 text-xs text-muted-foreground">No Cost Codes match.</span>}</div>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <label className="field-label">Start time<Input type="time" value={form.start_time} onChange={event => setField("start_time", event.target.value)} /></label>
          <label className="field-label">End time<Input type="time" value={form.end_time} onChange={event => setField("end_time", event.target.value)} /></label>
        </div>
        <label className="field-label">Notes<Textarea value={form.notes} onChange={event => setField("notes", event.target.value)} placeholder="Optional planning notes" /></label>
        <div className="flex flex-wrap justify-end gap-2"><Button type="button" variant="ghost" onClick={resetForm}>Clear</Button><Button type="submit" disabled={saving}>{saving ? <LoaderCircle className="size-4 animate-spin" /> : form.schedule_key ? <Edit3 className="size-4" /> : <Plus className="size-4" />}{saving ? "Saving…" : form.schedule_key ? "Save changes" : "Add schedule"}</Button></div>
      </form></CardContent>
    </Card>

    <Card>
      <CardHeader><div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center"><div><CardTitle>Weekly assignments</CardTitle><CardDescription>Confirmed schedules can be copied to Entry later. Pending conflicts stay out of Entry until approved.</CardDescription></div><Input className="sm:max-w-xs" value={search} onChange={event => setSearch(event.target.value)} placeholder="Search worker, Site, Cost Code…" /></div></CardHeader>
        <CardContent>{loading ? <div className="flex items-center gap-2 py-10 text-sm text-muted-foreground"><LoaderCircle className="size-4 animate-spin" />Loading schedule…</div> : visibleRows.length ? <div className="grid gap-3">{visibleRows.map(row => <div key={row.schedule_key} className={`rounded-xl border p-4 ${row.status === "pending_approval" ? "border-amber-300 bg-amber-50/50" : row.status === "rejected" || row.status === "cancelled" ? "opacity-60" : ""}`}><div className="flex flex-col gap-3 lg:flex-row lg:items-start"><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><strong>{displayDate(row.schedule_date, true)}</strong>{statusBadge(row.status)}{row.status === "pending_approval" && <AlertTriangle className="size-4 text-amber-600" />}</div><p className="mt-1 text-sm"><strong>{row.worker_name}</strong><span className="mx-2 text-muted-foreground">·</span>{row.site}</p><p className="mt-1 text-xs text-muted-foreground">Cost Code: {row.cost_code_names.length ? row.cost_code_names.join(", ") : "—"}{row.start_time && row.end_time ? ` · ${row.start_time}–${row.end_time}` : " · Time not set"}{row.notes ? ` · ${row.notes}` : ""}</p>{row.conflict_reason && <p className="mt-2 text-xs font-semibold text-amber-800">{row.conflict_reason}</p>}{row.submitted_by_name && <p className="mt-2 text-[11px] text-muted-foreground">Submitted by {row.submitted_by_name}{row.reviewed_by_name ? ` · reviewed by ${row.reviewed_by_name}` : ""}</p>}</div><div className="flex flex-wrap gap-2 lg:justify-end">{row.status === "pending_approval" && <><Button size="sm" variant="outline" disabled={reviewing === row.schedule_key} onClick={() => void review(row, "rejected")}><X className="size-4" />Reject</Button><Button size="sm" disabled={reviewing === row.schedule_key} onClick={() => void review(row, "approved")}><Check className="size-4" />Approve</Button></>}{row.status !== "cancelled" && row.status !== "rejected" && <><Button size="sm" variant="outline" onClick={() => editRow(row)}><Edit3 className="size-4" />Edit</Button><Button size="sm" variant="ghost" className="text-red-600 hover:text-red-700" disabled={reviewing === row.schedule_key} onClick={() => void cancel(row)}><X className="size-4" />Cancel</Button></>}</div></div></div>)}</div> : <div className="rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">No schedules for this week.</div>}</CardContent>
    </Card>

    <Dialog open={Boolean(pendingConflict)} onOpenChange={open => { if (!open && !submittingConflict) { setPendingConflict(null); setConflictRecipientIds([]) } }}>
      <DialogContent className="max-h-[90vh] max-w-4xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><AlertTriangle className="size-5 text-amber-600" />Schedule conflict found</DialogTitle>
          <DialogDescription>Nothing has been saved yet. Review both assignments, then select one or more Schedule Managers to request approval.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          {pendingConflict?.conflicts.map((conflict, index) => <div key={`${conflict.schedule_date}-${index}`} className="rounded-xl border border-amber-300 bg-amber-50/60 p-4">
            <p className="text-sm font-bold text-amber-950">{displayDate(conflict.schedule_date, true)}</p>
            <p className="mt-1 text-xs font-semibold text-amber-800">{conflict.reason}</p>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <div className="rounded-lg border border-blue-200 bg-white p-3"><Badge>Proposed</Badge><p className="mt-2 font-bold">{conflict.proposed.worker_name}</p><p className="text-sm">{conflict.proposed.site}</p><p className="mt-1 text-xs text-muted-foreground">Cost Code: {conflict.proposed.cost_code_names.map((name, codeIndex) => `${name}${conflict.proposed.cost_code_ids[codeIndex] ? ` (${conflict.proposed.cost_code_ids[codeIndex]})` : ""}`).join(", ") || "—"}</p><p className="text-xs text-muted-foreground">Time: {conflict.proposed.start_time && conflict.proposed.end_time ? `${conflict.proposed.start_time}–${conflict.proposed.end_time}` : "not set"}</p>{conflict.proposed.notes && <p className="mt-1 text-xs text-muted-foreground">Notes: {conflict.proposed.notes}</p>}</div>
              <div className="grid gap-2">{conflict.existing.map(existing => <div key={existing.schedule_key} className="rounded-lg border bg-white p-3"><Badge variant="warning">Existing</Badge><p className="mt-2 font-bold">{existing.worker_name}</p><p className="text-sm">{existing.site}</p><p className="mt-1 text-xs text-muted-foreground">Cost Code: {existing.cost_code_names.map((name, codeIndex) => `${name}${existing.cost_code_ids[codeIndex] ? ` (${existing.cost_code_ids[codeIndex]})` : ""}`).join(", ") || "—"}</p><p className="text-xs text-muted-foreground">Time: {existing.start_time && existing.end_time ? `${existing.start_time}–${existing.end_time}` : "not set"}</p>{existing.notes && <p className="mt-1 text-xs text-muted-foreground">Notes: {existing.notes}</p>}</div>)}</div>
            </div>
          </div>)}
          <div className="rounded-xl border border-blue-200 bg-blue-50/60 p-4">
            <div className="flex flex-wrap items-start justify-between gap-2"><div><div className="flex items-center gap-2 text-sm font-bold"><Bell className="size-4 text-blue-700" />Choose approval recipients</div><p className="mt-1 text-xs text-muted-foreground">Super Admins are always notified. Select one or more additional Schedule Managers.</p></div>{optionalManagers.length > 0 && <Button type="button" size="sm" variant="outline" onClick={() => setConflictRecipientIds(conflictRecipientIds.length === optionalManagers.length ? [] : optionalManagers.map(item => item.open_id))}>{conflictRecipientIds.length === optionalManagers.length ? "Clear managers" : "Select all managers"}</Button>}</div>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {requiredRecipients.map(recipient => <label key={recipient.open_id} className="flex items-center gap-2 rounded-lg border border-blue-200 bg-white px-3 py-2 text-xs"><input type="checkbox" checked disabled /><span><strong className="block">{recipient.name}{recipient.current ? " (you)" : ""}</strong><span className="text-muted-foreground">Super Admin · always notified</span></span></label>)}
              {optionalManagers.map(recipient => <label key={recipient.open_id} className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-xs ${conflictRecipientIds.includes(recipient.open_id) ? "border-blue-500 bg-blue-100" : "bg-white hover:border-blue-300"}`}><input type="checkbox" checked={conflictRecipientIds.includes(recipient.open_id)} onChange={() => toggleConflictRecipient(recipient.open_id)} /><span><strong className="block">{recipient.name}{recipient.current ? " (you)" : ""}</strong><span className="text-muted-foreground">Schedule Manager</span></span></label>)}
              {!notificationRecipients.length && <p className="text-xs text-red-700">No eligible approver is registered. Ask an administrator or Schedule Manager to sign in once.</p>}
              {notificationRecipients.length > 0 && !optionalManagers.length && <p className="text-xs text-amber-700">No additional Schedule Manager is available; the listed Super Admins will receive this request.</p>}
            </div>
          </div>
        </div>
        <div className="mt-2 flex justify-end gap-2"><Button variant="ghost" disabled={submittingConflict} onClick={() => { setPendingConflict(null); setConflictRecipientIds([]) }}>Cancel</Button><Button disabled={submittingConflict || !notificationRecipients.length || (optionalManagers.length > 0 && !conflictRecipientIds.length)} onClick={() => void submitConflictApproval()}>{submittingConflict ? <LoaderCircle className="size-4 animate-spin" /> : <Bell className="size-4" />}{submittingConflict ? "Sending…" : "Send approval request"}</Button></div>
      </DialogContent>
    </Dialog>
  </div>
}
