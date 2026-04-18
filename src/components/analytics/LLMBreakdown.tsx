"use client"

import * as React from 'react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from 'recharts';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface LLMBreakdownData {
  has_data: boolean;
  total_calls: number;
  total_tokens_in: number;
  total_tokens_out: number;
  total_cost_usd: number;
  by_model: { model: string; calls: number; tokens_in: number; tokens_out: number; cost_usd: number }[];
  by_purpose: { purpose: string; calls: number; cost_usd: number; tokens_in: number; tokens_out: number }[];
  recent: { model: string; purpose: string; tokens_in: number; tokens_out: number; cost_usd: number; ts: number }[];
}

const CHART_STYLE = { background: 'transparent', fontSize: 10, fontFamily: 'JetBrains Mono, monospace' };

const PURPOSE_LABELS: Record<string, string> = {
  scanner_discovery: 'Discovery',
  scanner_verdict:   'Verdict',
  orchestrator_chat: 'Chat',
  orchestrator_signal: 'Signal',
  research_deep:     'Research',
  reflection:        'Reflection',
};

const MODEL_COLORS: Record<string, string> = {
  'gemini-2.5-flash':    'var(--kraken-purple)',
  'claude-haiku-4-5':    'var(--neon-green)',
  'claude-haiku-4-5-20251001': 'var(--neon-green)',
  'claude-sonnet-4-6':   'var(--neon-blue)',
  'claude-opus-4-7':     'var(--warning)',
};
function modelColor(m: string) {
  for (const [k, v] of Object.entries(MODEL_COLORS)) {
    if (m.includes(k) || k.includes(m)) return v;
  }
  return 'var(--muted-foreground)';
}

function fmtK(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)     return `${(n / 1_000).toFixed(1)}k`;
  return `${n}`;
}

function fmtModel(m: string) {
  if (m.includes('gemini')) return 'Gemini 2.5';
  if (m.includes('haiku'))  return 'Haiku';
  if (m.includes('sonnet')) return 'Sonnet';
  if (m.includes('opus'))   return 'Opus';
  return m.slice(0, 14);
}

type Tab = 'purpose' | 'models' | 'recent';

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function Empty({ height }: { height: number }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2" style={{ height }}>
      <span className="text-xs font-mono text-[var(--muted-foreground)] opacity-40 uppercase tracking-widest">
        No LLM calls recorded yet
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Purpose cost split — horizontal bar chart
// ---------------------------------------------------------------------------

function PurposeChart({ data, height }: { data: LLMBreakdownData['by_purpose']; height: number }) {
  if (!data.length) return <Empty height={height} />;

  const chartData = data.map(r => ({
    name: PURPOSE_LABELS[r.purpose] ?? r.purpose,
    cost: r.cost_usd,
    calls: r.calls,
    tok_in: r.tokens_in,
    tok_out: r.tokens_out,
  }));

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height={height} minWidth={0} minHeight={0}>
        <BarChart
          layout="vertical"
          data={chartData}
          margin={{ top: 2, right: 40, bottom: 2, left: 56 }}
          style={CHART_STYLE}
        >
          <XAxis
            type="number"
            dataKey="cost"
            tickFormatter={v => `$${Number(v).toFixed(4)}`}
            tick={{ fill: 'var(--muted-foreground)', fontSize: 10 }}
            stroke="var(--border)" tickLine={false} axisLine={false}
          />
          <YAxis
            type="category"
            dataKey="name"
            width={54}
            tick={{ fill: 'var(--muted-foreground)', fontSize: 10 }}
            stroke="var(--border)" tickLine={false} axisLine={false}
          />
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const d = payload[0].payload;
              return (
                <div className="bg-[var(--panel)] border border-[var(--border)] px-3 py-2 shadow-lg rounded-sm space-y-0.5">
                  <div className="text-xs font-semibold text-[var(--foreground)]">{d.name}</div>
                  <div className="text-xs font-mono tabular-nums text-[var(--muted-foreground)]">
                    ${Number(d.cost).toFixed(6)} · {d.calls} calls
                  </div>
                  <div className="text-xs font-mono tabular-nums text-[var(--muted-foreground)]">
                    {fmtK(d.tok_in)} in · {fmtK(d.tok_out)} out
                  </div>
                </div>
              );
            }}
          />
          <Bar
            dataKey="cost"
            isAnimationActive={false}
            radius={[0, 2, 2, 0]}
            fill="var(--kraken-purple)"
            opacity={0.8}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Model mix
