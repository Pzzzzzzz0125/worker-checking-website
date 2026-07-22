import * as React from "react"
import { cn } from "@/lib/utils"

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-[10px] border border-border bg-card text-card-foreground shadow-[0_1px_2px_rgba(15,23,42,.03)]", className)} {...props} />
}
export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col gap-1.5 p-5 pb-3 sm:p-6 sm:pb-3", className)} {...props} />
}
export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn("text-base font-bold tracking-tight sm:text-lg", className)} {...props} />
}
export function CardDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-sm leading-5 text-muted-foreground", className)} {...props} />
}
export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-5 pt-2 sm:p-6 sm:pt-2", className)} {...props} />
}
