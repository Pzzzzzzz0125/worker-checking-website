import { useEffect, useState } from "react"
import {
  Check,
  ExternalLink,
  FileSpreadsheet,
  FileText,
  LoaderCircle,
  LockKeyhole,
  Receipt,
  ShieldCheck,
  Upload,
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
import { Input } from "@/components/ui/input"
import { api, downloadJSON, postJSON } from "@/lib/api"
import type { Bootstrap } from "@/lib/types"
import { displayDate, localISO } from "@/lib/utils"

type Access = {
  authorized: boolean
  access_type: string
  password_configured?: boolean
  admin_allowlist_configured?: boolean
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
  const due = new Date(`${today}T12:00:00`)
  due.setDate(due.getDate() + 30)
  const [access, setAccess] = useState<Access | null>(null)
  const [password, setPassword] = useState("")
  const [unlocking, setUnlocking] = useState(false)
  const [workbook, setWorkbook] = useState<any>(null)
  const [workbookLoading, setWorkbookLoading] = useState(false)
  const [from, setFrom] = useState(`${today.slice(0, 7)}-01`)
  const [to, setTo] = useState(today)
  const [site, setSite] = useState("")
  const [workerId, setWorkerId] = useState("")
  const [auditorLoading, setAuditorLoading] = useState(false)
  const [invoiceLoading, setInvoiceLoading] = useState(false)
  const [billTo, setBillTo] = useState("")
  const [invoiceNumber, setInvoiceNumber] = useState(`SC-${today.replaceAll("-", "")}`)
  const [invoiceDate, setInvoiceDate] = useState(today)
  const [paymentDue, setPaymentDue] = useState(due.toISOString().slice(0, 10))
  const [billingRate, setBillingRate] = useState("")

  const checkAccess = async () => {
    const value = await api<Access>("/api/export/access")
    setAccess(value)
    if (value.authorized) {
      setWorkbook(await api<any>("/api/lark/workbook"))
    }
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

  const commonFilters = () => ({
    from,
    to,
    site: site.trim(),
    worker_id: workerId,
  })

  const generateAuditor = async () => {
    if (!from || !to || from > to) return toast.error("Choose a valid From and To date range.")
    setAuditorLoading(true)
    try {
      const filename = await downloadJSON("/api/export/template", {
        template: "auditor",
        ...commonFilters(),
      })
      toast.success(`${filename} downloaded.`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setAuditorLoading(false)
    }
  }

  const generateInvoice = async () => {
    if (!from || !to || from > to) return toast.error("Choose a valid From and To date range.")
    if (!billTo.trim()) return toast.error("Enter Bill To before generating the invoice.")
    if (Number(billingRate) <= 0) return toast.error("Enter a billing rate greater than 0.")
    setInvoiceLoading(true)
    try {
      const filename = await downloadJSON("/api/export/template", {
        template: "invoice",
        ...commonFilters(),
        bill_to: billTo,
        invoice_number: invoiceNumber,
        invoice_date: invoiceDate,
        payment_due: paymentDue,
        billing_rate: Number(billingRate),
      })
      toast.success(`${filename} downloaded.`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setInvoiceLoading(false)
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

  return <div className="page">
    <div className="mb-6">
      <div className="mb-2 inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-xs font-bold text-blue-700"><LockKeyhole className="size-3" />Password protected</div>
      <h1 className="page-title">Export</h1>
      <p className="page-subtitle">Generate approved Excel templates from a selected date range, site, and worker.</p>
    </div>
    <div className="grid gap-5">
      <Card>
        <CardHeader>
          <CardTitle>Connected work-schedule spreadsheet</CardTitle>
          <CardDescription>One Excel-style Lark Sheet with payroll-period tabs, dates across the top, workers down the first column, and complete work blocks in each cell.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={configureWorkbook} disabled={workbookLoading}>
              {workbookLoading ? <LoaderCircle className="size-4 animate-spin" /> : <FileSpreadsheet className="size-4" />}
              {workbookLoading ? "Building spreadsheet…" : workbook?.configured ? "Refresh spreadsheet" : "Create connected spreadsheet"}
            </Button>
            {workbook?.url && <a className="inline-flex min-h-10 items-center gap-2 rounded-lg border px-4 text-sm font-semibold hover:bg-muted" href={workbook.url} target="_blank" rel="noreferrer">
              <ExternalLink className="size-4" />Open in Lark
            </a>}
          </div>
          <p className="mt-3 text-xs text-muted-foreground">One-way connection: PostgreSQL updates Lark Sheets asynchronously. Direct Sheet edits never overwrite website records.</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Work-record filters</CardTitle>
          <CardDescription>Leave Site or Worker blank to include every matching active worker or site.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <label className="field-label">From<Input type="date" value={from} onChange={event => setFrom(event.target.value)} /></label>
          <label className="field-label">To<Input type="date" value={to} onChange={event => setTo(event.target.value)} /></label>
          <label className="field-label">Site<Input list="locations" value={site} onChange={event => setSite(event.target.value)} placeholder="All sites" /></label>
          <label className="field-label">Worker
            <select className="h-11 rounded-lg border bg-white px-3 text-sm" value={workerId} onChange={event => setWorkerId(event.target.value)}>
              <option value="">All active workers</option>
              {bootstrap.workers.map(worker => <option value={worker.id} key={worker.id}>{worker.name}</option>)}
            </select>
          </label>
        </CardContent>
      </Card>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <span className="mb-1 grid size-11 place-items-center rounded-xl bg-blue-50 text-primary"><FileText className="size-5" /></span>
            <CardTitle>Worker Compensation Auditor Report</CardTitle>
            <CardDescription>One row per worker, date, site, and cost-code allocation, including start/end time and California regular/OT allocation.</CardDescription>
          </CardHeader>
          <CardContent>
            <Button className="w-full" size="lg" onClick={() => void generateAuditor()} disabled={auditorLoading || invoiceLoading}>
              {auditorLoading ? <LoaderCircle className="size-4 animate-spin" /> : <FileSpreadsheet className="size-4" />}
              {auditorLoading ? "Generating auditor report…" : "Download auditor report"}
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <span className="mb-1 grid size-11 place-items-center rounded-xl bg-blue-50 text-primary"><Receipt className="size-5" /></span>
            <CardTitle>Speed Invoice Template</CardTitle>
            <CardDescription>The amount is calculated from selected labor hours × the billing rate entered here. Worker salary rates are not used as customer billing rates.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-2">
            <label className="field-label sm:col-span-2">Bill To<Input value={billTo} onChange={event => setBillTo(event.target.value)} placeholder="Customer or company name" /></label>
            <label className="field-label">Invoice number<Input value={invoiceNumber} onChange={event => setInvoiceNumber(event.target.value)} /></label>
            <label className="field-label">Billing rate / labor hour<Input type="number" min="0" step=".01" value={billingRate} onChange={event => setBillingRate(event.target.value)} placeholder="0.00" /></label>
            <label className="field-label">Invoice date<Input type="date" value={invoiceDate} onChange={event => setInvoiceDate(event.target.value)} /></label>
            <label className="field-label">Payment due<Input type="date" value={paymentDue} onChange={event => setPaymentDue(event.target.value)} /></label>
            <Button className="sm:col-span-2" size="lg" onClick={() => void generateInvoice()} disabled={invoiceLoading || auditorLoading}>
              {invoiceLoading ? <LoaderCircle className="size-4 animate-spin" /> : <Receipt className="size-4" />}
              {invoiceLoading ? "Generating invoice…" : "Download Speed invoice"}
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  </div>
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
