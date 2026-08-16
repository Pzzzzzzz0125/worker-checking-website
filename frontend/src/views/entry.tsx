import { useEffect, useMemo, useState } from "react"
import { AlertTriangle, Check, ChevronDown, ChevronLeft, ChevronRight, Clipboard, Copy, LoaderCircle, Plus, RotateCcw, Save, Search, Trash2, Users, X } from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { LocationEditor, cleanLocations, rangeHours } from "@/components/location-editor"
import { api, postJSON } from "@/lib/api"
import type { Bootstrap, WorkLocation, WorkRecord, Worker } from "@/lib/types"
import { compactNumber, displayDate, initials, localISO } from "@/lib/utils"

type HourSource = "calculated" | "manual"
type Editable = WorkRecord & {
  dirty: boolean
  existing: boolean
  expanded?: boolean
  total_hours_source: HourSource
  overtime_source: HourSource
  override_reason: string
}
type WorkerPeriod = "month" | "1" | "2"
const blankLocation = (): WorkLocation => ({ name: "", hours: 8, start_time: "08:30", end_time: "16:30", cost_centers: [] })

const roundHours = (value: number) => Math.round(value * 100) / 100
function locationHoursSum(locations: WorkLocation[]) {
  return roundHours(locations.reduce((sum, location) => {
    const hours = Number(location.hours)
    return sum + (Number.isFinite(hours) && hours >= 0 ? hours : 0)
  }, 0))
}
function normalize(raw: any, date: string): Editable {
  const locations: WorkLocation[] = raw.locations?.length
    ? raw.locations.map((location: any) => ({
        ...location,
        start_time: location.start_time || "",
        end_time: location.end_time || "",
        hours: location.hours ?? rangeHours(location.start_time || "", location.end_time || ""),
        cost_centers: location.cost_centers || [],
      }))
    : [blankLocation()]
  const locationSum = locationHoursSum(locations)
  const total = Number(raw.total_hours ?? (locationSum || 8))
  const calculatedOvertime = Math.max(total - 8, 0)
  const recordedOvertime = Number(raw.overtime_hours ?? calculatedOvertime)
  const inferredTotalSource: HourSource = Math.abs(total - locationSum) > 0.01 ? "manual" : "calculated"
  const inferredOvertimeSource: HourSource = Math.abs(recordedOvertime - calculatedOvertime) > 0.01 ? "manual" : "calculated"
  return {
    worker_id: raw.worker_id,
    worker_name: raw.worker_name,
    work_date: raw.work_date || date,
    status: raw.status || "worked",
    total_hours: total,
    overtime_hours: recordedOvertime,
    location_hours_sum: Number(raw.location_hours_sum ?? locationSum),
    total_hours_source: raw.total_hours_source === "manual" ? "manual" : raw.total_hours_source === "calculated" ? "calculated" : inferredTotalSource,
    hours_difference: Number(raw.hours_difference ?? roundHours(total - locationSum)),
    calculated_overtime_hours: Number(raw.calculated_overtime_hours ?? calculatedOvertime),
    overtime_source: raw.overtime_source === "manual" ? "manual" : raw.overtime_source === "calculated" ? "calculated" : inferredOvertimeSource,
    override_reason: raw.override_reason || "",
    extra_pay: raw.extra_pay || 0,
    start_time: "",
    end_time: "",
    notes: raw.notes || "",
    locations,
    cost_centers: raw.cost_centers || [],
    dirty: false,
    existing: !!raw.day_id || !!raw.id,
  }
}
const clearedRecord = (record: Editable): Editable => ({...normalize({worker_id:record.worker_id,worker_name:record.worker_name,work_date:record.work_date,status:"worked",total_hours:8,overtime_hours:0,extra_pay:0,locations:[]},record.work_date),expanded:record.expanded})
function minutes(value:string){const [hour,minute]=value.split(":").map(Number);return hour*60+minute}
function timeResult(locations:WorkLocation[]){
  const rows=locations.filter(x=>x.name.trim()||x.start_time||x.end_time||x.hours!==null)
  const entered=rows.filter(x=>x.start_time||x.end_time)
  if(!entered.length)return {error:""}
  if(entered.length!==rows.length||entered.some(x=>!x.start_time||!x.end_time))return {error:"Time conflict: enter both Start and End for every site, or leave all site times blank."}
  const ranges=rows.map((x,index)=>({name:x.name.trim()||`Site ${index+1}`,start:minutes(x.start_time),end:minutes(x.end_time),hours:x.hours}))
  const invalid=ranges.find(x=>x.end<=x.start)
  if(invalid)return {error:`Time conflict: ${invalid.name} must end after it starts.`}
  const mismatched=ranges.find(x=>x.hours!==null&&Math.abs((x.end-x.start)/60-Number(x.hours))>.01)
  if(mismatched)return {error:`Time conflict: ${mismatched.name}'s time range does not match its Site hours.`}
  const sorted=[...ranges].sort((a,b)=>a.start-b.start)
  for(let i=1;i<sorted.length;i++)if(sorted[i].start<sorted[i-1].end)return {error:`Time conflict: ${sorted[i-1].name} overlaps ${sorted[i].name}.`}
  return {error:""}
}
function payload(r: Editable) {
  const locations=cleanLocations(r.locations)
  return {
    worker_id:r.worker_id,
    status:r.status,
    total_hours:r.status==="worked"?Number(r.total_hours??8):r.status==="sick_leave"?8:0,
    overtime_hours:r.status==="worked"?Number(r.overtime_hours||0):0,
    location_hours_sum:r.status==="worked"?locationHoursSum(locations):0,
    total_hours_source:r.status==="worked"?r.total_hours_source:"calculated",
    hours_difference:r.status==="worked"?roundHours(Number(r.total_hours)-locationHoursSum(locations)):0,
    calculated_overtime_hours:r.status==="worked"?Math.max(Number(r.total_hours)-8,0):0,
    overtime_source:r.status==="worked"?r.overtime_source:"calculated",
    override_reason:r.status==="worked"?r.override_reason:"",
    extra_pay:r.status==="worked"?Number(r.extra_pay||0):0,
    start_time:"",
    end_time:"",
    locations:r.status==="worked"?locations:[],
    cost_centers:r.status==="worked"?Array.from(new Map(locations.flatMap(l=>l.cost_centers).map(c=>[c.id,c])).values()):[],
    notes:r.notes||"",
  }
}
function validate(r:Editable){
  const locations=cleanLocations(r.locations)
  if(r.status==="worked"&&!locations.length)return "Add at least one site."
  const missingCenter=locations.find(x=>!x.cost_centers.length)
  if(r.status==="worked"&&missingCenter)return `Choose a cost code for ${missingCenter.name}.`
  if(r.status!=="worked")return ""
  const invalidHours=locations.find(x=>x.hours===null||!Number.isFinite(Number(x.hours))||Number(x.hours)<0||Number(x.hours)>24)
  if(invalidHours)return `Enter valid Site hours for ${invalidHours.name}.`
  const timing=timeResult(locations)
  if(timing.error)return timing.error
  const locationSum=locationHoursSum(locations),total=Number(r.total_hours??8),overtime=Number(r.overtime_hours||0)
  if(!Number.isFinite(total)||total<0||total>24)return "Total hours must be between 0 and 24."
  if(!Number.isFinite(overtime)||overtime<0||overtime>total)return "Overtime must be between 0 and Total hours."
  const totalMismatch=Math.abs(locationSum-total)>.01
  const expected=Math.max(total-8,0)
  const overtimeMismatch=Math.abs(expected-overtime)>.01
  if(r.total_hours_source!=="manual"&&totalMismatch)return "Calculated Total hours must match the Site hours sum."
  if(r.overtime_source!=="manual"&&overtimeMismatch)return "Calculated Overtime must match Total hours."
  if((totalMismatch||overtimeMismatch)&&!r.override_reason.trim())return "Enter an override reason before saving mismatched Total or Overtime hours."
  return ""
}
function cellText(r:Editable){if(r.status==="off")return "off";if(r.status==="sick_leave")return "sick leave";const loc=cleanLocations(r.locations).map(l=>`${l.name}${l.hours==null?"":`(${compactNumber(l.hours)})`}`).join(";");const ot=Number(r.overtime_hours||Math.max(0,Number(r.total_hours)-8));return `${loc}${ot?`, ot ${compactNumber(ot)}h`:""}${Number(r.extra_pay)?`, ex $${compactNumber(r.extra_pay)}`:""}`||"—"}
function moveMonth(value:string,delta:number){const [year,month]=value.split("-").map(Number);const next=new Date(year,month-1+delta,1);return `${next.getFullYear()}-${String(next.getMonth()+1).padStart(2,"0")}`}
function workerPeriodLabel(period:WorkerPeriod){return period==="month"?"Full month":period==="1"?"1–15":"16–end"}
function inWorkerPeriod(workDate:string,period:WorkerPeriod){const day=Number(workDate.slice(8,10));return period==="month"||period==="1"&&day<=15||period==="2"&&day>=16}
function workedPatch(record:Editable, expanded=false):Partial<Editable>{
  if(record.status==="worked")return {status:"worked",expanded:expanded||record.expanded}
  const locations=record.locations.length?record.locations:[blankLocation()]
  const total=locationHoursSum(locations)||8
  const overtime=Math.max(total-8,0)
  return {
    status:"worked",
    locations,
    expanded:expanded||record.expanded,
    location_hours_sum:total,
    total_hours:total,
    total_hours_source:"calculated",
    hours_difference:0,
    calculated_overtime_hours:overtime,
    overtime_hours:overtime,
    overtime_source:"calculated",
    override_reason:"",
  }
}
function offPatch():Partial<Editable>{
  return {
    status:"off",
    total_hours:0,
    location_hours_sum:0,
    total_hours_source:"calculated",
    hours_difference:0,
    calculated_overtime_hours:0,
    overtime_hours:0,
    overtime_source:"calculated",
    override_reason:"",
  }
}
function sickLeavePatch():Partial<Editable>{
  return {
    status:"sick_leave",
    total_hours:8,
    location_hours_sum:0,
    total_hours_source:"calculated",
    hours_difference:0,
    calculated_overtime_hours:0,
    overtime_hours:0,
    overtime_source:"calculated",
    override_reason:"",
    extra_pay:0,
  }
}

