import { MapPin, Plus, Trash2, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input, Label } from "@/components/ui/input"
import type { CostCenter, WorkLocation } from "@/lib/types"

const blankLocation = (): WorkLocation => ({ name: "", hours: null, cost_centers: [] })

export function cleanLocations(locations: WorkLocation[]) {
  return locations.filter(l => l.name.trim()).map(l => ({ name: l.name.trim(), hours: l.hours == null || Number.isNaN(Number(l.hours)) ? null : Number(l.hours), cost_centers: l.cost_centers || [] }))
}

export function LocationEditor({ value, onChange, suggestions, costCenters, disabled = false }: { value: WorkLocation[]; onChange: (v: WorkLocation[]) => void; suggestions: string[]; costCenters: CostCenter[]; disabled?: boolean }) {
  const rows = value.length ? value : [blankLocation()]
  const update = (index: number, next: Partial<WorkLocation>) => onChange(rows.map((r, i) => i === index ? { ...r, ...next } : r))
  const addCenter = (index: number, raw: string) => {
    const q = raw.trim().toLowerCase(); if (!q) return
    const center = costCenters.find(c => c.id.toLowerCase() === q || c.name.toLowerCase() === q || `${c.name} (${c.id})`.toLowerCase() === q) || costCenters.find(c => c.name.toLowerCase().includes(q) || c.id.toLowerCase().includes(q))
    if (center && !rows[index].cost_centers.some(c => c.id === center.id)) update(index, { cost_centers: [...rows[index].cost_centers, center] })
  }
  return <div className="rounded-xl border bg-[#fbfcfc] p-3">
    <div className="mb-1 flex items-center justify-between"><Label className="flex items-center gap-2"><MapPin className="size-4 text-primary" /> Location and cost center</Label><span className="text-[11px] font-semibold text-amber-700">Cost center required</span></div>
    <datalist id="location-options">{suggestions.map(x => <option value={x} key={x} />)}</datalist>
    <datalist id="center-options">{costCenters.map(c => <option value={`${c.name} (${c.id})`} key={c.id} />)}</datalist>
    {rows.map((row, index) => <div className="location-row" key={index}>
      <label className="field-label">Location<Input list="location-options" value={row.name} disabled={disabled} placeholder="e.g. 444 Pocatello" onChange={e => update(index, { name: e.target.value })} /></label>
      <label className="field-label">Hours<Input type="number" min="0" max="24" step=".25" value={row.hours ?? ""} disabled={disabled} placeholder="Auto" onChange={e => update(index, { hours: e.target.value === "" ? null : Number(e.target.value) })} /></label>
      <div className="field-label"><span>Cost centers</span><div className="flex min-h-9 flex-wrap items-center gap-1 rounded-lg border bg-white px-2 py-1.5">{row.cost_centers.map(c => <span key={c.id} className="flex items-center gap-1 rounded-md bg-accent px-2 py-1 text-[11px] font-semibold text-primary">{c.name} · {c.id}<button disabled={disabled} onClick={() => update(index, { cost_centers: row.cost_centers.filter(x => x.id !== c.id) })}><X className="size-3" /></button></span>)}<input disabled={disabled} list="center-options" className="min-w-28 flex-1 border-0 bg-transparent text-xs outline-none" placeholder="Search, press Enter" onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addCenter(index, e.currentTarget.value); e.currentTarget.value = "" } }} /></div></div>
      <Button variant="ghost" size="icon" disabled={disabled || rows.length === 1} className="mt-5 text-muted-foreground hover:text-red-600" onClick={() => onChange(rows.filter((_, i) => i !== index))}><Trash2 className="size-4" /></Button>
    </div>)}
    <Button variant="ghost" size="sm" disabled={disabled} className="mt-3" onClick={() => onChange([...rows, blankLocation()])}><Plus className="size-4" /> Add location</Button>
  </div>
}
