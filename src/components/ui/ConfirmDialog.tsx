"use client"

import * as React from 'react';
import { AlertTriangle } from 'lucide-react';

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
  loading?: boolean;
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "CONFIRM",
  onConfirm,
  onCancel,
  loading = false,
}: ConfirmDialogProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Overlay */}
      <div
        className="absolute inset-0 bg-black/70"
        onClick={!loading ? onCancel : undefined}
      />

      {/* Dialog panel */}
      <div className="relative z-10 w-full max-w-sm mx-4 bg-[var(--panel)] border border-[var(--border)] rounded-sm shadow-2xl">
        {/* Header */}
        <div className="flex items-center gap-3 px-5 pt-5 pb-3 border-b border-[var(--border)]">
          <div className="w-7 h-7 rounded-sm bg-red-600/20 border border-red-600/40 flex items-center justify-center shrink-0">
            <AlertTriangle className="w-4 h-4 text-red-400" strokeWidth={2} />
          </div>
          <span className="text-sm font-bold tracking-widest uppercase text-[var(--foreground)]">
            {title}
          </span>
        </div>

        {/* Body */}
        <div className="px-5 py-4">
          <p className="text-sm text-[var(--muted-foreground)] leading-relaxed">
            {message}
          </p>
        </div>

        {/* Actions */}
        <div className="flex items-center justify-end gap-2 px-5 pb-5">
          <button
            onClick={onCancel}
            disabled={loading}
            className="px-4 py-2 text-xs font-bold tracking-widest uppercase border border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:border-[var(--foreground)] rounded-sm transition-colors disabled:opacity-40"
          >
            CANCEL
          </button>
          <button
            onClick={onConfirm}
            disabled={loading}
            className="px-4 py-2 text-xs font-bold tracking-widest uppercase bg-red-600 hover:bg-red-700 text-white rounded-sm transition-colors disabled:opacity-60 flex items-center gap-2"
          >
            {loading && (
              <span className="w-3 h-3 border border-white/40 border-t-white rounded-sm animate-spin" />
            )}
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