function RecordEditor({ record, update, bootstrap }: { record: Editable; update: (patch: Partial<Editable>)=>void; bootstrap: Bootstrap }) {
 const worked=record.status==="worked"
 const locationSum=locationHoursSum(record.locations)
 const total=Number(record.total_hours||0)
 const overtime=Number(record.overtime_hours||0)
 const calculatedOvertime=Math.max(total-8,0)
 const totalMismatch=Math.abs(total-locationSum)>.01
 const overtimeMismatch=Math.abs(overtime-calculatedOvertime)>.01
 const changeLocations=(locations:WorkLocation[])=>{
   const nextSum=locationHoursSum(locations)
   if(record.total_hours_source==="manual"){
     const nextCalculatedOvertime=Math.max(total-8,0)
     update({
       locations,
       location_hours_sum:nextSum,
       hours_difference:roundHours(total-nextSum),
       calculated_overtime_hours:nextCalculatedOvertime,
       overtime_hours:record.overtime_source==="manual"?overtime:nextCalculatedOvertime,
     })
     return
   }
   const nextOvertime=Math.max(nextSum-8,0)
   update({
     locations,
     location_hours_sum:nextSum,
     total_hours:nextSum,
     total_hours_source:"calculated",
     hours_difference:0,
     calculated_overtime_hours:nextOvertime,
     overtime_hours:record.overtime_source==="manual"?overtime:nextOvertime,
   })
 }
 const changeTotal=(nextTotal:number)=>{
   const source:HourSource=Math.abs(nextTotal-locationSum)>.01?"manual":"calculated"
   const nextOvertime=Math.max(nextTotal-8,0)
   update({
     total_hours:nextTotal,
     total_hours_source:source,
     hours_difference:roundHours(nextTotal-locationSum),
     calculated_overtime_hours:nextOvertime,
     overtime_hours:nextOvertime,
     overtime_source:"calculated",
   })
 }
 const changeOvertime=(nextOvertime:number)=>update({
   overtime_hours:nextOvertime,
   calculated_overtime_hours:calculatedOvertime,
   overtime_source:Math.abs(nextOvertime-calculatedOvertime)>.01?"manual":"calculated",
 })
 const resetTotal=()=>{
   const nextOvertime=Math.max(locationSum-8,0)
   update({
     total_hours:locationSum,
     total_hours_source:"calculated",
     hours_difference:0,
     calculated_overtime_hours:nextOvertime,
     overtime_hours:nextOvertime,
     overtime_source:"calculated",
     override_reason:"",
   })
 }
 const resetOvertime=()=>update({overtime_hours:calculatedOvertime,overtime_source:"calculated"})
 const statusSelector=<div className="flex w-fit rounded-lg bg-muted p-1"><Button size="sm" variant={record.status==="worked"?"default":"ghost"} onClick={()=>update(workedPatch(record,true))}>Worked</Button><Button size="sm" variant={record.status==="sick_leave"?"default":"ghost"} onClick={()=>update(sickLeavePatch())}>Sick leave</Button><Button size="sm" variant={record.status==="off"?"default":"ghost"} onClick={()=>update(offPatch())}>Off</Button></div>
 if(record.status==="sick_leave")return <div className="mt-4 grid gap-4 border-t pt-4">
   {statusSelector}
   <div className="rounded-xl border border-blue-200 bg-blue-50 p-4"><strong className="block text-sm text-blue-950">Paid sick leave · 8 hours</strong><p className="mt-1 text-xs text-blue-800">Included as straight-time payroll hours. It does not require a Site or Cost Code and does not create overtime.</p></div>
   <label className="field-label">Notes<Input value={record.notes} onChange={e=>update({notes:e.target.value})} placeholder="Optional sick leave note"/></label>
   <div className="flex items-center gap-2 rounded-lg bg-slate-900 px-3 py-2 text-xs text-white"><span className="text-slate-400">Normalized cell</span><code>sick leave</code></div>
 </div>
 return <div className="mt-4 grid gap-4 border-t pt-4">
   {statusSelector}
   <LocationEditor value={record.locations} onChange={changeLocations} suggestions={bootstrap.locations} costCenters={bootstrap.cost_centers} disabled={!worked}/>
   <div className="grid gap-3 rounded-xl border bg-slate-50 p-3 sm:grid-cols-3">
     <div><span className="text-xs font-semibold text-muted-foreground">Site hours sum</span><strong className="mt-1 block text-lg">{compactNumber(locationSum)}h</strong></div>
     <div><span className="text-xs font-semibold text-muted-foreground">Regular hours</span><strong className="mt-1 block text-lg">{compactNumber(Math.max(total-overtime,0))}h</strong></div>
     <div><span className="text-xs font-semibold text-muted-foreground">Calculated overtime</span><strong className="mt-1 block text-lg">{compactNumber(calculatedOvertime)}h</strong></div>
   </div>
   <div className="entry-grid">
     <label className="field-label">Total hours <Badge variant={record.total_hours_source==="manual"?"warning":"secondary"}>{record.total_hours_source==="manual"?"Manual override":"Auto"}</Badge><Input type="number" min="0" max="24" step=".5" disabled={!worked} value={record.total_hours} onChange={e=>changeTotal(Number(e.target.value))}/></label>
     <label className="field-label">Overtime hours <Badge variant={record.overtime_source==="manual"?"warning":"secondary"}>{record.overtime_source==="manual"?"Manual override":"Auto"}</Badge><Input type="number" min="0" max="24" step=".5" disabled={!worked} value={record.overtime_hours||0} onChange={e=>changeOvertime(Number(e.target.value))}/></label>
     <label className="field-label">Extra pay<Input type="number" min="0" step="1" disabled={!worked} value={record.extra_pay} onChange={e=>update({extra_pay:Number(e.target.value)})}/></label>
   </div>
   {(totalMismatch||overtimeMismatch)&&<div className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
     <div className="flex items-start gap-2"><AlertTriangle className="mt-0.5 size-4 shrink-0"/><div className="flex-1">{totalMismatch&&<p>Site hours add up to {compactNumber(locationSum)}h, but Total Hours is {compactNumber(total)}h. Difference: {total>locationSum?"+":""}{compactNumber(total-locationSum)}h.</p>}{overtimeMismatch&&<p>Calculated overtime is {compactNumber(calculatedOvertime)}h, but recorded Overtime is {compactNumber(overtime)}h.</p>}</div></div>
     <div className="mt-3 flex flex-wrap gap-2">{totalMismatch&&<Button type="button" size="sm" variant="outline" onClick={resetTotal}><RotateCcw className="size-4"/>Reset to site sum</Button>}{overtimeMismatch&&<Button type="button" size="sm" variant="outline" onClick={resetOvertime}><RotateCcw className="size-4"/>Reset overtime</Button>}</div>
     <label className="field-label mt-3">Override reason<Input value={record.override_reason} onChange={e=>update({override_reason:e.target.value})} placeholder="Required to save a mismatch, e.g. Supervisor confirmed"/></label>
   </div>}
   <p className="text-xs text-muted-foreground">Site hours are the normal source of truth: changing a site recalculates Total and Overtime. Editing Total or Overtime creates a manual override without silently changing site allocations. Time ranges must still match each site's hours.</p>
   <label className="field-label">Notes<Input disabled={!worked} value={record.notes} onChange={e=>update({notes:e.target.value})} placeholder="Optional"/></label>
   <div className="flex items-center gap-2 rounded-lg bg-slate-900 px-3 py-2 text-xs text-white"><span className="text-slate-400">Normalized cell</span><code className="overflow-hidden text-ellipsis">{cellText(record)}</code></div>
 </div>
}

