import { MapPin, Plus, Trash2, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input, Label } from "@/components/ui/input"
import type { CostCenter, WorkLocation } from "@/lib/types"

const blankLocation = (start_time = "08:30", end_time = "16:30"): WorkLocation => ({ name: "", hours: rangeHours(start_time, end_time), start_time, end_time, cost_centers: [] })

export function rangeHours(start: string, end: string): number | null {
  if (!start || !end) return null
  const [startHour, startMinute] = start.split(":").map(Number)
  const [endHour, endMinute] = end.split(":").map(Number)
  const minutes = endHour * 60 + endMinute - startHour * 60 - startMinute
  return minutes > 0 ? Math.round(minutes / 60 * 100) / 100 : null
}

function minutes(value: string): number | null {
  if (!value) return null
  const [hour, minute] = value.split(":").map(Number)
  return Number.isFinite(hour) && Number.isFinite(minute) ? hour * 60 + minute : null
}

function timeFromMinutes(value: number): string {
  const rounded = Math.round(value)
  if (rounded < 0 || rounded > 23 * 60 + 59) return ""
  return `${String(Math.floor(rounded / 60)).padStart(2, "0")}:${String(rounded % 60).padStart(2, "0")}`
}

export function cleanLocations(locations: WorkLocation[]) {
  return locations.filter(l => l.name.trim()).map(l => ({ name: l.name.trim(), start_time: l.start_time || "", end_time: l.end_time || "", hours: rangeHours(l.start_time, l.end_time), cost_centers: l.cost_centers || [] }))
}