// ---------------------------------------------------------------------------

function ModelGrid({ data, height }: { data: LLMBreakdownData['by_model']; height: number }) {
  if (!data.length) return <Empty height={height} />;

  const total = data.reduce((s, r) => s + r.cost_usd, 0);

  return (
    <div className="overflow-y-auto px-1" style={{ height }}>
      <div className="space-y-2 py-1">
        {data.map(r => {
          const pct = total > 0 ? (r.cost_usd / total) * 100 : 0;
          const color = modelColor(r.model);
          return (
            <div key={r.model} className="space-y-1">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span
                    className="inline-block w-2 h-2 rounded-sm shrink-0"
                    style={{ background: color }}
                  />
                  <span className="text-xs font-mono text-[var(--foreground)]">{fmtModel(r.model)}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs font-mono tabular-nums text-[var(--muted-foreground)]">
                    {r.calls} calls
                  </span>
                  <span className="text-xs font-mono tabular-nums text-[var(--muted-foreground)]">
                    {fmtK(r.tokens_in + r.tokens_out)} tok
                  </span>
                  <span className="text-xs font-mono tabular-nums font-semibold text-[var(--foreground)]">
                    ${r.cost_usd.toFixed(4)}
                  </span>
                </div>
              </div>
              {/* share bar */}
              <div className="h-1 bg-[var(--border)] rounded-sm overflow-hidden">
                <div
                  className="h-full rounded-sm transition-all"
                  style={{ width: `${pct.toFixed(1)}%`, background: color }}
                />
              </div>
              <div className="text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-50">
                {fmtK(r.tokens_in)} in · {fmtK(r.tokens_out)} out · {pct.toFixed(1)}% spend
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Recent calls table
// ---------------------------------------------------------------------------

function RecentCalls({ data, height }: { data: LLMBreakdownData['recent']; height: number }) {
  if (!data.length) return <Empty height={height} />;

  return (
    <div className="overflow-y-auto" style={{ height }}>
      <table className="w-full text-xs font-mono">
        <thead className="sticky top-0 bg-[var(--panel)]">
          <tr className="text-[var(--muted-foreground)] uppercase tracking-wider border-b border-[var(--border)]">
            <th className="text-left py-1 px-2 font-semibold">Model</th>
            <th className="text-left py-1 px-2 font-semibold">Purpose</th>
            <th className="text-right py-1 px-2 font-semibold tabular-nums">In</th>
            <th className="text-right py-1 px-2 font-semibold tabular-nums">Out</th>
            <th className="text-right py-1 px-2 font-semibold tabular-nums">Cost</th>
            <th className="text-right py-1 px-2 font-semibold">Time</th>
          </tr>
        </thead>
        <tbody>
          {data.map((r, i) => (
            <tr
              key={i}
              className="border-b border-[var(--border)]/40 hover:bg-[var(--panel-muted)] transition-colors"
            >
              <td className="py-1 px-2 text-[var(--foreground)]">{fmtModel(r.model)}</td>
              <td className="py-1 px-2 text-[var(--muted-foreground)]">
                {PURPOSE_LABELS[r.purpose] ?? r.purpose}
              </td>
              <td className="py-1 px-2 text-right tabular-nums text-[var(--muted-foreground)]">
                {fmtK(r.tokens_in)}
              </td>
              <td className="py-1 px-2 text-right tabular-nums text-[var(--muted-foreground)]">
                {fmtK(r.tokens_out)}
              </td>
              <td className="py-1 px-2 text-right tabular-nums text-[var(--foreground)]">
                ${r.cost_usd.toFixed(5)}
              </td>
              <td className="py-1 px-2 text-right text-[var(--muted-foreground)] opacity-60">
                {new Date(r.ts).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false })}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

interface LLMBreakdownProps {
  data: LLMBreakdownData;
  height?: number;
}

export function LLMBreakdown({ data, height = 256 }: LLMBreakdownProps) {
  const [tab, setTab] = React.useState<Tab>('purpose');

  if (!data.has_data) return <Empty height={height} />;

  const kpiH = 36;
  const tabH = 28;
  const bodyH = height - kpiH - tabH - 4;

  return (
    <div className="flex flex-col h-full" style={{ height }}>

      {/* KPI strip */}
      <div className="flex items-center gap-4 px-1 shrink-0" style={{ height: kpiH }}>
        <div className="flex flex-col">
          <span className="text-xs text-[var(--muted-foreground)] opacity-60 uppercase tracking-wider leading-none">Calls</span>
          <span className="text-sm font-mono tabular-nums font-bold text-[var(--foreground)]">{data.total_calls}</span>
        </div>
        <div className="w-px h-6 bg-[var(--border)]" />
        <div className="flex flex-col">
          <span className="text-xs text-[var(--muted-foreground)] opacity-60 uppercase tracking-wider leading-none">Tokens In</span>
          <span className="text-sm font-mono tabular-nums font-bold text-[var(--foreground)]">{fmtK(data.total_tokens_in)}</span>
        </div>
        <div className="w-px h-6 bg-[var(--border)]" />
        <div className="flex flex-col">
          <span className="text-xs text-[var(--muted-foreground)] opacity-60 uppercase tracking-wider leading-none">Tokens Out</span>
          <span className="text-sm font-mono tabular-nums font-bold text-[var(--foreground)]">{fmtK(data.total_tokens_out)}</span>
        </div>
        <div className="w-px h-6 bg-[var(--border)]" />
        <div className="flex flex-col">
          <span className="text-xs text-[var(--muted-foreground)] opacity-60 uppercase tracking-wider leading-none">Total Cost</span>
          <span className="text-sm font-mono tabular-nums font-bold text-[var(--neon-red)]">${data.total_cost_usd.toFixed(4)}</span>
        </div>
        <div className="w-px h-6 bg-[var(--border)]" />
        <div className="flex flex-col">
          <span className="text-xs text-[var(--muted-foreground)] opacity-60 uppercase tracking-wider leading-none">$/1k Tok</span>
          <span className="text-sm font-mono tabular-nums font-bold text-[var(--foreground)]">
            {data.total_tokens_in + data.total_tokens_out > 0
              ? `$${((data.total_cost_usd / (data.total_tokens_in + data.total_tokens_out)) * 1000).toFixed(5)}`
              : '—'}
          </span>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex items-center gap-0 border-b border-[var(--border)] shrink-0" style={{ height: tabH }}>
        {(['purpose', 'models', 'recent'] as Tab[]).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 h-full text-xs font-mono uppercase tracking-wider transition-colors border-b-2 ${
              tab === t
                ? 'border-[var(--kraken-purple)] text-[var(--kraken-light)]'
                : 'border-transparent text-[var(--muted-foreground)] hover:text-[var(--foreground)]'
            }`}
          >
            {t === 'purpose' ? 'By Purpose' : t === 'models' ? 'Models' : 'Recent Calls'}
          </button>
        ))}
      </div>

      {/* Tab body */}
      <div className="flex-1 min-h-0 pt-2">
        {tab === 'purpose' && <PurposeChart data={data.by_purpose} height={bodyH} />}
        {tab === 'models'  && <ModelGrid    data={data.by_model}   height={bodyH} />}
        {tab === 'recent'  && <RecentCalls  data={data.recent}     height={bodyH} />}
      </div>

    </div>
  );
}
