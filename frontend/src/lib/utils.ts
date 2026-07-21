import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function compactNumber(value: unknown, digits = 2) {
  const number = Number(value || 0)
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(number)
}

export function money(value: unknown) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(Number(value || 0))
}

export function localISO(day = new Date()) {
  const offset = day.getTimezoneOffset()
  return new Date(day.getTime() - offset * 60_000).toISOString().slice(0, 10)
}

export function displayDate(value?: string, year = false) {
  if (!value) return "—"
  return new Date(`${value}T12:00:00`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    ...(year ? { year: "numeric" } : {}),
  })
}

export function initials(name = "") {
  return name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase()
}
