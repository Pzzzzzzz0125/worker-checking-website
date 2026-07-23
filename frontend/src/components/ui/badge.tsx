import * as React from "react"
import { cn } from "@/lib/utils"

export function Badge({ className, variant = "secondary", ...props }: React.HTMLAttributes<HTMLSpanElement> & { variant?: "secondary" | "success" | "warning" | "destructive" }) {
  return <span className={cn("inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold capitalize", variant === "success" ? "bg-emerald-100 text-emerald-800" : variant === "warning" ? "bg-orange-100 text-orange-800" : variant === "destructive" ? "bg-red-100 text-red-800" : "bg-slate-100 text-slate-700", className)} {...props} />
}
