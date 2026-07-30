import { Fragment, useEffect, useMemo, useState } from "react"
import { CalendarRange, Check, ChevronDown, ChevronRight, ChevronsUpDown, ChevronUp, Clock3, DollarSign, LoaderCircle, LockKeyhole, MapPin, RefreshCw, Search, Users } from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { api, getApiMutationVersion, postJSON } from "@/lib/api"
import type { Bootstrap, Summary } from "@/lib/types"
import { compactNumber, displayDate, initials, localISO } from "@/lib/utils"

function PageIntro({ title, text, actions }: { title: string; text: string; actions?: React.ReactNode }) { return <div className="mb-6 flex flex-col justify-between gap-4 sm:flex-row sm:items-end"><div><h1 className="page-title">{title}</h1><p className="page-subtitle">{text}</p></div>{actions}</div> }
function Metric({ icon: Icon, label, value, detail }: { icon: typeof Clock3; label: string; value: string; detail?: string }) { return <Card><CardContent className="flex items-center gap-4 !pt-5 sm:!pt-6"><div className="metric-icon"><Icon className="size-5" /></div><div className="min-w-0"><p className="text-xs font-semibold text-muted-foreground">{label}</p><p className="metric-value mt-1">{value}</p>{detail && <p className="mt-1 text-[11px] text-muted-foreground">{detail}</p>}</div></CardContent></Card> }
type RangePreset = "7" | "month" | "pay1" | "pay2"
type PayrollSort = "name_asc" | "name_desc" | "cost_desc" | "cost_asc" | "hours_desc" | "hours_asc" | "regular_desc" | "regular_asc" | "overtime_desc" | "overtime_asc" | "days_desc" | "days_asc"
type SiteSort = "name_asc" | "name_desc" | "cost_desc" | "cost_asc" | "hours_desc" | "hours_asc" | "regular_desc" | "regular_asc" | "days_desc" | "days_asc" | "first_desc" | "first_asc" | "last_desc" | "last_asc"
const rangePresets: [RangePreset, string][] = [["7","Last 7 days"],["month","This month"],["pay1","1–15"],["pay2","16–end"]]
function presetDates(kind:RangePreset,today:string){const now=new Date(`${today}T12:00:00`),y=now.getFullYear(),m=now.getMonth();if(kind==="7"){const start=new Date(now);start.setDate(start.getDate()-6);return {from:localISO(start),to:today}}if(kind==="month")return {from:`${today.slice(0,7)}-01`,to:today};const last=new Date(y,m+1,0);return {from:localISO(new Date(y,m,kind==="pay1"?1:16)),to:localISO(kind==="pay1"?new Date(y,m,15):last)}}
function SortableHeader({label,active,direction,onClick}:{label:string;active:boolean;direction:"asc"|"desc";onClick:()=>void}){
  const Icon=active?(direction==="asc"?ChevronUp:ChevronDown):ChevronsUpDown
  return <th><button type="button" onClick={onClick} className={`inline-flex items-center gap-1.5 whitespace-nowrap font-bold uppercase tracking-wide transition-colors hover:text-primary ${active?"text-primary":"text-inherit"}`} aria-label={`Sort ${label} ${active&&direction==="asc"?"descending":"ascending"}`}>{label}<Icon className="size-3.5" aria-hidden="true"/></button></th>
}