export function DailyEntryView({ bootstrap }: { bootstrap: Bootstrap }) {
 const [date,setDate]=useState(localISO());const [records,setRecords]=useState<Editable[]>([]);const [search,setSearch]=useState("");const [copied,setCopied]=useState<Editable|null>(null);const draftKey=`speed-daily-draft:${date}`
 useEffect(()=>{const warn=(event:BeforeUnloadEvent)=>{if(records.some(record=>record.dirty)){event.preventDefault();event.returnValue=""}};window.addEventListener("beforeunload",warn);return()=>window.removeEventListener("beforeunload",warn)},[records])
 const load=async()=>{try{const data=await api<any>(`/api/day?date=${date}`);let rows=data.workers.map((x:any)=>normalize(x,date));try{const drafts=JSON.parse(localStorage.getItem(draftKey)||"[]");rows=rows.map((r:Editable)=>{const d=drafts.find((x:any)=>x.worker_id===r.worker_id);return d?{...r,...d,dirty:true}:r})}catch{}setRecords(rows)}catch(e){toast.error(String(e))}};useEffect(()=>{void load()},[date])
 const setRow=(id:number,patch:Partial<Editable>)=>setRecords(old=>{const next=old.map(r=>r.worker_id===id?{...r,...patch,dirty:true}:r);try{localStorage.setItem(draftKey,JSON.stringify(next.filter(r=>r.dirty)))}catch{}return next})
 const save=async(rows:Editable[])=>{for(const r of rows){const error=validate(r);if(error){toast.error(`${r.worker_name}: ${error}`);return}}try{await postJSON("/api/day",{date,records:rows.map(payload)});setRecords(old=>{const next=old.map(r=>rows.some(x=>x.worker_id===r.worker_id)?{...r,dirty:false,existing:true}:r);const remaining=next.filter(r=>r.dirty);try{remaining.length?localStorage.setItem(draftKey,JSON.stringify(remaining)):localStorage.removeItem(draftKey)}catch{}return next});toast.success(`Saved ${rows.length} ${rows.length===1?"worker":"workers"}.`)}catch(e){toast.error(String(e))}}
 const clearRecord=async(r:Editable)=>{if(!window.confirm(`Clear ${r.worker_name}'s record for ${displayDate(date,true)}? This deletes the saved Lark record.`))return;try{if(r.existing)await postJSON("/api/day/clear",{worker_id:r.worker_id,date});setRecords(old=>{const next=old.map(item=>item.worker_id===r.worker_id?clearedRecord(item):item);const remaining=next.filter(item=>item.dirty);try{remaining.length?localStorage.setItem(draftKey,JSON.stringify(remaining)):localStorage.removeItem(draftKey)}catch{}return next});toast.success(`${r.worker_name}'s record was cleared.`)}catch(e){toast.error(String(e))}}
 const visible=records.filter(r=>r.worker_name?.toLowerCase().includes(search.toLowerCase()));const dirty=records.filter(r=>r.dirty)
 return <div className="page"><div className="mb-6 flex flex-col justify-between gap-4 sm:flex-row sm:items-end"><div><h1 className="page-title">Daily entry</h1><p className="page-subtitle">Choose one day, then update every worker who worked that day.</p></div><div className="flex w-full gap-2 sm:w-auto"><Button variant="outline" size="icon" className="shrink-0" onClick={()=>{const d=new Date(`${date}T12:00`);d.setDate(d.getDate()-1);setDate(localISO(d))}}><ChevronLeft className="size-4"/></Button><Input className="min-w-0 flex-1 sm:w-40" type="date" value={date} onChange={e=>setDate(e.target.value)}/><Button variant="outline" size="icon" className="shrink-0" onClick={()=>{const d=new Date(`${date}T12:00`);d.setDate(d.getDate()+1);setDate(localISO(d))}}><ChevronRight className="size-4"/></Button></div></div>
 <div className="metric-grid mb-5"><Mini label="Worked" value={records.filter(r=>r.status==="worked").length}/><Mini label="Sick leave" value={records.filter(r=>r.status==="sick_leave").length}/><Mini label="Off" value={records.filter(r=>r.status==="off").length}/><Mini label="Paid hours" value={compactNumber(records.filter(r=>r.status==="worked"||r.status==="sick_leave").reduce((a,r)=>a+Number(r.total_hours),0))}/><Mini label="Unsaved" value={dirty.length}/></div>
 <Card><CardHeader className="!flex-col justify-between sm:!flex-row sm:items-center"><div><CardTitle>Workers for {displayDate(date,true)}</CardTitle><CardDescription>Drafts are kept in this browser until saved.</CardDescription></div><div className="relative w-full sm:max-w-xs"><Search className="absolute left-3 top-3 size-4 text-muted-foreground"/><Input className="pl-9" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Find worker…"/></div></CardHeader><CardContent className="grid gap-3">{visible.map(r=><Card className={r.dirty?"border-amber-300":"shadow-none"} key={r.worker_id}><div className="p-4"><div className="flex flex-wrap items-center gap-3"><span className="avatar">{initials(r.worker_name)}</span><strong className="mr-auto">{r.worker_name}</strong><div className="flex rounded-lg bg-muted p-1"><Button size="sm" variant={r.status==="worked"?"default":"ghost"} onClick={()=>setRow(r.worker_id,workedPatch(r))}>Worked</Button><Button size="sm" variant={r.status==="sick_leave"?"default":"ghost"} onClick={()=>setRow(r.worker_id,sickLeavePatch())}>Sick leave</Button><Button size="sm" variant={r.status==="off"?"default":"ghost"} onClick={()=>setRow(r.worker_id,offPatch())}>Off</Button></div><Button size="sm" variant="ghost" onClick={()=>{setCopied(structuredClone(r));toast.success(`Copied ${r.worker_name}`)}}><Copy className="size-4"/>Copy</Button><Button size="sm" variant="ghost" disabled={!copied} onClick={()=>copied&&setRow(r.worker_id,{...structuredClone(copied),worker_id:r.worker_id,worker_name:r.worker_name,dirty:true})}><Clipboard className="size-4"/>Paste</Button><Button size="sm" disabled={!r.dirty} onClick={()=>save([r])}><Save className="size-4"/>Save</Button><Button size="sm" variant="ghost" className="text-red-600 hover:text-red-700" onClick={()=>void clearRecord(r)}><Trash2 className="size-4"/>Clear record</Button><Button variant="ghost" size="icon" onClick={()=>setRow(r.worker_id,{expanded:!r.expanded})}><ChevronDown className={`size-4 transition ${r.expanded?"rotate-180":""}`}/></Button></div>{r.expanded&&<RecordEditor record={r} bootstrap={bootstrap} update={p=>setRow(r.worker_id,p)}/>}</div></Card>)}</CardContent></Card>
 {dirty.length>0&&<div className="fixed bottom-20 right-5 z-40 flex items-center gap-4 rounded-2xl border bg-white p-3 pl-5 shadow-xl md:bottom-6"><span className="text-sm"><strong>{dirty.length}</strong> unsaved · draft protected</span><Button onClick={()=>save(dirty)}><Save className="size-4"/>Save all</Button></div>}</div>
}
function Mini({label,value}:{label:string;value:string|number}){return <Card><CardContent className="!pt-5"><p className="text-xs font-semibold text-muted-foreground">{label}</p><strong className="mt-1 block text-2xl">{value}</strong></CardContent></Card>}

