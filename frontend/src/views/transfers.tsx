import { useEffect, useState } from "react"
import {
  ArrowLeft,
  Check,
  ChevronRight,
  ExternalLink,
  FileSpreadsheet,
  FileText,
  LoaderCircle,
  LockKeyhole,
  MapPin,
  Receipt,
  ShieldCheck,
  Upload,
  Users,
} from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input, Textarea } from "@/components/ui/input"
import { api, downloadJSON, postJSON } from "@/lib/api"
import type { Bootstrap } from "@/lib/types"
import { displayDate, localISO } from "@/lib/utils"

type Access = {
  authorized: boolean
  access_type: string
  password_configured?: boolean
  admin_allowlist_configured?: boolean
}

function newInvoiceNumber() {
  const now = new Date()
  const pad = (value: number) => String(value).padStart(2, "0")
  return `SC-${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`
}

export function ImportView() {
  const [access, setAccess] = useState<Access | null>(null)
  const [preview, setPreview] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [importing, setImporting] = useState(false)
  const [result, setResult] = useState<any>(null)

  useEffect(() => {
    void api<Access>("/api/import/access")
      .then(setAccess)
      .catch(error => toast.error(error instanceof Error ? error.message : String(error)))
  }, [])

  const loadPreview = async () => {
    setLoading(true)
    try {
      const value: any = await api("/api/lark/migration")
      setPreview(value)
      setResult(null)
      toast.success("Cloud workbooks verified. No records were changed.")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setLoading(false)
    }
  }

  const importVerified = async () => {
    if (!preview?.safe_to_write) {
      toast.error("Run a successful preview first.")
      return
    }
    if (!window.confirm(
      `Import ${preview.counts.work_days.toLocaleString()} work days and ` +
      `${preview.counts.location_entries.toLocaleString()} site entries?`,
    )) return
    setImporting(true)
    setResult(null)
    const results: Record<string, any> = {}
    try {
      const stages = [
        "workers",
        "cost_centers",
        "work_days",
        "location_entries",
        "audit",
      ]
      for (const [index, stage] of stages.entries()) {
        toast.info(`Import step ${index + 1} of ${stages.length}: ${stage.replaceAll("_", " ")}`)
        const value: any = await postJSON("/api/lark/migration", {
          confirm: "IMPORT VERIFIED PREVIEW",
          stage,
        })
        results[value.table] = value.result
      }
      setResult({ results })
      toast.success("Verified workforce data imported.")
    } catch (error) {
      toast.error(
        `${error instanceof Error ? error.message : String(error)} ` +
        "You can safely run Import again to resume.",
      )
    } finally {
      setImporting(false)
    }
  }

  if (!access) return <AccessLoading label="Checking Import access…" />
  if (!access.authorized) {
    return <div className="page"><AccessCard
      title="Import is restricted"
      description="Only a Lark account whose open ID is listed in LARK_ADMIN_OPEN_IDS can preview or import source workbooks."
      detail={access.admin_allowlist_configured
        ? "Sign in using a configured administrator account."
        : "No administrator IDs are configured in Vercel yet."}
    /></div>
  }

  const metrics = preview ? [
    ["Workers", preview.counts.workers],
    ["Work days", preview.counts.work_days],
    ["Sites", preview.counts.location_entries],
    ["Cost codes", preview.counts.cost_centers],
  ] : []

  return <div className="page">
    <div className="mb-6">
      <div className="mb-2 inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-xs font-bold text-blue-700"><ShieldCheck className="size-3" />Lark administrator only</div>
      <h1 className="page-title">Import</h1>
      <p className="page-subtitle">Verify controlled source workbooks before adding missing records to the operational database.</p>
    </div>
    <Card>
      <CardHeader>
        <CardTitle>Standardized workforce source files</CardTitle>
        <CardDescription>Preview is read-only. Import creates only missing keyed records, so retrying does not overwrite records already present.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-5">
        <div className="flex flex-wrap gap-3">
          <Button onClick={loadPreview} disabled={loading || importing} variant="outline">
            {loading ? <LoaderCircle className="size-4 animate-spin" /> : <FileSpreadsheet className="size-4" />}
            {loading ? "Checking Lark Drive…" : "Preview source files"}
          </Button>
          <Button onClick={importVerified} disabled={!preview?.safe_to_write || loading || importing}>
            {importing ? <LoaderCircle className="size-4 animate-spin" /> : <Upload className="size-4" />}
            {importing ? "Importing…" : "Import verified preview"}
          </Button>
        </div>
        {preview && <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {metrics.map(([label, value]) => <div className="rounded-xl border bg-slate-50 p-4" key={label}>
              <p className="text-xs font-semibold text-muted-foreground">{label}</p>
              <strong className="mt-1 block text-2xl">{Number(value).toLocaleString()}</strong>
            </div>)}
          </div>
          <div className={`rounded-xl border p-4 ${preview.safe_to_write ? "border-emerald-200 bg-emerald-50" : "border-red-200 bg-red-50"}`}>
            <div className="flex items-center gap-2">
              <Badge variant={preview.safe_to_write ? "success" : "destructive"}>
                {preview.safe_to_write ? "Verified" : "Blocked"}
              </Badge>
              <strong>{displayDate(preview.date_range.start, true)} – {displayDate(preview.date_range.end, true)}</strong>
            </div>
            <p className="mt-2 text-sm">{preview.counts.warnings} entries require review. Historical cost codes remain blank until confirmed.</p>
          </div>
        </>}
        {result && <div className="rounded-xl border border-sky-200 bg-sky-50 p-4">
          <div className="flex items-center gap-2"><Check className="size-5 text-emerald-700" /><strong>Import complete</strong></div>
          <p className="mt-2 text-sm">Existing records were preserved. The same import can be safely resumed if a stage was interrupted.</p>
        </div>}
      </CardContent>
    </Card>
  </div>
}