type OverviewCacheEntry = {
  data: Summary
  savedAt: number
  mutationVersion: number
}
const overviewCache = new Map<string, OverviewCacheEntry>()
export function OverviewView({ bootstrap }: { bootstrap: Bootstrap }) {
  const today = localISO()
  const [from, setFrom] = useState(`${today.slice(0,7)}-01`)
  const [to, setTo] = useState(today)
  const [selectedPreset, setSelectedPreset] = useState<RangePreset | null>("month")
  const [worker, setWorker] = useState("")
  const [data, setData] = useState<Summary | null>(null)
  const [loading, setLoading] = useState(true)
  const load = async (force = false) => {
    const match = worker
      ? bootstrap.workers.find(w => w.name.toLowerCase() === worker.toLowerCase())
        || bootstrap.workers.find(w => w.name.toLowerCase().includes(worker.toLowerCase()))
      : null
    if (worker && !match) {
      toast.error(`No worker matches “${worker}”`)
      return
    }
    const p = new URLSearchParams({ from, to })
    if (match) p.set("worker_id", String(match.id))
    const key = p.toString()
    const cached = overviewCache.get(key)
    if (!force && cached && Date.now() - cached.savedAt < 5 * 60_000 && cached.mutationVersion === getApiMutationVersion()) {
      setData(cached.data)
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const result = await api<Summary>(`/api/summary?${p}`)
      overviewCache.set(key, { data: result, savedAt: Date.now(), mutationVersion: getApiMutationVersion() })
      setData(result)
    } catch(e) {
      toast.error(e instanceof Error ? e.message : "Unable to load records")
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { void load() }, [])
  const setPreset = (kind: RangePreset) => { const range=presetDates(kind,today);setSelectedPreset(kind);setFrom(range.from);setTo(range.to) }
  return <div className="page"><PageIntro title="Workforce overview" text="A quick summary of the selected work period." />
    <Card className="mb-5"><CardContent className="grid gap-3 !pt-5 lg:grid-cols-[1fr_1fr_1.3fr_auto]"><label className="field-label">From<Input type="date" value={from} onChange={e=>{setFrom(e.target.value);setSelectedPreset(null)}} /></label><label className="field-label">To<Input type="date" value={to} onChange={e=>{setTo(e.target.value);setSelectedPreset(null)}} /></label><label className="field-label">Worker<Input list="workers" value={worker} onChange={e=>setWorker(e.target.value)} placeholder="All workers" /></label><Button className="self-end" disabled={loading} onClick={()=>void load(true)}>{loading?<LoaderCircle className="size-4 animate-spin"/>:<Search className="size-4"/>}{loading?"Loading…":"Apply"}</Button><div className="flex flex-wrap gap-2 lg:col-span-4">{rangePresets.map(([id,label])=><Button size="sm" variant={selectedPreset===id?"default":"ghost"} aria-pressed={selectedPreset===id} key={id} onClick={()=>setPreset(id)}>{selectedPreset===id&&<Check className="size-3.5"/>}{label}</Button>)}</div></CardContent></Card>
    {loading && !data ? <div className="metric-grid mb-5">{[1,2,3,4].map(x=><Skeleton className="h-28" key={x}/>)}</div> : <>
      <div className="metric-grid mb-5"><Metric icon={Clock3} label="Regular hours" value={`${compactNumber(data?.totals.regular_hours)}h`} /><Metric icon={Clock3} label="Weighted payroll hours" value={`${compactNumber(data?.totals.weighted_hours)}h`} detail="Regular + OT ×1.5 + DT ×2" /><Metric icon={Users} label="Active workers" value={compactNumber(data?.totals.active_workers,0)} /><Metric icon={CalendarRange} label="Worked days" value={compactNumber(data?.totals.worked_days,0)} /></div>
      <Card className="mb-5"><CardHeader className="!flex-row items-center justify-between"><div><CardTitle>Period summary</CardTitle><CardDescription>{data ? `${displayDate(data.range.from,true)} – ${displayDate(data.range.to,true)}` : ""}</CardDescription></div><Button size="sm" variant="outline" disabled={loading} onClick={()=>void load(true)}><RefreshCw className={`size-4 ${loading?"animate-spin":""}`}/>Refresh</Button></CardHeader><CardContent><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">{[["Actual hours",`${compactNumber(data?.totals.hours)}h`],["Average workday",`${compactNumber(data?.totals.average_hours)}h`],["Off records",compactNumber(data?.totals.off_days,0)],["Extra pay",`$${compactNumber(data?.totals.extra_pay)}`],["Latest activity",data?.totals.last_worked_date?displayDate(data.totals.last_worked_date,true):"—"]].map(([label,value])=><div className="rounded-xl border bg-slate-50 p-4" key={label}><p className="text-xs font-semibold text-muted-foreground">{label}</p><strong className="mt-1 block text-lg">{value}</strong></div>)}</div></CardContent></Card>
    </>}
  </div>
}

export function PayrollView({ bootstrap }: { bootstrap: Bootstrap }) {
  const today=localISO()
  const [from,setFrom]=useState(`${today.slice(0,7)}-01`)
  const [to,setTo]=useState(today)
  const [selectedPreset,setSelectedPreset]=useState<RangePreset|null>("month")
  const [worker,setWorker]=useState("")
  const [data,setData]=useState<any>(null)
  const [detail,setDetail]=useState<any>(null)
  const [access,setAccess]=useState<any>(null)
  const [password,setPassword]=useState("")
  const [unlocking,setUnlocking]=useState(false)
  const [loading,setLoading]=useState(false)
  const [sort,setSort]=useState<PayrollSort>("name_asc")
  const workers=useMemo(()=>{
    const rows=[...(data?.workers||[])]
    const name=(a:any,b:any)=>a.worker_name.localeCompare(b.worker_name,undefined,{sensitivity:"base"})
    const comparators:Record<PayrollSort,(a:any,b:any)=>number>={
      name_asc:name,
      name_desc:(a,b)=>name(b,a),
      cost_desc:(a,b)=>b.estimated_salary-a.estimated_salary||name(a,b),
      cost_asc:(a,b)=>a.estimated_salary-b.estimated_salary||name(a,b),
      hours_desc:(a,b)=>b.weighted_hours-a.weighted_hours||name(a,b),
      hours_asc:(a,b)=>a.weighted_hours-b.weighted_hours||name(a,b),
      regular_desc:(a,b)=>b.regular_hours-a.regular_hours||name(a,b),
      regular_asc:(a,b)=>a.regular_hours-b.regular_hours||name(a,b),
      overtime_desc:(a,b)=>(b.overtime_hours+b.doubletime_hours)-(a.overtime_hours+a.doubletime_hours)||name(a,b),
      overtime_asc:(a,b)=>(a.overtime_hours+a.doubletime_hours)-(b.overtime_hours+b.doubletime_hours)||name(a,b),
      days_desc:(a,b)=>b.worked_days-a.worked_days||name(a,b),
      days_asc:(a,b)=>a.worked_days-b.worked_days||name(a,b),
    }
    return rows.sort(comparators[sort])
  },[data,sort])
  const changeSort=(field:string,preferred:"asc"|"desc")=>setSort(current=>
    (current.startsWith(`${field}_`)
      ? `${field}_${current.endsWith("_asc")?"desc":"asc"}`
      : `${field}_${preferred}`) as PayrollSort
  )
  const checkAccess=async()=>{try{setAccess(await api("/api/payroll/access"))}catch(e){toast.error(e instanceof Error?e.message:String(e))}}
  useEffect(()=>{void checkAccess()},[])
  const selectedWorker=()=>worker?bootstrap.workers.find(w=>w.name.toLowerCase()===worker.toLowerCase())||bootstrap.workers.find(w=>w.name.toLowerCase().includes(worker.toLowerCase())):null
  const load=async()=>{if(!access?.authorized)return;if(!from||!to||from>to)return toast.error("Choose a valid From and To date range.");const match=selectedWorker();if(worker&&!match)return toast.error(`No worker matches “${worker}”`);setLoading(true);try{const params=new URLSearchParams({from,to});if(match)params.set("worker_id",String(match.id));setData(await api(`/api/payroll?${params}`));setDetail(null)}catch(e){toast.error(e instanceof Error?e.message:String(e))}finally{setLoading(false)}}
  useEffect(()=>{if(access?.authorized)void load()},[access?.authorized])
  const setPreset=(kind:RangePreset)=>{const range=presetDates(kind,today);setSelectedPreset(kind);setFrom(range.from);setTo(range.to)}
  const unlock=async(event:React.FormEvent)=>{event.preventDefault();if(!password)return;setUnlocking(true);try{await postJSON("/api/payroll/unlock",{password});setPassword("");await checkAccess();toast.success("Payroll Check unlocked for 8 hours.")}catch(e){toast.error(e instanceof Error?e.message:String(e))}finally{setUnlocking(false)}}
  const show=async(id:number)=>{if(detail?.worker.id===id){setDetail(null);return}try{setDetail(await api(`/api/payroll_worker_detail?${new URLSearchParams({worker_id:String(id),from:data.period.from,to:data.period.to})}`))}catch(e){toast.error(e instanceof Error?e.message:String(e))}}
  const check=async(w:any, checked:boolean)=>{try{await postJSON("/api/payroll_check",{worker_id:w.worker_id,period_start:data.period.from,period_end:data.period.to,checked});setData((d:any)=>({...d,totals:{...d.totals,checked:d.workers.filter((x:any)=>x.worker_id===w.worker_id?checked:x.checked).length},workers:d.workers.map((x:any)=>x.worker_id===w.worker_id?{...x,checked}:x)}))}catch(e){toast.error(e instanceof Error?e.message:String(e))}}
  if(!access)return <div className="page"><Card><CardContent className="flex items-center justify-center gap-3 py-20 text-sm text-muted-foreground"><LoaderCircle className="size-5 animate-spin"/>Checking Payroll Check access…</CardContent></Card></div>
  if(!access.authorized)return <div className="page"><div className="mx-auto max-w-lg py-10"><Card><CardHeader><span className="mb-2 grid size-12 place-items-center rounded-xl bg-blue-50 text-primary"><LockKeyhole className="size-6"/></span><CardTitle>Payroll Check is protected</CardTitle><CardDescription>Payroll totals, rates, and working history are available only to authorized Lark administrators or users with the Payroll Check password.</CardDescription></CardHeader><CardContent>{access.password_configured?<form className="grid gap-3" onSubmit={unlock}><label className="field-label">Payroll Check password<Input autoFocus type="password" autoComplete="current-password" value={password} onChange={event=>setPassword(event.target.value)}/></label><Button type="submit" disabled={!password||unlocking}>{unlocking?<LoaderCircle className="size-4 animate-spin"/>:<LockKeyhole className="size-4"/>}{unlocking?"Unlocking…":"Unlock Payroll Check"}</Button></form>:<div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">Password access is not configured. Add <code>PAYROLL_PASSWORD</code> in Vercel and redeploy, or add this user's Lark open ID to <code>LARK_ADMIN_OPEN_IDS</code>.</div>}</CardContent></Card></div></div>
  return <div className="page"><PageIntro title="Payroll check" text="Review regular, overtime, and total hours for any selected period."/>
  <Card className="mb-5"><CardContent className="grid gap-3 !pt-5 lg:grid-cols-[1fr_1fr_1.3fr_auto]"><label className="field-label">From<Input type="date" value={from} onChange={e=>{setFrom(e.target.value);setSelectedPreset(null)}}/></label><label className="field-label">To<Input type="date" value={to} onChange={e=>{setTo(e.target.value);setSelectedPreset(null)}}/></label><label className="field-label">Worker<Input list="workers" value={worker} onChange={e=>setWorker(e.target.value)} placeholder="All workers"/></label><Button className="self-end" disabled={loading} onClick={()=>void load()}>{loading?<LoaderCircle className="size-4 animate-spin"/>:<Search className="size-4"/>}{loading?"Loading…":"Apply"}</Button><div className="flex flex-wrap gap-2 lg:col-span-4">{rangePresets.map(([id,label])=><Button size="sm" variant={selectedPreset===id?"default":"ghost"} aria-pressed={selectedPreset===id} key={id} onClick={()=>setPreset(id)}>{selectedPreset===id&&<Check className="size-3.5"/>}{label}</Button>)}</div></CardContent></Card>
  <div className="metric-grid mb-5"><Metric icon={Clock3} label="Regular hours" value={`${compactNumber(data?.totals.regular_hours)}h`}/><Metric icon={Clock3} label="Weighted payroll hours" value={`${compactNumber(data?.totals.weighted_hours)}h`} detail="Regular + OT ×1.5 + DT ×2"/><Metric icon={DollarSign} label="Estimated cost" value={`$${compactNumber(data?.totals.estimated_salary)}`}/><Metric icon={Check} label="Checked" value={`${data?.totals.checked||0} / ${workers.length}`}/></div>
  <Card><CardHeader><CardTitle>{data?`${displayDate(data.period.from,true)} – ${displayDate(data.period.to,true)}`:"Selected payroll period"}</CardTitle><CardDescription>Click a column heading to sort; click it again to reverse the order. Click a worker to expand their history.</CardDescription></CardHeader><CardContent><div className="table-wrap"><table className="data-table"><thead><tr><th>Checked</th><SortableHeader label="Worker" active={sort.startsWith("name_")} direction={sort.endsWith("_asc")?"asc":"desc"} onClick={()=>changeSort("name","asc")}/><SortableHeader label="Regular hours" active={sort.startsWith("regular_")} direction={sort.endsWith("_asc")?"asc":"desc"} onClick={()=>changeSort("regular","desc")}/><SortableHeader label="Weighted payroll hours" active={sort.startsWith("hours_")} direction={sort.endsWith("_asc")?"asc":"desc"} onClick={()=>changeSort("hours","desc")}/><SortableHeader label="CA overtime" active={sort.startsWith("overtime_")} direction={sort.endsWith("_asc")?"asc":"desc"} onClick={()=>changeSort("overtime","desc")}/><SortableHeader label="Estimated cost" active={sort.startsWith("cost_")} direction={sort.endsWith("_asc")?"asc":"desc"} onClick={()=>changeSort("cost","desc")}/><SortableHeader label="Days" active={sort.startsWith("days_")} direction={sort.endsWith("_asc")?"asc":"desc"} onClick={()=>changeSort("days","desc")}/><th></th></tr></thead><tbody>{workers.map((w:any)=><Fragment key={w.worker_id}><tr onClick={()=>show(w.worker_id)} className="cursor-pointer"><td onClick={e=>e.stopPropagation()}><input type="checkbox" checked={!!w.checked} onChange={e=>void check(w,e.target.checked)} className="size-4 accent-[#2563eb]"/></td><td><div className="flex items-center gap-2"><span className="avatar">{initials(w.worker_name)}</span><strong className={w.worker_type==="W2"?"text-red-600":"text-slate-900"}>{w.worker_name}</strong><span className="badge">{w.worker_type}</span></div></td><td><strong>{compactNumber(w.regular_hours)}h</strong></td><td><strong className="text-lg text-primary">{compactNumber(w.weighted_hours)} <small className="text-xs">hrs</small></strong></td><td><div>{compactNumber(w.overtime_hours)}h × 1.5</div>{w.doubletime_hours>0&&<small className="text-orange-700">{compactNumber(w.doubletime_hours)}h × 2</small>}</td><td>${compactNumber(w.estimated_salary)}</td><td>{w.worked_days} <small className="text-muted-foreground">· {w.off_days} off</small></td><td><ChevronRight className={`size-4 text-muted-foreground transition-transform ${detail?.worker.id===w.worker_id?"rotate-90":""}`}/></td></tr>{detail?.worker.id===w.worker_id&&<tr className="bg-slate-50/70"><td colSpan={8} className="!p-4 sm:!p-6"><PayrollWorkerDetail detail={detail}/></td></tr>}</Fragment>)}</tbody></table>{!workers.length&&!loading&&<div className="p-10 text-center text-sm text-muted-foreground">No payroll records match this period and worker selection.</div>}</div></CardContent></Card></div>
}
function PayrollWorkerDetail({detail}:{detail:any}){return <div><div className="mb-5 flex flex-wrap items-center justify-between gap-3"><div><h3 className="text-lg font-bold">{detail.worker.name} · selected-period details</h3><p className="text-sm text-muted-foreground">{compactNumber(detail.totals.regular_hours)} regular hours · {compactNumber(detail.totals.weighted_hours)} weighted payroll hours · estimated ${compactNumber(detail.totals.estimated_salary)}</p></div><Badge variant={detail.worker.worker_type==="W2"?"warning":"secondary"}>{detail.worker.worker_type}</Badge></div><WorkingHistory days={detail.days||[]}/><div className="mt-5 grid gap-5 xl:grid-cols-2"><DetailTable title="Hours by site" rows={detail.locations} totalEstimatedCost={detail.totals.estimated_salary}/><DetailTable title="Hours by cost code" rows={detail.cost_centers} totalEstimatedCost={detail.totals.estimated_salary}/></div><p className="mt-3 text-xs text-muted-foreground"><strong>--</strong> means the site or cost code was not filled in, or the amount is extra pay that is not assigned to either category.</p></div>}
function WorkingHistory({days}:{days:any[]}){return <div><div className="mb-3 flex items-end justify-between"><div><h3 className="text-base font-bold">Working history</h3><p className="text-xs text-muted-foreground">California weighting: regular ×1, overtime ×1.5, double time ×2</p></div><Badge variant="secondary">{days.length} days</Badge></div><div className="table-wrap"><table className="data-table"><thead><tr><th>Date</th><th>Site and hours</th><th>Cost code</th><th>Regular hours</th><th>OT ×1.5</th><th>DT ×2</th><th>Actual hours</th><th>Weighted payroll hours</th><th>Extra pay</th></tr></thead><tbody>{days.map((d:any)=><tr key={d.work_day_id}><td><strong>{displayDate(d.date,true)}</strong></td><td>{d.locations?.length?d.locations.map((l:any)=><div key={l.location_id}><strong>{l.name}</strong><small className="ml-1 text-muted-foreground">{compactNumber(l.hours)}h</small></div>):"—"}</td><td>{d.cost_centers?.length?d.cost_centers.map((c:any)=><div key={c.id}>{c.name}<small className="ml-1 text-muted-foreground">{c.id}</small></div>):"—"}</td><td>{compactNumber(d.regular_hours)}h</td><td>{d.overtime_hours?<Badge variant="warning">{compactNumber(d.overtime_hours)}h</Badge>:"0h"}</td><td>{d.doubletime_hours?<Badge variant="warning">{compactNumber(d.doubletime_hours)}h</Badge>:"0h"}</td><td><strong>{compactNumber(d.total_hours)}h</strong></td><td><strong className="text-primary">{compactNumber(d.weighted_hours)}h</strong></td><td>{d.extra_pay?`$${compactNumber(d.extra_pay)}`:"—"}</td></tr>)}</tbody></table>{!days.length&&<div className="p-8 text-center text-sm text-muted-foreground">No worked days in this payment period.</div>}</div></div>}
function DetailTable({title,rows,totalEstimatedCost}:{title:string;rows:any[];totalEstimatedCost?:number}){
  const showCost=rows.some((row:any)=>row.estimated_cost!==undefined)
  return <div><h3 className="mb-2 text-sm font-bold">{title}</h3><div className="table-wrap"><table className="data-table"><thead><tr><th>Name</th>{showCost?<><th>Regular hours</th><th>Weighted payroll hours</th><th>Estimated cost</th></>:<th>Hours</th>}<th>Days</th></tr></thead><tbody>{rows.map((r:any)=><tr key={`${r.id||""}${r.name}`}><td><strong>{r.name}</strong>{r.id&&<small className="block text-muted-foreground">{r.id}</small>}</td>{showCost?<><td>{compactNumber(r.regular_hours)}h</td><td className="font-semibold text-primary">{compactNumber(r.weighted_hours)}h</td><td className="font-semibold tabular-nums">${compactNumber(r.estimated_cost)}</td></>:<td>{compactNumber(r.hours)}</td>}<td>{r.days}</td></tr>)}</tbody>{showCost&&totalEstimatedCost!==undefined&&<tfoot><tr className="border-t-2 bg-slate-100"><td colSpan={3}><strong>Total estimated cost</strong></td><td className="font-bold tabular-nums text-primary">${compactNumber(totalEstimatedCost)}</td><td></td></tr></tfoot>}</table>{!rows.length&&<div className="p-8 text-center text-xs text-muted-foreground">No details recorded.</div>}</div></div>
}

export function LocationsView({ bootstrap }: { bootstrap: Bootstrap }) {
  const today=localISO()
  const [location,setLocation]=useState("")
  const [from,setFrom]=useState(`${today.slice(0,4)}-01-01`)
  const [to,setTo]=useState(today)
  const [data,setData]=useState<any>(null)
  const [detail,setDetail]=useState<any>(null)
  const [detailLoading,setDetailLoading]=useState<number|null>(null)
  const [loading,setLoading]=useState(false)
  const [access,setAccess]=useState<any>(null)
  const [password,setPassword]=useState("")
  const [unlocking,setUnlocking]=useState(false)
  const [sort,setSort]=useState<SiteSort>("name_asc")
  const workers=useMemo(()=>{
    const rows=[...(data?.workers||[])]
    const name=(a:any,b:any)=>a.worker_name.localeCompare(b.worker_name,undefined,{sensitivity:"base"})
    const comparators:Record<SiteSort,(a:any,b:any)=>number>={
      name_asc:name,
      name_desc:(a,b)=>name(b,a),
      cost_desc:(a,b)=>b.estimated_cost-a.estimated_cost||name(a,b),
      cost_asc:(a,b)=>a.estimated_cost-b.estimated_cost||name(a,b),
      hours_desc:(a,b)=>b.weighted_hours-a.weighted_hours||name(a,b),
      hours_asc:(a,b)=>a.weighted_hours-b.weighted_hours||name(a,b),
      regular_desc:(a,b)=>b.regular_hours-a.regular_hours||name(a,b),
      regular_asc:(a,b)=>a.regular_hours-b.regular_hours||name(a,b),
      days_desc:(a,b)=>b.days-a.days||name(a,b),
      days_asc:(a,b)=>a.days-b.days||name(a,b),
      first_desc:(a,b)=>b.first_date.localeCompare(a.first_date)||name(a,b),
      first_asc:(a,b)=>a.first_date.localeCompare(b.first_date)||name(a,b),
      last_desc:(a,b)=>b.last_date.localeCompare(a.last_date)||name(a,b),
      last_asc:(a,b)=>a.last_date.localeCompare(b.last_date)||name(a,b),
    }
    return rows.sort(comparators[sort])
  },[data,sort])
  const changeSort=(field:string,preferred:"asc"|"desc")=>setSort(current=>
    (current.startsWith(`${field}_`)
      ? `${field}_${current.endsWith("_asc")?"desc":"asc"}`
      : `${field}_${preferred}`) as SiteSort
  )

  const checkAccess=async()=>{try{setAccess(await api("/api/payroll/access"))}catch(e){toast.error(e instanceof Error?e.message:String(e))}}
  useEffect(()=>{void checkAccess()},[])
  const unlock=async(event:React.FormEvent)=>{
    event.preventDefault()
    if(!password)return
    setUnlocking(true)
    try{
      await postJSON("/api/payroll/unlock",{password})
      setPassword("")
      await checkAccess()
      toast.success("Payroll and Site Check unlocked for 8 hours.")
    }catch(e){toast.error(e instanceof Error?e.message:String(e))}
    finally{setUnlocking(false)}
  }
  const load=async()=>{
    if(!access?.authorized)return
    if(!from||!to||from>to)return toast.error("Choose a valid From and To date range.")
    const found=bootstrap.locations.find(x=>x.toLowerCase()===location.toLowerCase())||bootstrap.locations.find(x=>x.toLowerCase().includes(location.toLowerCase()))
    if(!found)return toast.error("Choose a site from the suggestions.")
    setLoading(true)
    try{
      setData(await api(`/api/location_detail?${new URLSearchParams({location:found,from,to})}`))
      setDetail(null)
    }catch(e){toast.error(e instanceof Error?e.message:String(e))}
    finally{setLoading(false)}
  }
  const show=async(workerId:number)=>{
    if(detail?.worker.id===workerId){setDetail(null);return}
    if(!data)return
    setDetailLoading(workerId)
    try{
      setDetail(await api(`/api/location_detail?${new URLSearchParams({location:data.location,from:data.range.from,to:data.range.to,worker_id:String(workerId)})}`))
    }catch(e){toast.error(e instanceof Error?e.message:String(e))}
    finally{setDetailLoading(null)}
  }

  if(!access)return <div className="page"><Card><CardContent className="flex items-center justify-center gap-3 py-20 text-sm text-muted-foreground"><LoaderCircle className="size-5 animate-spin"/>Checking Site Check access…</CardContent></Card></div>
  if(!access.authorized)return <div className="page"><div className="mx-auto max-w-lg py-10"><Card><CardHeader><span className="mb-2 grid size-12 place-items-center rounded-xl bg-blue-50 text-primary"><LockKeyhole className="size-6"/></span><CardTitle>Site Check is protected</CardTitle><CardDescription>Site hours, worker rates, and estimated labor costs use the same protected access as Payroll Check.</CardDescription></CardHeader><CardContent>{access.password_configured?<form className="grid gap-3" onSubmit={unlock}><label className="field-label">Payroll Check password<Input autoFocus type="password" autoComplete="current-password" value={password} onChange={event=>setPassword(event.target.value)}/></label><Button type="submit" disabled={!password||unlocking}>{unlocking?<LoaderCircle className="size-4 animate-spin"/>:<LockKeyhole className="size-4"/>}{unlocking?"Unlocking…":"Unlock Site Check"}</Button></form>:<div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">Password access is not configured. Add <code>PAYROLL_PASSWORD</code> in Vercel and redeploy, or add this user's Lark open ID to <code>LARK_ADMIN_OPEN_IDS</code>.</div>}</CardContent></Card></div></div>

  return <div className="page">
    <PageIntro title="Site check" text="See site hours, workers, cost codes, and estimated labor cost."/>
    <Card className="mb-5"><CardContent className="grid gap-3 !pt-5 md:grid-cols-[1.5fr_1fr_1fr_auto]">
      <label className="field-label">Site<Input list="locations" value={location} onChange={e=>setLocation(e.target.value)} placeholder="Search address or site"/></label>
      <label className="field-label">From<Input type="date" value={from} onChange={e=>setFrom(e.target.value)}/></label>
      <label className="field-label">To<Input type="date" value={to} onChange={e=>setTo(e.target.value)}/></label>
      <Button className="self-end" disabled={loading} onClick={()=>void load()}>{loading?<LoaderCircle className="size-4 animate-spin"/>:<Search className="size-4"/>}{loading?"Calculating…":"Check site"}</Button>
    </CardContent></Card>
    {data&&<>
      <div className="metric-grid mb-5">
        <Metric icon={Users} label="Workers" value={compactNumber(data.totals.workers,0)}/>
        <Metric icon={Clock3} label="Regular hours" value={`${compactNumber(data.totals.regular_hours)}h`}/>
        <Metric icon={Clock3} label="Weighted payroll hours" value={`${compactNumber(data.totals.weighted_hours)}h`} detail="Regular + OT ×1.5 + DT ×2"/>
        <Metric icon={DollarSign} label="Estimated cost" value={`$${compactNumber(data.totals.estimated_cost)}`} detail="Based on worker rates and weighted overtime"/>
        <Metric icon={CalendarRange} label="Work days" value={compactNumber(data.totals.days,0)}/>
        <Metric icon={MapPin} label="Date span" value={data.totals.first_date?`${displayDate(data.totals.first_date)}–${displayDate(data.totals.last_date)}`:"—"}/>
      </div>
      <Card>
        <CardHeader><CardTitle>{data.location}</CardTitle><CardDescription>{displayDate(data.range.from,true)} – {displayDate(data.range.to,true)} · Click a column heading to sort and click again to reverse it. Click a worker for site-specific history.</CardDescription></CardHeader>
        <CardContent><div className="table-wrap"><table className="data-table">
          <thead><tr><SortableHeader label="Worker" active={sort.startsWith("name_")} direction={sort.endsWith("_asc")?"asc":"desc"} onClick={()=>changeSort("name","asc")}/><th>Type</th><SortableHeader label="Regular hours" active={sort.startsWith("regular_")} direction={sort.endsWith("_asc")?"asc":"desc"} onClick={()=>changeSort("regular","desc")}/><SortableHeader label="Weighted payroll hours" active={sort.startsWith("hours_")} direction={sort.endsWith("_asc")?"asc":"desc"} onClick={()=>changeSort("hours","desc")}/><SortableHeader label="Estimated cost" active={sort.startsWith("cost_")} direction={sort.endsWith("_asc")?"asc":"desc"} onClick={()=>changeSort("cost","desc")}/><SortableHeader label="Days" active={sort.startsWith("days_")} direction={sort.endsWith("_asc")?"asc":"desc"} onClick={()=>changeSort("days","desc")}/><SortableHeader label="First day" active={sort.startsWith("first_")} direction={sort.endsWith("_asc")?"asc":"desc"} onClick={()=>changeSort("first","asc")}/><SortableHeader label="Last day" active={sort.startsWith("last_")} direction={sort.endsWith("_asc")?"asc":"desc"} onClick={()=>changeSort("last","asc")}/><th></th></tr></thead>
          <tbody>{workers.map((w:any)=><Fragment key={w.worker_id}>
            <tr className="cursor-pointer" onClick={()=>void show(w.worker_id)}>
              <td><div className="flex items-center gap-2"><span className="avatar">{initials(w.worker_name)}</span><strong>{w.worker_name}</strong></div></td>
              <td><Badge variant={w.worker_type==="W2"?"warning":"secondary"}>{w.worker_type}</Badge></td>
              <td><strong>{compactNumber(w.regular_hours)}h</strong></td>
              <td><strong className="text-primary">{compactNumber(w.weighted_hours)}h</strong></td>
              <td className="font-semibold tabular-nums">${compactNumber(w.estimated_cost)}</td>
              <td>{w.days}</td><td>{displayDate(w.first_date,true)}</td><td>{displayDate(w.last_date,true)}</td>
              <td>{detailLoading===w.worker_id?<LoaderCircle className="size-4 animate-spin text-muted-foreground"/>:<ChevronRight className={`size-4 text-muted-foreground transition-transform ${detail?.worker.id===w.worker_id?"rotate-90":""}`}/>}</td>
            </tr>
            {detail?.worker.id===w.worker_id&&<tr className="bg-slate-50/70"><td colSpan={9} className="!p-4 sm:!p-6"><SiteWorkerDetail detail={detail}/></td></tr>}
          </Fragment>)}</tbody>
        </table>{!workers.length&&<div className="p-10 text-center text-sm text-muted-foreground">No workers recorded at this site during the selected period.</div>}</div></CardContent>
      </Card>
      {data.cost_centers?.length>0&&<Card className="mt-5"><CardHeader><CardTitle>Cost codes at this site</CardTitle><CardDescription>Hours are allocated from the selected site entries.</CardDescription></CardHeader><CardContent><DetailTable title="" rows={data.cost_centers}/></CardContent></Card>}
    </>}
  </div>
}

function SiteWorkerDetail({detail}:{detail:any}){
  return <div>
    <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
      <div><h3 className="text-lg font-bold">{detail.worker.name} · {detail.location}</h3><p className="text-sm text-muted-foreground">{compactNumber(detail.totals.regular_hours)} regular hours · {compactNumber(detail.totals.weighted_hours)} weighted payroll hours · estimated ${compactNumber(detail.totals.estimated_cost)}</p></div>
      <Badge variant={detail.worker.worker_type==="W2"?"warning":"secondary"}>{detail.worker.worker_type}</Badge>
    </div>
    <div className="table-wrap"><table className="data-table">
      <thead><tr><th>Date</th><th>Site hours</th><th>Cost codes</th><th>Regular hours</th><th>OT ×1.5</th><th>DT ×2</th><th>Weighted payroll hours</th><th>Estimated cost</th></tr></thead>
      <tbody>{detail.days.map((day:any)=><tr key={day.date}>
        <td><strong>{displayDate(day.date,true)}</strong></td>
        <td><strong className="text-primary">{compactNumber(day.site_hours)}h</strong></td>
        <td>{day.cost_centers?.length?day.cost_centers.map((center:any)=><div key={center.id}><strong>{center.name||center.id}</strong><small className="ml-1 text-muted-foreground">{center.id} · {compactNumber(center.hours)}h</small></div>):"—"}</td>
        <td>{compactNumber(day.regular_hours)}h</td>
        <td>{day.overtime_hours?<Badge variant="warning">{compactNumber(day.overtime_hours)}h</Badge>:"0h"}</td>
        <td>{day.doubletime_hours?<Badge variant="warning">{compactNumber(day.doubletime_hours)}h</Badge>:"0h"}</td>
        <td><strong>{compactNumber(day.weighted_hours)}h</strong></td>
        <td className="font-semibold tabular-nums">${compactNumber(day.estimated_cost)}</td>
      </tr>)}</tbody>
    </table></div>
  </div>
}
