import { useEffect, useState } from "react"
import { zodResolver } from "@hookform/resolvers/zod"
import { useForm } from "react-hook-form"
import { z } from "zod"
import { AlertTriangle, BrainCircuit, Check, Download, ExternalLink, FileSpreadsheet, LoaderCircle, Paperclip, Sparkles, Trash2, Upload } from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input, Textarea } from "@/components/ui/input"
import { api, postJSON } from "@/lib/api"
import type { Bootstrap } from "@/lib/types"
import { displayDate, localISO } from "@/lib/utils"

const aiSchema=z.object({text:z.string().max(50_000,"Use 50,000 characters or fewer."),year:z.number().min(2020).max(2100),consent:z.boolean().refine(Boolean,"Confirm the Gemini notice.")})
type AiForm=z.infer<typeof aiSchema>
type AiAttachment={name:string;mime_type:string;data:string;bytes:number}
const acceptedAiTypes=new Set(["image/jpeg","image/png","image/webp","image/bmp","application/pdf","text/plain","text/csv","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"])
const maxAiUploadBytes=2_500_000

function fileBase64(file:Blob){return new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onerror=()=>reject(reader.error);reader.onload=()=>resolve(String(reader.result||"").split(",")[1]||"");reader.readAsDataURL(file)})}
async function prepareAiFile(file:File):Promise<AiAttachment>{
 const extension=file.name.split(".").pop()?.toLowerCase()||""
 let mime=({jpg:"image/jpeg",jpeg:"image/jpeg",png:"image/png",webp:"image/webp",bmp:"image/bmp",txt:"text/plain",csv:"text/csv",pdf:"application/pdf",xlsx:"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"} as Record<string,string>)[extension]||file.type||""
 if(!acceptedAiTypes.has(mime))throw new Error(`${file.name}: use JPG, PNG, WebP, BMP, PDF, XLSX, TXT, or CSV.`)
 if(file.size>maxAiUploadBytes)throw new Error(`${file.name}: use a file no larger than 2.5 MB.`)
 return {name:file.name,mime_type:mime,data:await fileBase64(file),bytes:file.size}
}

