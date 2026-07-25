import { useEffect, useState } from "react"
import {
  BarChart3,
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
import { api, postJSON } from "@/lib/api"
import { displayDate } from "@/lib/utils"

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
      `${preview.counts.location_entries.toLocaleString()} location entries?`,
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
    ["Locations", preview.counts.location_entries],
    ["Cost centers", preview.counts.cost_centers],
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
            <p className="mt-2 text-sm">{preview.counts.warnings} entries require review. Historical cost centers remain blank until confirmed.</p>
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

export function ExportView() {
  const [access, setAccess] = useState<Access | null>(null)
  const [password, setPassword] = useState("")
  const [unlocking, setUnlocking] = useState(false)
  const [workbook, setWorkbook] = useState<any>(null)
  const [workbookLoading, setWorkbookLoading] = useState(false)

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

  if (!access) return <AccessLoading label="Checking Export access…" />
  if (!access.authorized) {
    return <div className="page"><div className="mx-auto max-w-lg py-10">
      <Card>
        <CardHeader>
          <span className="mb-2 grid size-12 place-items-center rounded-xl bg-blue-50 text-primary"><LockKeyhole className="size-6" /></span>
          <CardTitle>Export is password protected</CardTitle>
          <CardDescription>Schedule spreadsheets and future invoice/report exports require the separate Export password.</CardDescription>
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
      <p className="page-subtitle">Create controlled schedule files now, with invoice and reporting templates ready to be added later.</p>
    </div>
    <div className="grid gap-5 xl:grid-cols-3">
      <Card className="xl:col-span-2">
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
        <CardHeader><CardTitle>Available format</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <ExportType icon={FileSpreadsheet} title="Work schedule" detail="Connected Lark Sheet · ready" ready />
          <ExportType icon={Receipt} title="Invoice / 发票" detail="Waiting for sample template" />
          <ExportType icon={BarChart3} title="Report / 汇报" detail="Waiting for sample template" />
          <ExportType icon={FileText} title="Additional forms" detail="Framework ready for future formats" />
        </CardContent>
      </Card>
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

function ExportType({ icon: Icon, title, detail, ready = false }: { icon: typeof FileSpreadsheet; title: string; detail: string; ready?: boolean }) {
  return <div className="flex items-center gap-3 rounded-xl border p-3">
    <span className="grid size-9 place-items-center rounded-lg bg-blue-50 text-primary"><Icon className="size-4" /></span>
    <div className="min-w-0 flex-1"><strong className="block text-sm">{title}</strong><span className="block truncate text-xs text-muted-foreground">{detail}</span></div>
    <Badge variant={ready ? "success" : "secondary"}>{ready ? "Ready" : "Planned"}</Badge>
  </div>
}