function isoDateRange(start: string, end: string) {
  if (!start || !end || start > end) return []
  const dates: string[] = []
  const cursor = new Date(`${start}T12:00:00`)
  const last = new Date(`${end}T12:00:00`)
  while (cursor <= last && dates.length <= 366) {
    dates.push(localISO(cursor))
    cursor.setDate(cursor.getDate() + 1)
  }
  return dates
}

export function WorkerEntryView({ bootstrap }: { bootstrap: Bootstrap }) {
 const today=localISO();const [workerName,setWorkerName]=useState("");const [month,setMonth]=useState(today.slice(0,7));const [period,setPeriod]=useState<WorkerPeriod>("month");const [data,setData]=useState<any>(null);const [selected,setSelected]=useState<Set<string>>(new Set());const [copyOpen,setCopyOpen]=useState(false);const [targets,setTargets]=useState<number[]>([]);const [targetSearch,setTargetSearch]=useState("");const [copyMode,setCopyMode]=useState<"same"|"range">("same");const [targetStart,setTargetStart]=useState("");const [targetEnd,setTargetEnd]=useState("");const [saving,setSaving]=useState(false);const worker=useMemo(()=>bootstrap.workers.find(w=>w.name.toLowerCase()===workerName.toLowerCase())||bootstrap.workers.find(w=>w.name.toLowerCase().includes(workerName.toLowerCase())),[workerName,bootstrap])
 const draftKey=data?`speed-worker-draft:${data.worker.id}:${data.month}`:""
 const load=async()=>{if(!worker)return toast.error("Choose a worker from the suggestions.");try{const x=await api<any>(`/api/worker-month?worker_id=${worker.id}&month=${month}`);let days=x.days.map((d:any)=>normalize({...d,worker_id:worker.id,worker_name:worker.name},d.work_date));try{const drafts=JSON.parse(localStorage.getItem(`speed-worker-draft:${worker.id}:${month}`)||"[]");days=days.map((day:Editable)=>{const draft=drafts.find((item:any)=>item.work_date===day.work_date);return draft?{...day,...draft,dirty:true}:day})}catch{}setData({...x,days});setSelected(new Set())}catch(e){toast.error(String(e))}}
 useEffect(()=>{if(!data||!draftKey)return;const drafts=data.days.filter((day:Editable)=>day.dirty);try{if(drafts.length)localStorage.setItem(draftKey,JSON.stringify(drafts));else localStorage.removeItem(draftKey)}catch{}},[data,draftKey])
 useEffect(()=>{const warn=(event:BeforeUnloadEvent)=>{if(data?.days.some((day:Editable)=>day.dirty)){event.preventDefault();event.returnValue=""}};window.addEventListener("beforeunload",warn);return()=>window.removeEventListener("beforeunload",warn)},[data])
 const setDay=(date:string,patch:Partial<Editable>)=>setData((d:any)=>({...d,days:d.days.map((r:Editable)=>r.work_date===date?{...r,...patch,dirty:true}:r)}));const save=async(rows:Editable[])=>{for(const r of rows){const error=validate(r);if(error)return toast.error(`${displayDate(r.work_date)}: ${error}`)}setSaving(true);try{await postJSON("/api/worker-days",{worker_id:data.worker.id,records:rows.map(r=>({date:r.work_date,...payload(r)}))});setData((d:any)=>({...d,days:d.days.map((r:Editable)=>rows.some(x=>x.work_date===r.work_date)?{...r,dirty:false,existing:true}:r)}));toast.success(`Saved ${rows.length} edited ${rows.length===1?"day":"days"}.`)}catch(e){toast.error(String(e))}finally{setSaving(false)}}
 const clearDay=async(r:Editable)=>{if(!window.confirm(`Clear ${data.worker.name}'s record for ${displayDate(r.work_date,true)}? This deletes the saved record.`))return;try{if(r.existing)await postJSON("/api/day/clear",{worker_id:data.worker.id,date:r.work_date});setData((d:any)=>({...d,days:d.days.map((item:Editable)=>item.work_date===r.work_date?clearedRecord(item):item)}));setSelected((selected:Set<string>)=>{const next=new Set(selected);next.delete(r.work_date);return next});toast.success(`Record for ${displayDate(r.work_date,true)} was cleared.`)}catch(e){toast.error(String(e))}}
 const openCopy=()=>{const dates=[...selected].sort();const first=dates[0]||month+"-01";setCopyMode("same");setTargetStart(first);setTargetEnd(first);setTargets([]);setTargetSearch("");setCopyOpen(true)}
 const changeCopyMode=(mode:"same"|"range")=>{setCopyMode(mode);setTargets(mode==="range"&&data?.worker?.id?[data.worker.id]:[])}
 const targetDates=copyMode==="same"?[...selected].sort():isoDateRange(targetStart,targetEnd);const sourceRows=data?.days.filter((day:Editable)=>selected.has(day.work_date))||[]
 const sameWorkerSameDate=!!data?.worker?.id&&targets.includes(data.worker.id)&&targetDates.some(date=>selected.has(date));const copy=async()=>{if(!sourceRows.length)return toast.error("Select at least one source day.");if(!targets.length)return toast.error("Select at least one target worker.");if(!targetDates.length)return toast.error("Choose at least one target date.");if(sameWorkerSameDate)return toast.error("You cannot copy a Worker to the same Worker on the same date. Choose a different target date.");try{const result:any=await postJSON("/api/worker-days/copy",{source_worker_id:data.worker.id,target_worker_ids:targets,target_dates:targetDates,records:sourceRows.map((r:Editable)=>({date:r.work_date,...payload(r)}))});toast.success(`Copied ${result.days} ${result.days===1?"day":"days"} to ${result.target_workers.length} workers.`);setCopyOpen(false);setTargetSearch("");setTargets([]);await load()}catch(e){toast.error(String(e))}}
 const periodDays=(data?.days||[]).filter((r:Editable)=>inWorkerPeriod(r.work_date,period));const dirtyDays:Editable[]=(data?.days||[]).filter((r:Editable)=>r.dirty)
 useEffect(()=>{setSelected(selected=>new Set([...selected].filter(date=>inWorkerPeriod(date,period))))},[period])
 const allSelected=!!periodDays.length&&selected.size===periodDays.length;const toggleAll=()=>setSelected(allSelected?new Set():new Set<string>(periodDays.map((r:Editable)=>r.work_date)))
 const copyTargets=bootstrap.workers.filter(w=>w.name.toLowerCase().includes(targetSearch.trim().toLowerCase()));const shownTargets=copyTargets;const selectableShownTargets=shownTargets.filter(w=>!(copyMode==="same"&&w.id===data?.worker?.id));const allShownSelected=selectableShownTargets.length>0&&selectableShownTargets.every(w=>targets.includes(w.id));const toggleShownTargets=()=>setTargets(current=>allShownSelected?current.filter(id=>!selectableShownTargets.some(w=>w.id===id)):Array.from(new Set([...current,...selectableShownTargets.map(w=>w.id)])))
 return <div className="page"><div className="mb-6"><h1 className="page-title">Worker entry</h1><p className="page-subtitle">Choose one worker and record multiple days in a month. Draft edits are saved in this browser automatically.</p></div><Card className="mb-5"><CardContent className="flex flex-wrap items-end gap-3 !pt-5"><label className="field-label min-w-64 flex-1">Worker<Input list="workers" value={workerName} onChange={e=>setWorkerName(e.target.value)} placeholder="Search worker name"/></label><div className="flex items-end gap-2"><Button variant="outline" size="icon" onClick={()=>setMonth(value=>moveMonth(value,-1))}><ChevronLeft className="size-4"/></Button><label className="field-label">Month<Input type="month" value={month} onChange={e=>setMonth(e.target.value)}/></label><Button variant="outline" size="icon" onClick={()=>setMonth(value=>moveMonth(value,1))}><ChevronRight className="size-4"/></Button></div><div className="flex rounded-xl bg-muted p-1">{(["month","1","2"] as WorkerPeriod[]).map(value=><Button key={value} size="sm" variant={period===value?"default":"ghost"} onClick={()=>setPeriod(value)}>{workerPeriodLabel(value)}</Button>)}</div><Button onClick={load}><Search className="size-4"/>Load</Button></CardContent></Card>
 {!data?<Card><CardContent className="py-16 text-center"><Users className="mx-auto mb-3 size-10 text-primary"/><h3 className="font-bold">Select a worker to begin</h3><p className="mt-1 text-sm text-muted-foreground">Choose full month, 1–15, or 16–end before loading.</p></CardContent></Card>:<><div className="mb-4 flex flex-wrap items-center gap-2"><strong className="mr-auto">{data.worker.name} · {data.month} · {workerPeriodLabel(period)}</strong><Badge>{periodDays.length} days</Badge><Badge>{selected.size} selected</Badge><Badge variant={periodDays.some((x:Editable)=>x.dirty)?"warning":"secondary"}>{periodDays.filter((x:Editable)=>x.dirty).length} edited</Badge><Button variant="outline" onClick={toggleAll}><Check className="size-4"/>{allSelected?"Deselect all":"Select all days"}</Button><Button variant="outline" disabled={!selected.size} onClick={openCopy}><Copy className="size-4"/>Copy selected days</Button><Button disabled={saving||!periodDays.some((x:Editable)=>x.dirty)} onClick={()=>save(periodDays.filter((x:Editable)=>x.dirty))}>{saving?<LoaderCircle className="size-4 animate-spin"/>:<Save className="size-4"/>}{saving?"Saving…":"Save edited"}</Button></div><div className="grid gap-3">{periodDays.map((r:Editable)=>{const weekday=new Date(`${r.work_date}T12:00`).toLocaleDateString("en-US",{weekday:"short"});return <Card key={r.work_date} className={r.dirty?"border-amber-300":""}><div className="p-4"><div className="flex flex-wrap items-center gap-3"><input type="checkbox" className="size-4 accent-[#2563eb]" checked={selected.has(r.work_date)} onChange={e=>setSelected(s=>{const n=new Set(s);e.target.checked?n.add(r.work_date):n.delete(r.work_date);return n})}/><div className="w-24"><strong>{displayDate(r.work_date)}</strong><small className="ml-2 text-muted-foreground">{weekday}</small></div><div className="flex rounded-lg bg-muted p-1"><Button size="sm" variant={r.status==="worked"?"default":"ghost"} onClick={()=>setDay(r.work_date,workedPatch(r,true))}>Worked</Button><Button size="sm" variant={r.status==="sick_leave"?"default":"ghost"} onClick={()=>setDay(r.work_date,sickLeavePatch())}>Sick leave</Button><Button size="sm" variant={r.status==="off"?"default":"ghost"} onClick={()=>setDay(r.work_date,offPatch())}>Off</Button></div><span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{cellText(r)}</span><strong className="text-primary">{compactNumber(r.total_hours)}h</strong><Button size="sm" disabled={saving||!r.dirty} onClick={()=>save([r])}>{saving?<LoaderCircle className="size-4 animate-spin"/>:<Save className="size-4"/>}Save</Button><Button size="sm" variant="ghost" className="text-red-600 hover:text-red-700" onClick={()=>void clearDay(r)}><Trash2 className="size-4"/>Clear record</Button><Button variant="ghost" size="icon" onClick={()=>setDay(r.work_date,{expanded:!r.expanded})}><ChevronDown className={`size-4 ${r.expanded?"rotate-180":""}`}/></Button></div>{r.expanded&&<RecordEditor record={r} bootstrap={bootstrap} update={p=>setDay(r.work_date,p)}/>}</div></Card>})}</div></>}
 {dirtyDays.length>0&&<div className="fixed bottom-20 right-5 z-40 flex items-center gap-4 rounded-2xl border bg-white p-3 pl-5 shadow-xl md:bottom-6"><span className="text-sm"><strong>{dirtyDays.length}</strong> edited · draft protected</span><Button disabled={saving} onClick={()=>save(dirtyDays)}>{saving?<LoaderCircle className="size-4 animate-spin"/>:<Save className="size-4"/>}{saving?"Saving…":"Save edited"}</Button></div>}
 <Dialog open={copyOpen} onOpenChange={open=>{setCopyOpen(open);if(!open){setTargetSearch("");setTargets([])}}}><DialogContent><DialogHeader><DialogTitle>Copy {selected.size} selected days</DialogTitle><DialogDescription>Same-date copies to the same Worker are blocked. To copy the same Worker, choose a different target date. Existing records on target dates will be replaced.</DialogDescription></DialogHeader><div className="grid gap-3 rounded-xl border bg-slate-50 p-3"><div className="flex flex-wrap gap-2"><Button size="sm" variant={copyMode==="same"?"default":"outline"} onClick={()=>changeCopyMode("same")}>Use same dates</Button><Button size="sm" variant={copyMode==="range"?"default":"outline"} onClick={()=>changeCopyMode("range")}>Copy to date range</Button></div>{copyMode==="range"?<div className="grid gap-3 sm:grid-cols-2"><label className="field-label">Target from<Input type="date" value={targetStart} onChange={e=>setTargetStart(e.target.value)}/></label><label className="field-label">Target to<Input type="date" value={targetEnd} onChange={e=>setTargetEnd(e.target.value)}/></label></div>:<p className="text-xs text-muted-foreground">Target dates: {targetDates.map(date=>displayDate(date,true)).join(", ")||"—"}</p>}<p className="text-xs font-semibold text-primary">{targetDates.length} target {targetDates.length===1?"date":"dates"}</p></div><div className="relative"><Search className="absolute left-3 top-3.5 size-4 text-muted-foreground"/><Input autoFocus className="pl-9" value={targetSearch} onChange={e=>setTargetSearch(e.target.value)} placeholder="Find target worker…"/></div><div className="flex items-center justify-between text-xs text-muted-foreground"><span>{targets.length} workers selected</span><Button type="button" size="sm" variant="ghost" onClick={toggleShownTargets}>{allShownSelected?"Clear shown":"Select shown"}</Button></div><div className="max-h-72 overflow-auto rounded-xl border p-2">{shownTargets.map((w:Worker)=><label key={w.id} className={`flex cursor-pointer items-center gap-3 rounded-lg p-2 hover:bg-muted ${copyMode==="same"&&w.id===data?.worker?.id?"opacity-50":""}`}><input type="checkbox" disabled={copyMode==="same"&&w.id===data?.worker?.id} checked={targets.includes(w.id)} onChange={e=>setTargets(t=>e.target.checked?Array.from(new Set([...t,w.id])):t.filter(id=>id!==w.id))}/><span className="avatar">{initials(w.name)}</span><span>{w.name}{w.id===data?.worker?.id&&<small className="ml-2 text-muted-foreground">current worker · choose a different date</small>}</span></label>)}{!shownTargets.length&&<p className="p-5 text-center text-sm text-muted-foreground">No worker matches this search.</p>}</div><div className="flex justify-end gap-2"><Button variant="ghost" onClick={()=>{setCopyOpen(false);setTargetSearch("");setTargets([])}}>Cancel</Button><Button disabled={!targets.length||!targetDates.length||sameWorkerSameDate} onClick={copy}><Copy className="size-4"/>Copy to {targets.length} workers</Button></div></DialogContent></Dialog></div>
}
