import { lazy, Suspense, useEffect, useState } from "react"
import { toast } from "sonner"
import { AppShell, type View } from "@/components/app-shell"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import type { Bootstrap } from "@/lib/types"
const OverviewView=lazy(()=>import("@/views/checking").then(m=>({default:m.OverviewView})))
const PayrollView=lazy(()=>import("@/views/checking").then(m=>({default:m.PayrollView})))
const LocationsView=lazy(()=>import("@/views/checking").then(m=>({default:m.LocationsView})))
const DailyEntryView=lazy(()=>import("@/views/entry").then(m=>({default:m.DailyEntryView})))
const WorkerEntryView=lazy(()=>import("@/views/entry").then(m=>({default:m.WorkerEntryView})))
const AiView=lazy(()=>import("@/views/data").then(m=>({default:m.AiView})))
const ReviewView=lazy(()=>import("@/views/data").then(m=>({default:m.ReviewView})))
const TransferView=lazy(()=>import("@/views/data").then(m=>({default:m.TransferView})))

const hashView=():View=>{const value=location.hash.slice(1) as View;return ["overview","payroll","locations","ai","daily","worker","transfer","review"].includes(value)?value:"overview"}
export default function App(){
 const [view,setViewState]=useState<View>(hashView());const [bootstrap,setBootstrap]=useState<Bootstrap|null>(null)
 const load=async()=>{try{setBootstrap(await api("/api/bootstrap"))}catch(e){toast.error(e instanceof Error?e.message:"Could not connect to the database")}};useEffect(()=>{void load();const listener=()=>setViewState(hashView());addEventListener("hashchange",listener);return()=>removeEventListener("hashchange",listener)},[])
 const setView=(v:View)=>{location.hash=v;setViewState(v)}
 if(!bootstrap)return <div className="grid min-h-screen place-items-center bg-[#f5f7f7]"><div className="w-full max-w-md space-y-3 p-8"><Skeleton className="h-14"/><Skeleton className="h-28"/><Skeleton className="h-44"/></div></div>
 return <AppShell view={view} setView={setView} reviewCount={bootstrap.review_count}>
   <datalist id="workers">{bootstrap.workers.map(w=><option value={w.name} key={w.id}/>)}</datalist>
   <datalist id="locations">{bootstrap.locations.map(x=><option value={x} key={x}/>)}</datalist>
   <datalist id="centers">{bootstrap.cost_centers.map(c=><option value={`${c.name} (${c.id})`} key={c.id}/>)}</datalist>
   <Suspense fallback={<div className="page space-y-3"><Skeleton className="h-12 w-72"/><Skeleton className="h-40"/><Skeleton className="h-64"/></div>}>
    {view==="overview"&&<OverviewView bootstrap={bootstrap}/>} {view==="payroll"&&<PayrollView/>} {view==="locations"&&<LocationsView bootstrap={bootstrap}/>} {view==="ai"&&<AiView bootstrap={bootstrap} onSaved={load}/>} {view==="daily"&&<DailyEntryView bootstrap={bootstrap}/>} {view==="worker"&&<WorkerEntryView bootstrap={bootstrap}/>} {view==="transfer"&&<TransferView bootstrap={bootstrap}/>} {view==="review"&&<ReviewView bootstrap={bootstrap} onSaved={load}/>} 
   </Suspense>
 </AppShell>
}