export function LocationEditor({ value, onChange, suggestions, costCenters, disabled = false }: { value: WorkLocation[]; onChange: (v: WorkLocation[]) => void; suggestions: string[]; costCenters: CostCenter[]; disabled?: boolean }) {
  const rows = value.length ? value : [blankLocation()]
  const update = (index: number, next: Partial<WorkLocation>) => onChange(rows.map((r, i) => i === index ? { ...r, ...next } : r))
  const reconnectFollowing = (nextRows: WorkLocation[], index: number, oldEnd: string) => {
    const following = nextRows[index + 1]
    const newEnd = nextRows[index].end_time
    if (!following || newEnd === oldEnd || (following.start_time && following.start_time !== oldEnd)) return
    following.start_time = newEnd
    const worked = nextRows.slice(0, index + 1).reduce((sum, row) => sum + Number(rangeHours(row.start_time, row.end_time) || 0), 0)
    const remaining = Math.max(8 - worked, 0)
    const start = minutes(newEnd)
    following.end_time = start !== null && remaining > 0 ? timeFromMinutes(start + remaining * 60) : ""
    following.hours = rangeHours(following.start_time, following.end_time)
  }
  const updateTime = (index: number, field: "start_time" | "end_time", value: string) => {
    const nextRows = rows.map(row => ({ ...row }))
    const oldEnd = nextRows[index].end_time
    const currentHours = nextRows[index].hours
    nextRows[index][field] = value
    if (field === "start_time" && currentHours !== null && value) {
      const start = minutes(value)
      nextRows[index].end_time = start === null ? nextRows[index].end_time : timeFromMinutes(start + currentHours * 60)
      nextRows[index].hours = currentHours
    } else {
      nextRows[index].hours = rangeHours(nextRows[index].start_time, nextRows[index].end_time)
    }
    reconnectFollowing(nextRows, index, oldEnd)
    onChange(nextRows)
  }
  const updateHours = (index: number, raw: string) => {
    const nextRows = rows.map(row => ({ ...row }))
    const oldEnd = nextRows[index].end_time
    const hours = raw === "" ? null : Math.max(0, Number(raw))
    nextRows[index].hours = hours
    const start = minutes(nextRows[index].start_time)
    if (hours !== null && start !== null) nextRows[index].end_time = timeFromMinutes(start + hours * 60)
    else if (hours === null) nextRows[index].end_time = ""
    reconnectFollowing(nextRows, index, oldEnd)
    onChange(nextRows)
  }
  const addLocation = () => {
    const worked = rows.reduce((sum, row) => sum + Number(rangeHours(row.start_time, row.end_time) || 0), 0)
    const startTime = rows.at(-1)?.end_time || ""
    const start = minutes(startTime)
    const remaining = Math.max(8 - worked, 0)
    const endTime = start !== null && remaining > 0 ? timeFromMinutes(start + remaining * 60) : ""
    onChange([...rows, blankLocation(startTime, endTime)])
  }
  const findCenter = (raw: string, exact = false) => {
    const q = raw.trim().toLowerCase(); if (!q) return undefined
    const match = costCenters.find(c => c.id.toLowerCase() === q || c.name.toLowerCase() === q || `${c.name} (${c.id})`.toLowerCase() === q)
    return match || (!exact ? costCenters.find(c => c.name.toLowerCase().includes(q) || c.id.toLowerCase().includes(q)) : undefined)
  }
  const addCenter = (index: number, raw: string) => {
    const center = findCenter(raw)
    if (center && !rows[index].cost_centers.some(c => c.id === center.id)) update(index, { cost_centers: [...rows[index].cost_centers, center] })
  }
  return <div className="rounded-xl border bg-[#fbfcfc] p-3">
    <div className="mb-1 flex items-center justify-between"><Label className="flex items-center gap-2"><MapPin className="size-4 text-primary" /> Location, time and cost center</Label><span className="text-[11px] font-semibold text-amber-700">Cost center required · blank times = 8h day</span></div>
    <datalist id="location-options">{suggestions.map(x => <option value={x} key={x} />)}</datalist>
    <datalist id="center-options">{costCenters.map(c => <option value={`${c.name} (${c.id})`} key={c.id} />)}</datalist>
    {rows.map((row, index) => <div className="location-row" key={index}>
      <label className="field-label">Location<Input list="location-options" value={row.name} disabled={disabled} placeholder="e.g. 444 Pocatello" onChange={e => update(index, { name: e.target.value })} /></label>
      <label className="field-label">Start<Input type="time" value={row.start_time || ""} disabled={disabled} onChange={e => updateTime(index, "start_time", e.target.value)} /></label>
      <label className="field-label">End<Input type="time" value={row.end_time || ""} disabled={disabled} onChange={e => updateTime(index, "end_time", e.target.value)} /></label>
      <label className="field-label">Location hours<Input type="number" min="0" max="24" step=".25" value={row.hours ?? ""} disabled={disabled} placeholder="Day defaults to 8h" onChange={e=>updateHours(index,e.target.value)} /></label>
      <div className="field-label"><span>Cost centers</span><div className="flex min-h-9 flex-wrap items-center gap-1 rounded-lg border bg-white px-2 py-1.5">{row.cost_centers.map(c => <span key={c.id} className="flex items-center gap-1 rounded-md bg-accent px-2 py-1 text-[11px] font-semibold text-primary">{c.name} · {c.id}<button disabled={disabled} onClick={() => update(index, { cost_centers: row.cost_centers.filter(x => x.id !== c.id) })}><X className="size-3" /></button></span>)}<input disabled={disabled} list="center-options" className="min-w-28 flex-1 border-0 bg-transparent text-xs outline-none" placeholder="Search or select" onChange={e=>{if(findCenter(e.currentTarget.value,true)){addCenter(index,e.currentTarget.value);e.currentTarget.value=""}}} onBlur={e=>{addCenter(index,e.currentTarget.value);e.currentTarget.value=""}} onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addCenter(index, e.currentTarget.value); e.currentTarget.value = "" } }} /></div><small className="text-[10px] text-muted-foreground">Added centers appear as blue chips above.</small></div>
      <Button variant="ghost" size="icon" disabled={disabled || rows.length === 1} className="mt-5 text-muted-foreground hover:text-red-600" onClick={() => onChange(rows.filter((_, i) => i !== index))}><Trash2 className="size-4" /></Button>
    </div>)}
    <Button variant="ghost" size="sm" disabled={disabled} className="mt-3" onClick={addLocation}><Plus className="size-4" /> Add location</Button>
  </div>
}
