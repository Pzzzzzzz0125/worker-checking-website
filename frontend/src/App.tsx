import { lazy, Suspense, useEffect, useState } from "react"
import { toast } from "sonner"
import { AppShell, type View } from "@/components/app-shell"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { api, ApiError, postJSON } from "@/lib/api"
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
 const [view,setViewState]=useState<View>(hashView());const [bootstrap,setBootstrap]=useState<Bootstrap|null>(null);const [bootError,setBootError]=useState<{message:string;setup:boolean}|null>(null);const [settingUp,setSettingUp]=useState(false)
 const load=async()=>{try{const base=await api<Bootstrap>("/api/bootstrap");let initial=base;try{const cached=JSON.parse(localStorage.getItem("speed-bootstrap-details")||"null");if(cached&&Array.isArray(cached.locations))initial={...base,...cached}}catch{}setBootstrap(initial);setBootError(null);void api<Partial<Bootstrap>>("/api/bootstrap_details").then(details=>{try{localStorage.setItem("speed-bootstrap-details",JSON.stringify(details))}catch{}setBootstrap(current=>current?{...current,...details}:current)}).catch(()=>{})}catch(e){const message=e instanceof Error?e.message:"Could not connect to the database";setBootError({message,setup:e instanceof ApiError&&e.status===503});toast.error(message)}};useEffect(()=>{void load();const listener=()=>setViewState(hashView());addEventListener("hashchange",listener);return()=>removeEventListener("hashchange",listener)},[])
 const initialize=async()=>{setSettingUp(true);try{const result=await postJSON<{schema:{ready:boolean}}>("/api/lark/setup",{});if(!result.schema.ready)throw new Error("Lark Base was created but its schema is incomplete.");setBootError({message:"Lark Base tables are ready. The workforce data adapter is the next deployment step.",setup:true});toast.success("Lark Base tables created successfully")}catch(e){toast.error(e instanceof Error?e.message:"Could not initialize Lark Base")}finally{setSettingUp(false)}}
 const setView=(v:View)=>{location.hash=v;setViewState(v)}
 if(bootError)return <div className="grid min-h-screen place-items-center bg-background p-5"><Card className="w-full max-w-xl"><CardHeader><img src="/logo.png" alt="Speed Construction" className="mb-3 h-12 w-fit rounded-lg"/><CardTitle>{bootError.setup?"Cloud setup in progress":"Unable to open workforce data"}</CardTitle><CardDescription>{bootError.message}</CardDescription></CardHeader><CardContent className="space-y-3"><p className="text-sm text-muted-foreground">The website is deployed safely. Connect the Lark Base environment variables to enable worker, payroll, location, and entry records.</p><div className="flex flex-wrap gap-2"><a className={buttonVariants()} href="/api/auth/lark/login">Sign in with Lark</a>{bootError.setup&&<Button onClick={()=>void initialize()} disabled={settingUp}>{settingUp?"Initializing…":"Initialize Lark Base"}</Button>}<Button variant="secondary" onClick={()=>void load()}>Try again</Button></div></CardContent></Card></div>
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
