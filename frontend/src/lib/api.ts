export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

// Every request announces its lifecycle so the interface can show a consistent
// progress indicator, including requests initiated from tables and checkboxes.
let activeRequests = 0
let mutationVersion = 0
let syncTimer: number | undefined
let syncInFlight = false

export type LarkSyncStatus = {
  enabled: boolean
  pending: number
  retrying: number
  synced_last_24h: number
  last_synced_at: string
  processed?: number
  phase?: "syncing" | "synced" | "pending" | "error" | "disabled"
}

export function getApiMutationVersion() {
  return mutationVersion
}

function notifyRequestState() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("speed-api-loading", { detail: activeRequests }))
  }
}

function notifySyncState(status: LarkSyncStatus) {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("speed-lark-sync", { detail: status }))
  }
}

async function runLarkSync() {
  if (syncInFlight) return
  syncInFlight = true
  notifySyncState({
    enabled: true,
    pending: 0,
    retrying: 0,
    synced_last_24h: 0,
    last_synced_at: "",
    phase: "syncing",
  })
  try {
    const response = await fetch("/api/sync/lark", {
      method: "POST",
      credentials: "same-origin",
      keepalive: true,
      headers: { "Content-Type": "application/json" },
      body: "{}",
    })
    const result = await response.json() as LarkSyncStatus & { error?: string }
    if (!response.ok) throw new Error(result.error || `Lark sync failed (${response.status})`)
    const phase = !result.enabled
      ? "disabled"
      : result.pending > 0
        ? "pending"
        : "synced"
    notifySyncState({ ...result, phase })
    if (result.enabled && result.pending > 0) {
      triggerLarkSync(result.retrying > 0 ? 35_000 : 1_000)
    }
  } catch {
    notifySyncState({
      enabled: true,
      pending: 1,
      retrying: 1,
      synced_last_24h: 0,
      last_synced_at: "",
      phase: "error",
    })
    triggerLarkSync(60_000)
  } finally {
    syncInFlight = false
  }
}

export function triggerLarkSync(delay = 300) {
  if (typeof window === "undefined") return
  if (syncTimer !== undefined) window.clearTimeout(syncTimer)
  syncTimer = window.setTimeout(() => {
    syncTimer = undefined
    void runLarkSync()
  }, delay)
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  activeRequests += 1
  notifyRequestState()
  try {
    const response = await fetch(path, options)
    const contentType = response.headers.get("content-type") || ""
    const body = contentType.includes("application/json")
      ? await response.json()
      : await response.text()
    if (!response.ok) {
      const message = typeof body === "object" && body && "error" in body
        ? String(body.error)
        : `Request failed (${response.status})`
      throw new ApiError(message, response.status)
    }
    const method = String(options.method || "GET").toUpperCase()
    if (method !== "GET" && method !== "HEAD") {
      mutationVersion += 1
      if (
        path !== "/api/sync/lark"
        && response.headers.get("X-Data-Backend")?.toLowerCase() === "postgres"
      ) {
        triggerLarkSync()
      }
    }
    return body as T
  } finally {
    activeRequests = Math.max(0, activeRequests - 1)
    notifyRequestState()
  }
}

export function postJSON<T>(path: string, body: unknown) {
  return api<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
}

export async function downloadJSON(path: string, body: unknown) {
  activeRequests += 1
  notifyRequestState()
  try {
    const response = await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
    if (!response.ok) {
      const contentType = response.headers.get("content-type") || ""
      const errorBody = contentType.includes("application/json")
        ? await response.json()
        : await response.text()
      const message = typeof errorBody === "object" && errorBody && "error" in errorBody
        ? String(errorBody.error)
        : `Request failed (${response.status})`
      throw new ApiError(message, response.status)
    }
    const disposition = response.headers.get("content-disposition") || ""
    const filename = disposition.match(/filename="([^"]+)"/i)?.[1] || "export.xlsx"
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement("a")
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1_000)
    return filename
  } finally {
    activeRequests = Math.max(0, activeRequests - 1)
    notifyRequestState()
  }
}
