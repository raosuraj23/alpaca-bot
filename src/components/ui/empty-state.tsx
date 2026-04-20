"use client"

import * as React from 'react';

interface EmptyStateProps {
  icon?: React.ReactNode;
  message: string;
  subtext?: string;
}

export function EmptyState({ icon, message, subtext }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center h-full min-h-[60px] gap-2 py-6 text-center">
      {icon && (
        <div className="w-6 h-6 text-[var(--muted-foreground)] opacity-40 flex items-center justify-center">
          {icon}
        </div>
      )}
      <span className="text-xs text-[var(--muted-foreground)] uppercase tracking-widest opacity-60">
        {message}
      </span>
      {subtext && (
        <span className="text-xs text-[var(--muted-foreground)] opacity-40">
          {subtext}
        </span>
      )}
    </div>
  );
}
