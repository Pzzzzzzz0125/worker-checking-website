import * as React from "react"
import { cn } from "@/lib/utils"

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type, ...props }, ref) => (
    <input
      type={type}
      ref={ref}
      className={cn("flex h-11 w-full rounded-lg border border-input bg-background px-3 text-sm shadow-sm outline-none transition placeholder:text-muted-foreground/70 focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10 disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-70", className)}
      {...props}
    />
  ),
)
Input.displayName = "Input"

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea ref={ref} className={cn("min-h-28 w-full rounded-lg border border-input bg-background px-3 py-2.5 text-sm shadow-sm outline-none transition placeholder:text-muted-foreground/70 focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10", className)} {...props} />
  ),
)
Textarea.displayName = "Textarea"

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("grid gap-1.5 text-sm font-semibold text-foreground", className)} {...props} />
}
