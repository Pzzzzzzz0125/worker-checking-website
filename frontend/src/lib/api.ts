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
function notifyRequestState() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("speed-api-loading", { detail: activeRequests }))
  }
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