export function AiView({bootstrap,onSaved}:{bootstrap:Bootstrap;onSaved:()=>void}){
 const [records,setRecords]=useState<any[]>([])
 const [warnings,setWarnings]=useState<string[]>([])
 const [attachments,setAttachments]=useState<AiAttachment[]>([])
 const [loading,setLoading]=useState(false)
 const [preparing,setPreparing]=useState(false)
 const {register,handleSubmit,formState:{errors}}=useForm<AiForm>({resolver:zodResolver(aiSchema),defaultValues:{year:Number(localISO().slice(0,4)),consent:false,text:""}})
 const addFiles=async(files:FileList|null)=>{
   if(!files?.length)return
   setPreparing(true)
   try{
     const next=[...attachments]
     for(const file of Array.from(files)){
       if(next.length>=5)throw new Error("Upload no more than 5 files at once.")
       next.push(await prepareAiFile(file))
     }
     if(next.reduce((sum,item)=>sum+item.bytes,0)>maxAiUploadBytes)throw new Error("Uploaded files must total 2.5 MB or less.")
     setAttachments(next)
   }catch(error){toast.error(error instanceof Error?error.message:String(error))}
   finally{setPreparing(false)}
 }
 const analyze=async(values:AiForm)=>{
   if(!values.text.trim()&&!attachments.length)return toast.error("Paste work information or upload a file.")
   setLoading(true)
   try{
     const result:any=await postJSON("/api/ai/parse",{...values,attachments:attachments.map(({bytes,...item})=>item)})
     setWarnings(result.warnings||[])
     setRecords((result.records||[]).map((r:any)=>({...r,selected:!!r.ready&&r.confidence!=="low",saved:false,assignments:(r.assignments||[]).map((assignment:any)=>({...assignment,cost_center_text:assignment.cost_center_text||(assignment.cost_centers||[]).map((center:any)=>typeof center==="string"?center:`${center.name} (${center.id})`).join(" ; ")}))})))
     toast.success(`Gemini found ${result.records?.length||0} records. Review before saving.`)
   }catch(error){toast.error(error instanceof Error?error.message:String(error))}
   finally{setLoading(false)}
 }
 const update=(index:number,patch:any)=>setRecords(current=>current.map((record,row)=>row===index?{...record,...patch}:record))
 const updateAssignment=(recordIndex:number,assignmentIndex:number,patch:any)=>setRecords(current=>current.map((record,row)=>row===recordIndex?{...record,assignments:(record.assignments||[]).map((assignment:any,segment:number)=>segment===assignmentIndex?{...assignment,...patch}:assignment)}:record))
 const save=async()=>{
   const selected=records.filter(record=>record.selected&&!record.saved)
   if(!selected.length)return
   const incomplete=selected.find(record=>record.status==="worked"&&(!String(record.worker_name||"").trim()||!(record.assignments||[]).length||(record.assignments||[]).some((assignment:any)=>!String(assignment.site||"").trim()||!String(assignment.cost_center_text||"").trim())))
   if(incomplete)return toast.error("Every worked segment needs a Worker, Site, and Cost Code.")
   try{
     const result:any=await postJSON("/api/ai/apply",{records:selected.map(record=>({worker_name:record.worker_name,date:record.date,status:record.status,regular_hours:record.regular_hours,overtime_hours:Number(record.overtime_hours||0),total_hours:Number(record.total_hours||8),extra_pay:Number(record.extra_pay||0),assignments:(record.assignments||[]).map((assignment:any)=>({site:assignment.site,hours:Number(assignment.hours||0),start_time:assignment.start_time||"",end_time:assignment.end_time||"",cost_codes:String(assignment.cost_center_text||"").split(";").map((value:string)=>value.trim()).filter(Boolean)})),notes:record.notes||""}))})
     setRecords(current=>current.map(record=>record.selected?{...record,saved:true,selected:false}:record))
     toast.success(`Confirmed and saved ${result.saved||selected.length} records.`);onSaved()
   }catch(error){toast.error(error instanceof Error?error.message:String(error))}
 }
 return <div className="page">
   <div className="mb-6"><div className="mb-2 inline-flex items-center gap-2 rounded-full bg-violet-100 px-3 py-1 text-xs font-bold text-violet-700"><Sparkles className="size-3"/>Gemini assisted</div><h1 className="page-title">AI reading</h1><p className="page-subtitle">Analyze pasted text, images, PDFs, Excel, TXT, or CSV files. Review every association before saving.</p></div>
   <div className="grid gap-5 xl:grid-cols-[1.1fr_.9fr]">
     <Card><CardHeader><CardTitle>Add working information</CardTitle><CardDescription>Rows and separated blocks are treated independently so Worker, Site, and Cost Code details do not cross into another record.</CardDescription></CardHeader><CardContent><form onSubmit={handleSubmit(analyze)} className="grid gap-4">
       <Textarea {...register("text")} className="min-h-64 resize-y" placeholder={'07/01 Cristian and Eduardo · texture\n16970 Cypress Way\n\n07/02 Filimon · floor · 1049 Woodland Ave'}/>{errors.text&&<p className="text-xs text-red-600">{errors.text.message}</p>}
       <label className="flex cursor-pointer items-center justify-center gap-2 rounded-xl border border-dashed bg-slate-50 p-4 text-sm font-semibold text-primary hover:border-blue-400 hover:bg-blue-50"><Paperclip className="size-4"/>{preparing?"Preparing files…":"Add images, PDF, Excel, TXT, or CSV"}<input className="hidden" type="file" multiple accept="image/jpeg,image/png,image/webp,image/bmp,application/pdf,text/plain,text/csv,.txt,.csv,.pdf,.xlsx,.bmp" disabled={preparing||loading} onChange={event=>{void addFiles(event.target.files);event.target.value=""}}/></label>
       {attachments.length>0&&<div className="grid gap-2">{attachments.map((item,index)=><div key={`${item.name}-${index}`} className="flex items-center gap-2 rounded-lg border bg-white px-3 py-2 text-xs"><Paperclip className="size-3.5 text-primary"/><span className="min-w-0 flex-1 truncate">{item.name}</span><span className="text-muted-foreground">{Math.ceil(item.bytes/1024)} KB</span><Button type="button" size="icon" variant="ghost" className="size-7 text-red-600" onClick={()=>setAttachments(current=>current.filter((_,row)=>row!==index))}><Trash2 className="size-3.5"/></Button></div>)}</div>}
       <label className="field-label">Entry year<Input type="number" {...register("year",{valueAsNumber:true})}/></label>
       <label className="flex items-start gap-3 rounded-xl border bg-amber-50 p-3 text-xs leading-5 text-amber-900"><input type="checkbox" {...register("consent")} className="mt-1 size-4"/><span>The pasted text and uploaded files will be sent to Google Gemini for extraction. Do not upload information you are not authorized to share.</span></label>{errors.consent&&<p className="text-xs text-red-600">{errors.consent.message}</p>}
       <Button size="lg" disabled={!bootstrap.ai_configured||loading||preparing}>{loading?<LoaderCircle className="size-4 animate-spin"/>:<BrainCircuit className="size-4"/>}{loading?"Gemini is reading…":"Analyze with Gemini"}</Button>{!bootstrap.ai_configured&&<p className="text-center text-xs text-red-600">Gemini API key is not configured on the server.</p>}
     </form></CardContent></Card>
     <Card><CardHeader><CardTitle>Association safeguards</CardTitle><CardDescription>The AI never writes directly to the timesheet.</CardDescription></CardHeader><CardContent className="grid gap-4">{[["1","Each line, row, or separated block is interpreted independently"],["2","Short Site addresses and work keywords are matched locally"],["3","Ambiguous records require correction before saving"]].map(([number,text])=><div className="flex items-center gap-3" key={number}><span className="grid size-8 place-items-center rounded-full bg-accent text-xs font-bold text-primary">{number}</span><span className="text-sm">{text}</span></div>)}</CardContent></Card>
   </div>
   {(records.length>0||warnings.length>0)&&<Card className="mt-5"><CardHeader className="flex-row items-center justify-between"><div><CardTitle>Review extracted records</CardTitle><CardDescription>Correct every Worker, Site, and Cost Code association before confirming.</CardDescription></div><Button disabled={!records.some(record=>record.selected&&!record.saved)} onClick={save}><Check className="size-4"/>Confirm selected</Button></CardHeader><CardContent className="grid gap-3">
     {warnings.map((warning,index)=><div key={index} className="rounded-lg bg-amber-50 p-3 text-xs text-amber-800"><AlertTriangle className="mr-2 inline size-4"/>{warning}</div>)}
     {records.map((record,index)=><div key={index} className={`rounded-xl border p-4 ${record.saved?"bg-sky-50 opacity-75":record.issues?.length?"border-amber-300":""}`}><div className="mb-3 flex flex-wrap items-center gap-2"><input type="checkbox" checked={!!record.selected} disabled={record.saved} onChange={event=>update(index,{selected:event.target.checked})}/><Badge variant={record.confidence==="high"?"success":"warning"}>{record.confidence||"low"} confidence</Badge>{record.existing&&<Badge>Updates existing day</Badge>}<span className="ml-auto max-w-full text-xs text-muted-foreground">{record.source_excerpt}</span></div><div className="grid gap-3 md:grid-cols-3">
       <label className="field-label">Date<Input type="date" value={record.date||""} onChange={event=>update(index,{date:event.target.value})}/></label>
       <label className="field-label">Worker<Input list="workers" value={record.worker_name||""} onChange={event=>update(index,{worker_name:event.target.value})}/></label>
       <label className="field-label">Status<select className="h-10 rounded-xl border bg-white px-3" value={record.status||"worked"} onChange={event=>update(index,{status:event.target.value,assignments:event.target.value==="worked"&&!(record.assignments||[]).length?[{site:"",cost_center_text:"",hours:0,start_time:"",end_time:""}]:record.assignments})}><option value="worked">Worked</option><option value="sick_leave">Sick leave</option><option value="off">Off</option></select></label>
       <label className="field-label">Total hours<Input type="number" step=".5" value={record.total_hours??8} disabled={record.status!=="worked"} onChange={event=>update(index,{total_hours:event.target.value})}/></label>
       <label className="field-label">Overtime<Input type="number" step=".5" value={record.overtime_hours||0} disabled={record.status!=="worked"} onChange={event=>update(index,{overtime_hours:event.target.value})}/></label>
       {record.status==="worked"&&<div className="grid gap-2 md:col-span-3"><span className="text-xs font-bold text-slate-700">Matched work segments</span>{(record.assignments||[]).map((assignment:any,segment:number)=><div key={segment} className="grid gap-2 rounded-lg border bg-slate-50 p-3 md:grid-cols-[1.2fr_1.2fr_.55fr_auto]"><label className="field-label">Site<Input list="locations" value={assignment.site||""} onChange={event=>updateAssignment(index,segment,{site:event.target.value})}/></label><label className="field-label">Cost Codes<Input list="centers" value={assignment.cost_center_text||""} onChange={event=>updateAssignment(index,segment,{cost_center_text:event.target.value})}/></label><label className="field-label">Hours<Input type="number" step=".5" value={assignment.hours||0} onChange={event=>updateAssignment(index,segment,{hours:event.target.value})}/></label><Button type="button" size="icon" variant="ghost" className="self-end text-red-600" onClick={()=>update(index,{assignments:(record.assignments||[]).filter((_:any,row:number)=>row!==segment)})}><Trash2 className="size-4"/></Button>{assignment.issues?.length>0&&<p className="text-xs text-amber-700 md:col-span-4">{assignment.issues.join(" · ")}</p>}</div>)}<Button type="button" variant="outline" className="justify-self-start" onClick={()=>update(index,{assignments:[...(record.assignments||[]),{site:"",cost_center_text:"",hours:0,start_time:"",end_time:""}]})}>+ Add Site & Cost Code</Button></div>}
     </div>{record.issues?.length>0&&<p className="mt-3 text-xs text-amber-700">{record.issues.join(" · ")}</p>}</div>)}
   </CardContent></Card>}
 </div>
}