export function ExportView({ bootstrap }: { bootstrap: Bootstrap }) {
  const today = localISO()
  const [mode, setMode] = useState<"schedule" | "auditor" | "invoice" | null>(null)
  const [access, setAccess] = useState<Access | null>(null)
  const [password, setPassword] = useState("")
  const [unlocking, setUnlocking] = useState(false)
  const [workbook, setWorkbook] = useState<any>(null)
  const [workbookLoading, setWorkbookLoading] = useState(false)
  const [auditorFrom, setAuditorFrom] = useState(`${today.slice(0, 7)}-01`)
  const [auditorTo, setAuditorTo] = useState(today)
  const [auditorWorkers, setAuditorWorkers] = useState<Set<string>>(new Set())
  const [auditorSites, setAuditorSites] = useState<Set<string>>(new Set())
  const [auditorLoading, setAuditorLoading] = useState(false)
  const [invoiceLoading, setInvoiceLoading] = useState<"xlsx" | "pdf" | null>(null)
  const [invoiceNumber, setInvoiceNumber] = useState(newInvoiceNumber)
  const [invoiceDate, setInvoiceDate] = useState(today)
  const [paymentTerms, setPaymentTerms] = useState("Upon Receipt")
  const [billToName, setBillToName] = useState("")
  const [billToAddress, setBillToAddress] = useState("")
  const [billToPhone, setBillToPhone] = useState("")
  const [billToEmail, setBillToEmail] = useState("")
  const [jobAddress, setJobAddress] = useState("")
  const [jobAddressDetail, setJobAddressDetail] = useState("")
  const [invoiceDescription, setInvoiceDescription] = useState("")
  const [unitPrice, setUnitPrice] = useState("")
  const [invoiceAmount, setInvoiceAmount] = useState("")

  const checkAccess = async () => {
    const value = await api<Access>("/api/export/access")
    setAccess(value)
  }
  useEffect(() => {
    void checkAccess().catch(error =>
      toast.error(error instanceof Error ? error.message : String(error)),
    )
  }, [])

  const unlock = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!password) return
    setUnlocking(true)
    try {
      await postJSON("/api/export/unlock", { password })
      setPassword("")
      await checkAccess()
      toast.success("Export unlocked for 8 hours.")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setUnlocking(false)
    }
  }

  const configureWorkbook = async () => {
    setWorkbookLoading(true)
    try {
      const value: any = await postJSON("/api/lark/workbook", {
        action: workbook?.configured ? "refresh" : "initialize",
      })
      setWorkbook(value)
      toast.success(`${Number(value.work_cells || 0).toLocaleString()} work cells exported to Lark Sheets.`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setWorkbookLoading(false)
    }
  }

  const openMode = async (nextMode: "schedule" | "auditor" | "invoice") => {
    if (nextMode === "auditor") {
      setAuditorWorkers(new Set())
      setAuditorSites(new Set())
    }
    if (nextMode === "invoice") setInvoiceNumber(newInvoiceNumber())
    setMode(nextMode)
    if (nextMode !== "schedule" || workbook) return
    setWorkbookLoading(true)
    try {
      setWorkbook(await api<any>("/api/lark/workbook"))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setWorkbookLoading(false)
    }
  }

  const generateAuditor = async () => {
    if (!auditorFrom || !auditorTo || auditorFrom > auditorTo) return toast.error("Choose a valid From and To date range.")
    if (!auditorWorkers.size) return toast.error("Select at least one worker.")
    if (!auditorSites.size) return toast.error("Select at least one site.")
    setAuditorLoading(true)
    try {
      const filename = await downloadJSON("/api/export/template", {
        template: "auditor",
        from: auditorFrom,
        to: auditorTo,
        worker_ids: Array.from(auditorWorkers),
        sites: Array.from(auditorSites),
      })
      toast.success(`${filename} downloaded.`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setAuditorLoading(false)
    }
  }

  const generateInvoice = async (format: "xlsx" | "pdf") => {
    if (!billToName.trim()) return toast.error("Enter the Bill To name.")
    if (!billToAddress.trim()) return toast.error("Enter the Bill To address.")
    if (!jobAddress.trim()) return toast.error("Enter the Job address.")
    if (!invoiceDescription.trim()) return toast.error("Enter the invoice Description.")
    if (Number(unitPrice) <= 0) return toast.error("Enter a Unit price greater than 0.")
    if (Number(invoiceAmount) <= 0) return toast.error("Enter an Amount greater than 0.")
    setInvoiceLoading(format)
    try {
      const filename = await downloadJSON("/api/export/template", {
        template: "invoice",
        format,
        invoice_number: invoiceNumber,
        invoice_date: invoiceDate,
        payment_terms: paymentTerms,
        bill_to_name: billToName,
        bill_to_address: billToAddress,
        bill_to_phone: billToPhone,
        bill_to_email: billToEmail,
        job_address: jobAddress,
        job_address_detail: jobAddressDetail,
        description: invoiceDescription,
        unit_price: Number(unitPrice),
        amount: Number(invoiceAmount),
      })
      toast.success(`${filename} downloaded.`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setInvoiceLoading(null)
    }
  }

  if (!access) return <AccessLoading label="Checking Export access…" />
  if (!access.authorized) {
    return <div className="page"><div className="mx-auto max-w-lg py-10">
      <Card>
        <CardHeader>
          <span className="mb-2 grid size-12 place-items-center rounded-xl bg-blue-50 text-primary"><LockKeyhole className="size-6" /></span>
          <CardTitle>Export is password protected</CardTitle>
          <CardDescription>Schedule spreadsheets, auditor reports, and invoices require the separate Export password.</CardDescription>
        </CardHeader>
        <CardContent>
          {access.password_configured ? <form className="grid gap-3" onSubmit={unlock}>
            <label className="field-label">Export password
              <Input autoFocus type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} />
            </label>
            <Button type="submit" disabled={!password || unlocking}>
              {unlocking ? <LoaderCircle className="size-4 animate-spin" /> : <LockKeyhole className="size-4" />}
              {unlocking ? "Unlocking…" : "Unlock Export"}
            </Button>
          </form> : <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            Add <code>EXPORT_PASSWORD</code> to the Vercel Production environment and redeploy.
          </div>}
        </CardContent>
      </Card>
    </div></div>
  }

  const header = (title: string, description: string) => <div className="mb-6">
    <Button variant="ghost" className="mb-3 -ml-3" onClick={() => setMode(null)}><ArrowLeft className="size-4" />Back to export options</Button>
    <div className="mb-2 inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-xs font-bold text-blue-700"><LockKeyhole className="size-3" />Password protected</div>
    <h1 className="page-title">{title}</h1>
    <p className="page-subtitle">{description}</p>
  </div>

  if (mode === "schedule") return <div className="page">
    {header("Connected work-schedule spreadsheet", "Open or refresh the one-way Lark spreadsheet mirror.")}
    <Card><CardHeader><CardTitle>Speed Construction Work Schedule</CardTitle><CardDescription>Payroll-period tabs, dates across the top, workers down the first column, and normalized work blocks in each cell.</CardDescription></CardHeader><CardContent>
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={configureWorkbook} disabled={workbookLoading}>
          {workbookLoading ? <LoaderCircle className="size-4 animate-spin" /> : <FileSpreadsheet className="size-4" />}
          {workbookLoading ? "Loading spreadsheet…" : workbook?.configured ? "Refresh spreadsheet" : "Create connected spreadsheet"}
        </Button>
        {workbook?.url && <a className="inline-flex min-h-10 items-center gap-2 rounded-lg border px-4 text-sm font-semibold hover:bg-muted" href={workbook.url} target="_blank" rel="noreferrer"><ExternalLink className="size-4" />Open in Lark</a>}
      </div>
      <p className="mt-3 text-xs text-muted-foreground">PostgreSQL remains authoritative. Direct Sheet edits never overwrite website records.</p>
    </CardContent></Card>
  </div>

  if (mode === "auditor") return <div className="page">
    {header("Worker Compensation Auditor Report", "Choose the reporting period and any combination of workers and sites.")}
    <div className="grid gap-5">
      <Card><CardHeader><CardTitle>1. Reporting period</CardTitle><CardDescription>Both dates are included in the report.</CardDescription></CardHeader><CardContent className="grid gap-3 sm:grid-cols-2">
        <label className="field-label">From<Input type="date" value={auditorFrom} onChange={event => setAuditorFrom(event.target.value)} /></label>
        <label className="field-label">To<Input type="date" value={auditorTo} onChange={event => setAuditorTo(event.target.value)} /></label>
      </CardContent></Card>
      <div className="grid gap-5 xl:grid-cols-2">
        <MultiSelectList title="2. Workers" icon={Users} items={bootstrap.workers.map(worker => ({ id: String(worker.id), label: worker.name }))} selected={auditorWorkers} onChange={setAuditorWorkers} placeholder="Search workers…" />
        <MultiSelectList title="3. Sites" icon={MapPin} items={bootstrap.locations.map(site => ({ id: site, label: site }))} selected={auditorSites} onChange={setAuditorSites} placeholder="Search sites…" />
      </div>
      <Card><CardContent className="flex flex-col gap-4 !pt-5 sm:flex-row sm:items-center sm:justify-between"><div><strong className="block">{auditorWorkers.size&&auditorSites.size?"Ready to generate":"Complete the selection"}</strong><p className="text-sm text-muted-foreground">{auditorWorkers.size} worker{auditorWorkers.size===1?"":"s"} · {auditorSites.size} site{auditorSites.size===1?"":"s"} · {displayDate(auditorFrom,true)} – {displayDate(auditorTo,true)}</p></div><Button size="lg" onClick={() => void generateAuditor()} disabled={auditorLoading||!auditorWorkers.size||!auditorSites.size}>{auditorLoading?<LoaderCircle className="size-4 animate-spin"/>:<FileSpreadsheet className="size-4" />}{auditorLoading?"Generating auditor report…":"Download auditor report"}</Button></CardContent></Card>
    </div>
  </div>

  if (mode === "invoice") return <div className="page">
    {header("Speed Invoice Template", "Complete only the customer, job, and invoice details. Speed Construction information and the invoice number are automatic.")}
    <div className="grid gap-5">
      <Card><CardHeader><div className="flex flex-wrap items-start justify-between gap-3"><div><CardTitle>Fixed invoice information</CardTitle><CardDescription>These company and numbering fields are inserted automatically and cannot be changed here.</CardDescription></div><Badge variant="secondary">Automatic</Badge></div></CardHeader><CardContent className="grid gap-4 sm:grid-cols-2"><div className="rounded-xl border bg-slate-50 p-4 text-sm"><strong className="block">Speed Construction</strong><p className="mt-1 text-muted-foreground">Lic. #1098660 · Logan Du<br/>10275 N De Anza Blvd, Cupertino, CA 95014<br/>(510) 415-5834 · logan@speedcons.com</p></div><div className="rounded-xl border bg-blue-50 p-4 text-sm"><strong className="block text-primary">Invoice number</strong><p className="mt-1 font-semibold tabular-nums text-foreground">{invoiceNumber}</p><p className="mt-1 text-xs text-muted-foreground">Excel and PDF use this same number.</p></div></CardContent></Card>

      <Card><CardHeader><CardTitle>1. Bill To</CardTitle><CardDescription>Information for the customer receiving this invoice.</CardDescription></CardHeader><CardContent className="grid gap-3 sm:grid-cols-2">
        <label className="field-label sm:col-span-2">Customer or company name<Input value={billToName} onChange={event => setBillToName(event.target.value)} placeholder="e.g. 5A Holdings LLC" /></label>
        <label className="field-label sm:col-span-2">Billing address<Input value={billToAddress} onChange={event => setBillToAddress(event.target.value)} placeholder="Street, city, state and ZIP" /></label>
        <label className="field-label">Phone<Input type="tel" value={billToPhone} onChange={event => setBillToPhone(event.target.value)} placeholder="Optional" /></label>
        <label className="field-label">Email<Input type="email" value={billToEmail} onChange={event => setBillToEmail(event.target.value)} placeholder="Optional" /></label>
      </CardContent></Card>

      <Card><CardHeader><CardTitle>2. Job Address</CardTitle><CardDescription>Type any address. Existing sites will appear as suggestions, but a matching site is not required yet.</CardDescription></CardHeader><CardContent className="grid gap-3 sm:grid-cols-2">
        <label className="field-label sm:col-span-2">Job address<Input list="locations" value={jobAddress} onChange={event => setJobAddress(event.target.value)} placeholder="Search an existing site or enter a new address" /></label>
        <label className="field-label sm:col-span-2">Address details<Input value={jobAddressDetail} onChange={event => setJobAddressDetail(event.target.value)} placeholder="City, state, ZIP, unit or lot (optional)" /></label>
      </CardContent></Card>

      <Card><CardHeader><CardTitle>3. Description and Amount</CardTitle><CardDescription>Enter the invoice wording and amounts exactly as they should appear in the spreadsheet.</CardDescription></CardHeader><CardContent className="grid gap-3 sm:grid-cols-2">
        <label className="field-label sm:col-span-2">Description<Textarea value={invoiceDescription} onChange={event => setInvoiceDescription(event.target.value)} placeholder="Describe the work, milestone, deposit, or payment" /></label>
        <label className="field-label">Unit price<Input type="number" min="0" step=".01" value={unitPrice} onChange={event => {const next=event.target.value;setUnitPrice(next);if(!invoiceAmount||invoiceAmount===unitPrice)setInvoiceAmount(next)}} placeholder="0.00" /></label>
        <label className="field-label">Amount<Input type="number" min="0" step=".01" value={invoiceAmount} onChange={event => setInvoiceAmount(event.target.value)} placeholder="0.00" /></label>
      </CardContent></Card>

      <Card><CardHeader><CardTitle>4. Date and Payment</CardTitle><CardDescription>The payment methods and standard footer text already come from the approved template.</CardDescription></CardHeader><CardContent className="grid gap-3 sm:grid-cols-2">
        <label className="field-label">Invoice date<Input type="date" value={invoiceDate} onChange={event => setInvoiceDate(event.target.value)} /></label>
        <label className="field-label">Payment terms<Input list="payment-terms" value={paymentTerms} onChange={event => setPaymentTerms(event.target.value)} placeholder="Upon Receipt" /><datalist id="payment-terms"><option value="Upon Receipt"/><option value="Net 15"/><option value="Net 30"/></datalist></label>
      </CardContent></Card>

      <Card><CardContent className="flex flex-col gap-4 !pt-5 sm:flex-row sm:items-center sm:justify-between"><div><strong className="block">Invoice total</strong><p className="text-2xl font-bold tabular-nums text-primary">${Number(invoiceAmount||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}</p><p className="mt-1 text-xs text-muted-foreground">Choose the format you need. Both files contain the same invoice data.</p></div><div className="flex flex-col gap-2 sm:flex-row"><Button size="lg" variant="outline" onClick={() => void generateInvoice("xlsx")} disabled={invoiceLoading !== null}>{invoiceLoading==="xlsx"?<LoaderCircle className="size-4 animate-spin"/>:<FileSpreadsheet className="size-4" />}{invoiceLoading==="xlsx"?"Generating Excel…":"Download Excel"}</Button><Button size="lg" onClick={() => void generateInvoice("pdf")} disabled={invoiceLoading !== null}>{invoiceLoading==="pdf"?<LoaderCircle className="size-4 animate-spin"/>:<FileText className="size-4" />}{invoiceLoading==="pdf"?"Generating PDF…":"Download PDF"}</Button></div></CardContent></Card>
    </div>
  </div>

  return <div className="page">
    <div className="mb-6"><div className="mb-2 inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-xs font-bold text-blue-700"><LockKeyhole className="size-3" />Password protected</div><h1 className="page-title">Export</h1><p className="page-subtitle">Choose a document. Each export has its own fields and selection rules.</p></div>
    <div className="grid gap-5 lg:grid-cols-3">
      <ExportChoice icon={FileSpreadsheet} title="Work schedule spreadsheet" detail="Open or refresh the connected Lark work schedule." action="Open spreadsheet" onClick={() => void openMode("schedule")} />
      <ExportChoice icon={FileText} title="Worker Compensation Auditor Report" detail="Select a date range, multiple workers, and multiple sites." action="Configure report" onClick={() => void openMode("auditor")} />
      <ExportChoice icon={Receipt} title="Speed Invoice Template" detail="Complete invoice-specific work and billing information." action="Configure invoice" onClick={() => void openMode("invoice")} />
    </div>
  </div>
}

function MultiSelectList({ title, icon: Icon, items, selected, onChange, placeholder }: { title: string; icon: typeof Users; items: { id: string; label: string }[]; selected: Set<string>; onChange: (value: Set<string>) => void; placeholder: string }) {
  const [search, setSearch] = useState("")
  const visible = items.filter(item => item.label.toLowerCase().includes(search.toLowerCase()))
  const toggle = (id: string) => { const next = new Set(selected); next.has(id) ? next.delete(id) : next.add(id); onChange(next) }
  const allSelected = items.length > 0 && selected.size === items.length
  const toggleAll = () => onChange(allSelected ? new Set() : new Set(items.map(item => item.id)))
  return <Card><CardHeader><div className="flex items-start justify-between gap-3"><div><span className="mb-2 grid size-10 place-items-center rounded-xl bg-blue-50 text-primary"><Icon className="size-5" /></span><CardTitle>{title}</CardTitle><CardDescription>{selected.size} of {items.length} selected</CardDescription></div><Button size="sm" variant={allSelected?"outline":"default"} onClick={toggleAll}>{allSelected?"Clear all":"Select all"}</Button></div></CardHeader><CardContent className="grid gap-3">
    <Input value={search} onChange={event => setSearch(event.target.value)} placeholder={placeholder} />
    <div className="max-h-64 overflow-y-auto rounded-xl border">
      {visible.map(item => <label className={`flex cursor-pointer items-center gap-3 border-b px-3 py-2.5 text-sm transition-colors last:border-b-0 ${selected.has(item.id)?"bg-blue-50 font-semibold text-blue-950 hover:bg-blue-100":"hover:bg-slate-50"}`} key={item.id}><input type="checkbox" className="size-4 accent-[#2563eb]" checked={selected.has(item.id)} onChange={() => toggle(item.id)} /><span>{item.label}</span></label>)}
      {!visible.length&&<p className="p-6 text-center text-sm text-muted-foreground">No matches.</p>}
    </div>
  </CardContent></Card>
}

function ExportChoice({ icon: Icon, title, detail, action, onClick }: { icon: typeof FileSpreadsheet; title: string; detail: string; action: string; onClick: () => void }) {
  return <Card className="flex flex-col"><CardHeader className="flex-1"><span className="mb-2 grid size-12 place-items-center rounded-xl bg-blue-50 text-primary"><Icon className="size-6" /></span><CardTitle>{title}</CardTitle><CardDescription>{detail}</CardDescription></CardHeader><CardContent><Button className="w-full justify-between" variant="outline" onClick={onClick}>{action}<ChevronRight className="size-4" /></Button></CardContent></Card>
}

function AccessLoading({ label }: { label: string }) {
  return <div className="page"><Card><CardContent className="flex items-center justify-center gap-3 py-20 text-sm text-muted-foreground"><LoaderCircle className="size-5 animate-spin" />{label}</CardContent></Card></div>
}

function AccessCard({ title, description, detail }: { title: string; description: string; detail: string }) {
  return <div className="mx-auto max-w-lg py-10"><Card>
    <CardHeader>
      <span className="mb-2 grid size-12 place-items-center rounded-xl bg-blue-50 text-primary"><ShieldCheck className="size-6" /></span>
      <CardTitle>{title}</CardTitle>
      <CardDescription>{description}</CardDescription>
    </CardHeader>
    <CardContent><div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">{detail}</div></CardContent>
  </Card></div>
}
