import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Resolves a CSS custom property value from :root at call time.
 * Required for Recharts which passes colors as SVG attributes (not CSS),
 * so variables must be pre-resolved to their computed string values.
 */
export function cssVar(name: string): string {
  if (typeof window === 'undefined') return '';
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/**
 * Parse a UTC timestamp string or epoch number into a Date.
 * SQLite / FastAPI often emit strings like "2026-04-18 05:15:19" with no
 * timezone suffix.  Without a 'Z' the JS engine treats them as local time,
 * so conversion to user-local display is skipped.  This helper appends 'Z'
 * when no timezone marker is present, forcing UTC interpretation.
 */
export function parseUtc(ts: string | number | null | undefined): Date | null {
  if (ts == null || ts === '') return null;
  if (typeof ts === 'number') return new Date(ts);
  const normalised = /Z$|[+-]\d{2}:\d{2}$/.test(ts) ? ts : ts.replace(' ', 'T') + 'Z';
  const d = new Date(normalised);
  return isNaN(d.getTime()) ? null : d;
}
