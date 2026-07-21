import type { LucideIcon } from "lucide-react"

export function EmptyState({ icon: Icon, title, description }: { icon: LucideIcon; title: string; description: string }) {
  return <div className="grid min-h-48 place-items-center px-6 py-10 text-center"><div><span className="mx-auto mb-3 grid size-11 place-items-center rounded-2xl bg-muted text-muted-foreground"><Icon className="size-5" /></span><h3 className="font-bold">{title}</h3><p className="mx-auto mt-1 max-w-md text-sm leading-6 text-muted-foreground">{description}</p></div></div>
}
