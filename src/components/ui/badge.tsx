import * as React from "react"
import { cn } from "@/lib/utils"

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "success" | "destructive" | "outline" | "purple";
}

function Badge({ className, variant = "default", ...props }: BadgeProps) {
  return (
    <div
      className={cn(
        "inline-flex items-center rounded-sm border px-2.5 py-0.5 text-xs font-semibold transition-colors tabular-nums uppercase tracking-wide",
        {
          "border-transparent bg-[var(--panel-muted)] text-[var(--foreground)]": variant === "default",
          "border-transparent bg-[var(--neon-green)]/15 text-[var(--neon-green)] shadow-[0_0_8px_rgba(0,200,5,0.2)]": variant === "success",
          "border-transparent bg-[var(--neon-red)]/15 text-[var(--neon-red)] shadow-[0_0_8px_rgba(255,59,48,0.2)]": variant === "destructive",
          "border-transparent bg-[var(--kraken-purple)]/20 text-[var(--kraken-light)] shadow-[0_0_8px_rgba(139,92,246,0.2)]": variant === "purple",
          "text-[var(--muted-foreground)] border-[var(--border)]": variant === "outline",
        },
        className
      )}
      {...props}
    />
  )
}

export { Badge }
