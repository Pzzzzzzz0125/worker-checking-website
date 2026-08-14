import { useEffect, useState } from "react"
import {
  Check,
  ClipboardCopy,
  LoaderCircle,
  RefreshCw,
  Settings2,
  ShieldCheck,
  UserCheck,
  X,
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

type Role = "viewer" | "entry_user" | "schedule_manager" | "super_admin"
type AccessUser = {
  open_id: string
  name: string
  avatar: string
  stored_role: Role
  role: Role
  role_label: string
  env_super_admin: boolean
  first_seen_at: string
  last_seen_at: string
}
type AccessRequest = {
  id: number
  open_id: string
  name: string
  avatar: string
  current_role: Role
  requested_role: Role
  requested_role_label: string
  reason: string
  status: "pending" | "approved" | "rejected" | "cancelled"
  requested_at: string
  review_note: string
}
type AccessSettings = {
  user: AccessUser
  permissions: {
    can_view: boolean
    can_enter: boolean
    can_manage_schedule: boolean
    can_approve_conflicts: boolean
    can_manage_access: boolean
  }
  requestable_roles: { id: Role; label: string }[]
  latest_request: AccessRequest | null
  pending_requests: AccessRequest[]
  users: AccessUser[]
  notification?: { attempted: number; sent: number; failed: number }
}
type CostCodeStatus = {
  configured: boolean
  source_type: "wiki" | "sheet" | "file" | ""
  database_rows: number
  message?: string
  counts?: {
    source_rows: number
    database_rows: number
    added: number
    updated: number
    deactivated: number
    unchanged: number
  }
}

const roleDetails: Record<Role, string> = {
  viewer: "View authorized workforce information without changing entries.",
  entry_user: "View information and create or update work entries.",
  schedule_manager: "Entry access plus Schedule management and conflict approval.",
  super_admin: "Full access, including approving requests and assigning roles.",
}

const roleLabels: Record<Role, string> = {
  viewer: "Viewer only",
  entry_user: "Entry user",
  schedule_manager: "Schedule manager",
  super_admin: "Super admin",
}

function requestBadge(status: AccessRequest["status"]) {
  if (status === "approved") return <Badge variant="success">Approved</Badge>
  if (status === "rejected") return <Badge variant="destructive">Rejected</Badge>
  if (status === "pending") return <Badge variant="warning">Pending review</Badge>
  return <Badge>Cancelled</Badge>
}

function timeLabel(value: string) {
  if (!value) return ""
  return new Intl.DateTimeFormat(undefined, {
    month: "short", day: "numeric", year: "numeric",
    hour: "numeric", minute: "2-digit",
  }).format(new Date(value))
}

export function SettingsView({ onSaved }: { onSaved?: () => Promise<void> | void }) {
  const [data, setData] = useState<AccessSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [requestedRole, setRequestedRole] = useState<Role>("entry_user")
  const [reason, setReason] = useState("")
  const [costCodes, setCostCodes] = useState<CostCodeStatus | null>(null)
  const [syncingCostCodes, setSyncingCostCodes] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const access = await api<AccessSettings>("/api/settings/access")
      setData(access)
      if (access.permissions.can_manage_access) {
        setCostCodes(await api<CostCodeStatus>("/api/settings/cost-codes"))
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { void load() }, [])

  const syncCostCodes = async () => {
    setSyncingCostCodes(true)
    try {
      const result = await postJSON<CostCodeStatus>("/api/settings/cost-codes", { action: "sync" })
      setCostCodes(result)
      const counts = result.counts
      toast.success(counts
        ? `Cost Codes synced: ${counts.added} added, ${counts.updated} updated, ${counts.deactivated} old codes archived.`
        : "Cost Codes synced.")
      await onSaved?.()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setSyncingCostCodes(false)
    }
  }

  const mutate = async (body: Record<string, unknown>, success: string) => {
    setSaving(true)
    try {
      const updated = await postJSON<AccessSettings>("/api/settings/access", body)
      setData(updated)
      const notification = (updated as AccessSettings).notification
      toast.success(notification && notification.attempted
        ? `${success} Lark notifications sent: ${notification.sent}/${notification.attempted}.`
        : success)
      window.dispatchEvent(new CustomEvent("speed-permissions-changed", { detail: updated }))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setSaving(false)
    }
  }

  if (loading || !data) return <div className="page"><div className="flex items-center gap-2 text-sm text-muted-foreground"><LoaderCircle className="size-4 animate-spin" />Loading access settings…</div></div>
  const latest = data.latest_request
  const canRequest = data.user.role !== "super_admin"

  return <div className="page">
    <div className="mb-6">
      <h1 className="page-title">Settings</h1>
      <p className="page-subtitle">Your Lark identity is automatic. Request access here; a Super Admin makes the final decision.</p>
    </div>

    <div className="grid gap-5 xl:grid-cols-[.9fr_1.1fr]">
      <Card>
        <CardHeader><CardTitle>Your account</CardTitle><CardDescription>No ID entry is required.</CardDescription></CardHeader>
        <CardContent className="grid gap-4">
          <div className="flex items-center gap-3">
            {data.user.avatar
              ? <img src={data.user.avatar} alt="" className="size-12 rounded-xl object-cover" />
              : <span className="grid size-12 place-items-center rounded-xl bg-blue-50 font-bold text-primary">{data.user.name.slice(0, 2).toUpperCase()}</span>}
            <div className="min-w-0"><strong className="block truncate">{data.user.name || "Lark user"}</strong><Badge variant={data.user.role === "super_admin" ? "success" : "secondary"}>{data.user.role_label}</Badge></div>
          </div>
          <div className="rounded-xl border bg-slate-50 p-3">
            <span className="text-xs font-semibold text-muted-foreground">Lark Open ID</span>
            <div className="mt-1 flex items-center gap-2"><code className="min-w-0 flex-1 truncate text-xs">{data.user.open_id}</code><Button size="sm" variant="outline" onClick={() => {void navigator.clipboard.writeText(data.user.open_id);toast.success("Lark ID copied.")}}><ClipboardCopy className="size-3.5" />Copy</Button></div>
          </div>
          {data.user.env_super_admin && <div className="rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900"><strong>Bootstrap Super Admin</strong><p className="mt-1 text-xs">This account is protected by LARK_ADMIN_OPEN_IDS and cannot be demoted in the website.</p></div>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Permission levels</CardTitle><CardDescription>Higher levels include the abilities of the levels below them.</CardDescription></CardHeader>
        <CardContent className="grid gap-2">
          {(["super_admin", "schedule_manager", "entry_user", "viewer"] as Role[]).map(role => <div key={role} className={`rounded-xl border p-3 ${data.user.role === role ? "border-blue-300 bg-blue-50" : "bg-white"}`}><div className="flex items-center justify-between gap-2"><strong className="text-sm">{roleLabels[role]}</strong>{data.user.role === role && <Badge>Current</Badge>}</div><p className="mt-1 text-xs text-muted-foreground">{roleDetails[role]}</p></div>)}
        </CardContent>
      </Card>
    </div>

    {canRequest && <Card className="mt-5">
      <CardHeader><CardTitle>Request access</CardTitle><CardDescription>Your request appears immediately in every Super Admin's approval queue.</CardDescription></CardHeader>
      <CardContent className="grid gap-4">
        {latest && <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-slate-50 p-3"><div><div className="flex items-center gap-2"><strong className="text-sm">Latest request: {latest.requested_role_label}</strong>{requestBadge(latest.status)}</div><p className="mt-1 text-xs text-muted-foreground">Submitted {timeLabel(latest.requested_at)}</p>{latest.review_note && <p className="mt-1 text-xs">Review note: {latest.review_note}</p>}</div></div>}
        <div className="grid gap-3 md:grid-cols-[.7fr_1.3fr_auto] md:items-end">
          <label className="field-label">Requested role<select className="h-10 w-full rounded-lg border border-input bg-background px-3 text-sm" value={requestedRole} onChange={event => setRequestedRole(event.target.value as Role)}>{data.requestable_roles.filter(role => role.id !== "viewer").map(role => <option key={role.id} value={role.id}>{role.label}</option>)}</select></label>
          <label className="field-label">Reason<Input value={reason} onChange={event => setReason(event.target.value)} placeholder="Briefly explain why you need this access" maxLength={500} /></label>
          <Button disabled={saving || latest?.status === "pending"} onClick={() => void mutate({ action: "request", requested_role: requestedRole, reason }, "Access request sent to Super Admins.")}>
            {saving ? <LoaderCircle className="size-4 animate-spin" /> : <UserCheck className="size-4" />}{latest?.status === "pending" ? "Awaiting review" : "Send request"}
          </Button>
        </div>
      </CardContent>
    </Card>}

    {data.permissions.can_manage_access && <>
      <Card className="mt-5">
        <CardHeader>
          <CardTitle>Cost Code source</CardTitle>
          <CardDescription>The separate read-only Lark source syncs automatically once per day. You can also sync it now.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 sm:flex-row sm:items-center">
          <div className="min-w-0 flex-1 rounded-xl border bg-slate-50 p-3 text-sm">
            <strong className="block">{costCodes?.configured ? `Connected Lark ${costCodes.source_type === "wiki" ? "Wiki Sheet" : costCodes.source_type === "sheet" ? "Sheet" : "Excel file"}` : "Not connected"}</strong>
            <span className="text-xs text-muted-foreground">
              {costCodes?.configured
                ? `${costCodes.database_rows.toLocaleString()} Cost Codes currently stored in the database.`
                : costCodes?.message || "Add LARK_COST_CODE_SOURCE_URL in Vercel."}
            </span>
          </div>
          <Button disabled={!costCodes?.configured || syncingCostCodes} onClick={() => void syncCostCodes()}>
            {syncingCostCodes ? <LoaderCircle className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
            {syncingCostCodes ? "Syncing…" : "Sync Cost Codes"}
          </Button>
        </CardContent>
      </Card>

      <Card className="mt-5">
        <CardHeader><div className="flex items-start justify-between gap-3"><div><CardTitle>Pending requests</CardTitle><CardDescription>Approve only the access needed for the person's work.</CardDescription></div><Badge variant={data.pending_requests.length ? "warning" : "success"}>{data.pending_requests.length} pending</Badge></div></CardHeader>
        <CardContent>
          {data.pending_requests.length ? <div className="grid gap-3">{data.pending_requests.map(request => <div key={request.id} className="flex flex-col gap-3 rounded-xl border p-4 lg:flex-row lg:items-center"><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><strong>{request.name || request.open_id}</strong><Badge>{roleLabels[request.current_role]} → {request.requested_role_label}</Badge></div><p className="mt-1 text-sm text-muted-foreground">{request.reason || "No reason supplied."}</p><p className="mt-1 text-xs text-muted-foreground">{timeLabel(request.requested_at)}</p></div><div className="flex gap-2"><Button variant="outline" disabled={saving} onClick={() => void mutate({ action: "review", request_id: request.id, decision: "rejected", review_note: "Access request rejected." }, "Access request rejected.")}><X className="size-4" />Reject</Button><Button disabled={saving} onClick={() => void mutate({ action: "review", request_id: request.id, decision: "approved", review_note: "Approved by Super Admin." }, `${request.name || "User"} approved as ${request.requested_role_label}.`)}><Check className="size-4" />Approve</Button></div></div>)}</div> : <div className="rounded-xl border border-dashed p-7 text-center text-sm text-muted-foreground">No access requests are waiting.</div>}
        </CardContent>
      </Card>

      <Card className="mt-5">
        <CardHeader><CardTitle>User access</CardTitle><CardDescription>Users appear here automatically after they open Settings for the first time.</CardDescription></CardHeader>
        <CardContent className="grid gap-2">{data.users.map(user => <UserRoleRow key={user.open_id} user={user} saving={saving} onSave={role => mutate({ action: "set_role", open_id: user.open_id, role }, `${user.name || "User"} is now ${roleLabels[role]}.`)} />)}</CardContent>
      </Card>
    </>}
  </div>
}

function UserRoleRow({ user, saving, onSave }: { user: AccessUser; saving: boolean; onSave: (role: Role) => Promise<void> }) {
  const [role, setRole] = useState<Role>(user.role)
  useEffect(() => setRole(user.role), [user.role])
  return <div className="flex flex-col gap-3 rounded-xl border p-3 sm:flex-row sm:items-center">
    <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-blue-50 text-primary"><ShieldCheck className="size-5" /></span>
    <div className="min-w-0 flex-1"><strong className="block truncate text-sm">{user.name || "Lark user"}</strong><p className="truncate text-xs text-muted-foreground">{user.open_id}</p></div>
    <select className="h-10 rounded-lg border border-input bg-background px-3 text-sm" value={role} disabled={user.env_super_admin} onChange={event => setRole(event.target.value as Role)}>{(["viewer", "entry_user", "schedule_manager", "super_admin"] as Role[]).map(item => <option key={item} value={item}>{roleLabels[item]}</option>)}</select>
    <Button size="sm" disabled={saving || user.env_super_admin || role === user.role} onClick={() => void onSave(role)}><Settings2 className="size-3.5" />Save</Button>
  </div>
}
