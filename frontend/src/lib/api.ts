export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
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
}

export function postJSON<T>(path: string, body: unknown) {
  return api<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
}
