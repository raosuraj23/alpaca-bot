import * as React from "react"
import { cn } from "@/lib/utils"

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "outline" | "ghost" | "success" | "destructive";
  size?: "default" | "sm" | "lg" | "icon";
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(
          "inline-flex items-center justify-center whitespace-nowrap rounded-sm text-sm font-medium transition-all focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--kraken-purple)] disabled:pointer-events-none disabled:opacity-50",
          {
            "bg-[var(--kraken-purple)] text-white hover:bg-[var(--kraken-light)] shadow-[0_0_15px_rgba(139,92,246,0.3)]": variant === "default",
            "border border-[var(--kraken-purple)]/50 bg-transparent text-[var(--kraken-light)] hover:bg-[var(--kraken-purple)]/10": variant === "outline",
            "hover:bg-[var(--panel-muted)] hover:text-white": variant === "ghost",
            "bg-[var(--neon-green)] text-black hover:bg-[var(--neon-green)]/90": variant === "success",
            "bg-[var(--neon-red)] text-white hover:bg-[var(--neon-red)]/90": variant === "destructive",
            "h-9 px-4 py-2": size === "default",
            "h-8 px-3 text-xs": size === "sm",
            "h-10 px-8": size === "lg",
            "h-9 w-9": size === "icon",
          },
          className
        )}
        {...props}
      />
    )
  }
)
Button.displayName = "Button"

export { Button }
