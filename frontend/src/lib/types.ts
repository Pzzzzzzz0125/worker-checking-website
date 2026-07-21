export type CostCenter = { id: string; name: string }
export type Worker = { id: number; name: string; active?: number }
export type WorkLocation = {
  id?: number
  name: string
  hours: number | null
  cost_centers: CostCenter[]
}
export type WorkRecord = {
  id?: number
  worker_id: number
  worker_name?: string
  work_date: string
  status: "worked" | "off" | "unknown" | ""
  total_hours: number
  overtime_hours?: number
  extra_pay: number
  start_time: string
  end_time: string
  notes: string
  original_text?: string
  locations: WorkLocation[]
  cost_centers: CostCenter[]
  source?: string
  confidence?: string
  dirty?: boolean
  existing?: boolean
}

export type Bootstrap = {
  workers: Worker[]
  cost_centers: CostCenter[]
  locations: string[]
  ai_configured: boolean
  review_count: number
  last_recorded_date: string
  workbook_year: number
}

export type Summary = {
  range: { from: string; to: string }
  totals: {
    hours: number
    active_workers: number
    worked_days: number
    off_days: number
    extra_pay: number
  }
  records: (WorkRecord & { locations: WorkLocation[] | string })[]
  daily: { date: string; hours: number }[]
}