export function TransferView({bootstrap}:{bootstrap:Bootstrap}){
 void bootstrap
 const [preview,setPreview]=useState<any>(null);const [loading,setLoading]=useState(false);const [importing,setImporting]=useState(false);const [result,setResult]=useState<any>(null)
 const [workbook,setWorkbook]=useState<any>(null);const [workbookLoading,setWorkbookLoading]=useState(false)
 useEffect(()=>{void api<any>("/api/lark/workbook").then(setWorkbook).catch(()=>{})},[])
 const configureWorkbook=async()=>{setWorkbookLoading(true);try{const value:any=await postJSON("/api/lark/workbook",{action:workbook?.configured?"refresh":"initialize"});setWorkbook(value);toast.success(`${value.work_cells.toLocaleString()} work cells reflected in Lark Sheets.`)}catch(e){toast.error(e instanceof Error?e.message:String(e))}finally{setWorkbookLoading(false)}}
 const loadPreview=async()=>{setLoading(true);try{const value:any=await api("/api/lark/migration");setPreview(value);setResult(null);toast.success("Cloud workbooks verified. No records were changed.")}catch(e){toast.error(e instanceof Error?e.message:String(e))}finally{setLoading(false)}}
 const importVerified=async()=>{if(!preview?.safe_to_write)return toast.error("Run a successful preview first.");if(!window.confirm(`Import ${preview.counts.work_days.toLocaleString()} work days and ${preview.counts.location_entries.toLocaleString()} site entries into Lark Base? Existing keyed records will not be overwritten.`))return;setImporting(true);setResult(null);const results:any={};try{const stages=["workers","cost_centers","work_days","location_entries","audit"];for(const [index,stage] of stages.entries()){toast.info(`Migration step ${index+1} of ${stages.length}: ${stage.replaceAll("_"," ")}`);const value:any=await postJSON("/api/lark/migration",{confirm:"IMPORT VERIFIED PREVIEW",stage});results[value.table]=value.result;toast.success(`${value.table} complete · ${value.result.created} created · ${value.result.already_present} already present`)}setResult({results});toast.success("Verified workforce data imported into Lark Base.")}catch(e){toast.error(`${e instanceof Error?e.message:String(e)} You can safely click Import again to resume.`)}finally{setImporting(false)}}
 const metrics=preview?[['Workers',preview.counts.workers],['Work days',preview.counts.work_days],['Sites',preview.counts.location_entries],['Cost codes',preview.counts.cost_centers]]:[]
 return <div className="page"><div className="mb-6"><h1 className="page-title">Cloud data migration</h1><p className="page-subtitle">Maintain the connected work-schedule spreadsheet and verify controlled Lark Drive imports.</p></div><Card className="mb-5"><CardHeader><CardTitle>Connected work-schedule spreadsheet</CardTitle><CardDescription>One Excel-style Lark Sheet with payroll-period tabs, dates across the top, workers down the first column, and complete normalized work blocks in each cell.</CardDescription></CardHeader><CardContent><div className="flex flex-wrap items-center gap-3"><Button onClick={configureWorkbook} disabled={workbookLoading}>{workbookLoading?<LoaderCircle className="size-4 animate-spin"/>:<FileSpreadsheet className="size-4"/>}{workbookLoading?"Building spreadsheet…":workbook?.configured?"Refresh spreadsheet":"Create connected spreadsheet"}</Button>{workbook?.url&&<a className="inline-flex min-h-10 items-center gap-2 rounded-lg border px-4 text-sm font-semibold hover:bg-muted" href={workbook.url} target="_blank" rel="noreferrer"><ExternalLink className="size-4"/>Open in Lark</a>}{workbook?.configured&&<span className="text-sm text-muted-foreground">{Number(workbook.workers||0).toLocaleString()} workers · {Number(workbook.sheets||workbook.periods||0).toLocaleString()} period tabs</span>}</div><p className="mt-3 text-xs text-muted-foreground">PostgreSQL remains authoritative. Website changes update the corresponding Sheet cells asynchronously; direct Sheet edits are not imported back.</p></CardContent></Card><Card><CardHeader><CardTitle>2026 standardized workforce data</CardTitle><CardDescription>Preview is read-only. Import creates only missing keyed records, so retrying will not overwrite records already in Base.</CardDescription></CardHeader><CardContent className="grid gap-5"><div className="flex flex-wrap gap-3"><Button onClick={loadPreview} disabled={loading||importing} variant="outline">{loading?<LoaderCircle className="size-4 animate-spin"/>:<FileSpreadsheet className="size-4"/>}{loading?"Checking Lark Drive…":"Preview cloud migration"}</Button><Button onClick={importVerified} disabled={!preview?.safe_to_write||loading||importing}>{importing?<LoaderCircle className="size-4 animate-spin"/>:<Upload className="size-4"/>}{importing?"Importing into Lark Base…":"Import verified preview"}</Button></div>{preview&&<><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{metrics.map(([label,value])=><div className="rounded-xl border bg-slate-50 p-4" key={label}><p className="text-xs font-semibold text-muted-foreground">{label}</p><strong className="mt-1 block text-2xl">{Number(value).toLocaleString()}</strong></div>)}</div><div className={`rounded-xl border p-4 ${preview.safe_to_write?"border-emerald-200 bg-emerald-50":"border-red-200 bg-red-50"}`}><div className="flex items-center gap-2"><Badge variant={preview.safe_to_write?"success":"destructive"}>{preview.safe_to_write?"Verified":"Blocked"}</Badge><strong>{displayDate(preview.date_range.start,true)} – {displayDate(preview.date_range.end,true)}</strong></div><p className="mt-2 text-sm">{preview.counts.warnings} source entries were flagged during preview. Historical cost codes remain blank until confirmed.</p></div></>}{result&&<div className="rounded-xl border border-sky-200 bg-sky-50 p-4"><div className="flex items-center gap-2"><Check className="size-5 text-emerald-700"/><strong>Migration complete</strong></div><p className="mt-2 text-sm">Created {Object.values(result.results||{}).reduce((sum:number,item:any)=>sum+Number(item.created||0),0).toLocaleString()} missing Base records. Existing records were preserved.</p></div>}</CardContent></Card></div>
}
