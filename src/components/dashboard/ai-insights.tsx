"use client"

import { API_BASE } from '@/lib/api';
import * as React from 'react';
import ReactMarkdown from 'react-markdown';
import { Card, CardHeader, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Newspaper, BrainCircuit, RefreshCw, ExternalLink, Clock, Zap } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import type { ActionItem, ActionItemsResponse } from '@/lib/types';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface NewsItem {
  id:        string | number;
  headline:  string;
  summary:   string;
  source:    string;
  url:       string;
  symbols:   string[];
  sentiment: 'positive' | 'negative' | 'neutral' | null;
  published: string | null;
}

interface Commentary {
  text:         string | null;
  generated_at: number;
  cached:       boolean;
}

// Strips only JSON command blocks (e.g. ```json\n{...}```), not regular code blocks
function stripCommandBlocks(text: string): string {
  return text.replace(/```json\n\{[\s\S]*?\}[\s\S]*?```/g, '').trim();
}

// ---------------------------------------------------------------------------
// Markdown components for AI commentary
// ---------------------------------------------------------------------------

const MD_COMPONENTS = {
  h1: ({ children }: { children?: React.ReactNode }) => (
    <h1 className="text-xs font-semibold uppercase tracking-widest text-[var(--kraken-purple)] border-b border-[var(--border)] pb-1 mb-2 mt-4 first:mt-0">
      {children}
    </h1>
  ),
  h2: ({ children }: { children?: React.ReactNode }) => (
    <h2 className="text-xs font-semibold uppercase tracking-widest text-[var(--kraken-purple)] border-b border-[var(--border)] pb-1 mb-2 mt-4 first:mt-0">
      {children}
    </h2>
  ),
  h3: ({ children }: { children?: React.ReactNode }) => (
    <h3 className="text-xs font-semibold text-[var(--kraken-light)] mb-1.5 mt-3 first:mt-0">
      {children}
    </h3>
  ),
  p: ({ children }: { children?: React.ReactNode }) => (
    <p className="text-xs text-[var(--muted-foreground)] leading-relaxed mb-2">
      {children}
    </p>
  ),
  strong: ({ children }: { children?: React.ReactNode }) => (
    <strong className="font-semibold text-[var(--foreground)]">{children}</strong>
  ),
  ul: ({ children }: { children?: React.ReactNode }) => (
    <ul className="text-xs text-[var(--muted-foreground)] leading-relaxed mb-2 ml-3 list-disc space-y-0.5">
      {children}
    </ul>
  ),
  li: ({ children }: { children?: React.ReactNode }) => (
    <li>{children}</li>
  ),
};

// ---------------------------------------------------------------------------
// Inline ticker highlight: bold-purple any uppercase 2-5 letter word
// ---------------------------------------------------------------------------

function HighlightedHeadline({ text }: { text: string }) {
  const parts = text.split(/\b([A-Z]{2,5})\b/);
  return (
    <>
      {parts.map((part, i) =>
        /^[A-Z]{2,5}$/.test(part) ? (
          <span key={i} className="font-semibold text-[var(--kraken-light)]">{part}</span>
        ) : (
          <React.Fragment key={i}>{part}</React.Fragment>
        )
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Sentiment dot
// ---------------------------------------------------------------------------

function SentimentDot({ sentiment }: { sentiment: 'positive' | 'negative' | 'neutral' | null }) {
  const color =
    sentiment === 'positive' ? 'var(--neon-green)' :
    sentiment === 'negative' ? 'var(--neon-red)' :
    'var(--muted-foreground)';
  return (
    <span
      className="inline-block w-1.5 h-1.5 rounded-sm shrink-0 mt-0.5"
      style={{ background: color, opacity: sentiment == null ? 0.3 : 1 }}
    />
  );
}

// ---------------------------------------------------------------------------
// NewsRow
// ---------------------------------------------------------------------------

function NewsRow({ item }: { item: NewsItem }) {
  const age = item.published
    ? (() => {
        const ms = Date.now() - new Date(item.published).getTime();
        const m  = Math.floor(ms / 60000);
        if (m < 60) return `${m}m`;
        const h = Math.floor(m / 60);
        if (h < 24) return `${h}h`;
        return `${Math.floor(h / 24)}d`;
      })()
    : null;

  return (
    <div className="py-2 border-b border-[var(--border)]/30 last:border-b-0 group">
      <div className="flex items-start gap-2">
        <SentimentDot sentiment={item.sentiment ?? null} />
        <div className="flex-1 min-w-0">
          <p className="text-xs text-[var(--foreground)] leading-snug line-clamp-2 group-hover:line-clamp-none transition-all mb-0.5">
            <HighlightedHeadline text={item.headline} />
          </p>
          <div className="flex items-center gap-1.5">
            {item.source && (
              <span className="text-xs text-[var(--muted-foreground)] opacity-50">{item.source}</span>
            )}
            {item.source && age && <span className="text-[var(--muted-foreground)] opacity-30">·</span>}
            {age && (
              <span className="text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-40">{age}</span>
            )}
          </div>
        </div>
        {item.url && (
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            className="shrink-0 p-0.5 text-[var(--muted-foreground)] opacity-0 group-hover:opacity-60 hover:opacity-100 transition-opacity"
            onClick={e => e.stopPropagation()}
          >
            <ExternalLink className="w-3 h-3" />
          </a>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ActionItemCard
// ---------------------------------------------------------------------------

const URGENCY_COLOR: Record<string, string> = {
  HIGH:   'var(--neon-red)',
  MEDIUM: 'var(--warning)',
  LOW:    'var(--neon-green)',
};

const TYPE_LABEL: Record<string, string> = {
  LIQUIDATE: 'LIQUIDATE',
  REACTIVATE: 'REACTIVATE',
  HALT:       'HALT',
  MONITOR:    'MONITOR',
  ADJUST:     'ADJUST',
};

function ActionItemCard({ item }: { item: ActionItem }) {
  const urgencyColor = URGENCY_COLOR[item.urgency] ?? 'var(--muted-foreground)';
  return (
    <div className="py-2.5 border-b border-[var(--border)]/30 last:border-b-0">
      <div className="flex items-start gap-2">
        <span
          className="inline-block w-1.5 h-1.5 rounded-sm shrink-0 mt-1"
          style={{ background: urgencyColor }}
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
            <span className="text-xs font-mono tabular-nums font-semibold text-[var(--muted-foreground)] opacity-70 tracking-wider">
              {TYPE_LABEL[item.type] ?? item.type}
            </span>
            {(item.symbol || item.strategy) && (
              <span className="text-xs font-mono tabular-nums text-[var(--kraken-light)] opacity-80">
                {item.symbol ?? item.strategy}
              </span>
            )}
            <span
              className="text-xs font-mono tabular-nums ml-auto"
              style={{ color: urgencyColor, opacity: 0.7 }}
              title="HIGH = immediate action required; MEDIUM = monitor closely; LOW = informational."
            >
              {item.urgency}
            </span>
          </div>
          <p className="text-xs text-[var(--foreground)] font-medium leading-snug mb-0.5">
            {item.title}
          </p>
          <p className="text-xs text-[var(--muted-foreground)] opacity-70 leading-relaxed">
            {item.reason}
          </p>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AiInsights — News Feed + AI Commentary + Portfolio Action Items
// ---------------------------------------------------------------------------

export function AiInsights() {
  const [news, setNews]               = React.useState<NewsItem[]>([]);
  const [commentary, setCommentary]   = React.useState<Commentary | null>(null);
  const [actionItems, setActionItems] = React.useState<ActionItem[]>([]);
  const [actionsTs, setActionsTs]     = React.useState<number>(0);
  const [actionsCached, setActionsCached] = React.useState(false);

  const [newsLoading, setNewsLoading]   = React.useState(false);
  const [commLoading, setCommLoading]   = React.useState(false);
  const [actionsLoading, setActionsLoading] = React.useState(false);

  const [lastNewsRefresh, setLastNewsRefresh] = React.useState<Date | null>(null);
  const [mounted, setMounted]         = React.useState(false);
  const [activeSection, setActiveSection] = React.useState<'news' | 'commentary' | 'actions'>('news');

  React.useEffect(() => { setMounted(true); }, []);

  const fetchNews = React.useCallback(async () => {
    setNewsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/market/news`, {
        signal: AbortSignal.timeout(10000),
      });
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) {
          setNews(data);
          setLastNewsRefresh(new Date());
        }
      }
    } catch { /* silent */ }
    finally { setNewsLoading(false); }
  }, []);

  const fetchCommentary = React.useCallback(async (force = false) => {
    setCommLoading(true);
    try {
      const res = await fetch(
        `${API_BASE}/api/market/commentary${force ? '?force=true' : ''}`,
        { signal: AbortSignal.timeout(30000) },
      );
      if (res.ok) {
        const data = await res.json();
        if (data.text) setCommentary(data);
      }
    } catch { /* silent */ }
    finally { setCommLoading(false); }
  }, []);

  const fetchActionItems = React.useCallback(async (force = false) => {
    setActionsLoading(true);
    try {
      const res = await fetch(
        `${API_BASE}/api/market/action-items${force ? '?force=true' : ''}`,
        { signal: AbortSignal.timeout(30000) },
      );
      if (res.ok) {
        const data: ActionItemsResponse = await res.json();
        if (Array.isArray(data.items)) {
          setActionItems(data.items);
          setActionsTs(data.generated_at ?? 0);
          setActionsCached(data.cached ?? false);
        }
      }
    } catch { /* silent */ }
    finally { setActionsLoading(false); }
  }, []);

  // News: initial load + 5-min refresh
  React.useEffect(() => {
    fetchNews();
    const interval = setInterval(fetchNews, 300_000);
    return () => clearInterval(interval);
  }, [fetchNews]);

  // Commentary: initial load + 30-min refresh
  React.useEffect(() => {
    fetchCommentary();
    const interval = setInterval(() => fetchCommentary(), 1_800_000);
    return () => clearInterval(interval);
  }, [fetchCommentary]);

  // Action items: initial load + 10-min refresh
  React.useEffect(() => {
    fetchActionItems();
    const interval = setInterval(() => fetchActionItems(), 600_000);
    return () => clearInterval(interval);
  }, [fetchActionItems]);

  const handleRefresh = () => {
    if (activeSection === 'news') fetchNews();
    else if (activeSection === 'commentary') fetchCommentary(true);
    else fetchActionItems(true);
  };

  const isLoading =
    activeSection === 'news' ? newsLoading :
    activeSection === 'commentary' ? commLoading :
    actionsLoading;

  if (!mounted) return null;

  const ageMinutes = commentary
    ? Math.floor((Date.now() / 1000 - commentary.generated_at) / 60)
    : null;

  const actionsAgeMinutes = actionsTs > 0
    ? Math.floor((Date.now() / 1000 - actionsTs) / 60)
    : null;

  return (
    <Card className="flex flex-col h-full">
      <CardHeader className="py-2.5 px-3 border-b border-[var(--border)] flex flex-row justify-between items-center">
        <div className="flex items-center gap-1">
          <button
            onClick={() => setActiveSection('news')}
            className={`flex items-center gap-1.5 px-2 py-1 rounded-sm text-xs font-semibold uppercase tracking-wider transition-colors ${
              activeSection === 'news'
                ? 'bg-[var(--kraken-purple)]/15 text-[var(--kraken-light)]'
                : 'text-[var(--muted-foreground)] hover:text-[var(--foreground)]'
            }`}
          >
            <Newspaper className="w-3 h-3" /> News
          </button>
          <button
            onClick={() => setActiveSection('commentary')}
            className={`flex items-center gap-1.5 px-2 py-1 rounded-sm text-xs font-semibold uppercase tracking-wider transition-colors ${
              activeSection === 'commentary'
                ? 'bg-[var(--kraken-purple)]/15 text-[var(--kraken-light)]'
                : 'text-[var(--muted-foreground)] hover:text-[var(--foreground)]'
            }`}
          >
            <BrainCircuit className="w-3 h-3" /> AI
          </button>
          <button
            onClick={() => setActiveSection('actions')}
            className={`flex items-center gap-1.5 px-2 py-1 rounded-sm text-xs font-semibold uppercase tracking-wider transition-colors ${
              activeSection === 'actions'
                ? 'bg-[var(--kraken-purple)]/15 text-[var(--kraken-light)]'
                : 'text-[var(--muted-foreground)] hover:text-[var(--foreground)]'
            }`}
          >
            <Zap className="w-3 h-3" /> Actions
            {actionItems.length > 0 && (
              <span
                className="inline-flex items-center justify-center w-4 h-4 rounded-sm text-xs font-mono tabular-nums font-bold"
                style={{ background: 'var(--kraken-purple)', color: 'var(--background)' }}
              >
                {actionItems.length}
              </span>
            )}
          </button>
        </div>

        <div className="flex items-center gap-2">
          {activeSection === 'news' && lastNewsRefresh && (
            <span className="text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-40 flex items-center gap-1">
              <Clock className="w-2.5 h-2.5" />
              {lastNewsRefresh.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false })}
            </span>
          )}
          {activeSection === 'commentary' && ageMinutes != null && (
            <span className="text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-40">
              {ageMinutes}m ago
            </span>
          )}
          {activeSection === 'actions' && actionsAgeMinutes != null && (
            <span className="text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-40">
              {actionsAgeMinutes}m ago{actionsCached ? ' · cached' : ''}
            </span>
          )}
          <button
            onClick={handleRefresh}
            disabled={isLoading}
            className="p-1 text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors disabled:opacity-30"
          >
            <RefreshCw className={`w-3 h-3 ${isLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </CardHeader>

      <CardContent className="flex-1 overflow-y-auto p-3">
        {activeSection === 'news' && (
          <>
            {newsLoading && news.length === 0 ? (
              <div className="flex items-center justify-center h-16 text-xs text-[var(--muted-foreground)] opacity-40 uppercase tracking-widest">
                Fetching news...
              </div>
            ) : news.length === 0 ? (
              <EmptyState icon={<Newspaper />} message="No news — check API key config" />
            ) : (
              news.map(item => <NewsRow key={item.id} item={item} />)
            )}
          </>
        )}

        {activeSection === 'commentary' && (
          <div>
            {commLoading && !commentary?.text ? (
              <div className="flex items-center justify-center h-24 text-xs text-[var(--muted-foreground)] opacity-40 uppercase tracking-widest">
                Generating analysis...
              </div>
            ) : commentary?.text ? (
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <Badge variant="purple" className="text-xs">AI Analyst</Badge>
                  {commentary.generated_at > 0 && (
                    <span className="text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-40">
                      {new Date(commentary.generated_at * 1000).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false })}
                    </span>
                  )}
                  {commentary.cached && (
                    <span className="text-xs text-[var(--muted-foreground)] opacity-40">cached</span>
                  )}
                </div>
                <ReactMarkdown components={MD_COMPONENTS}>
                  {stripCommandBlocks(commentary.text)}
                </ReactMarkdown>
              </div>
            ) : (
              <EmptyState icon={<BrainCircuit />} message="Click refresh to generate AI market commentary" />
            )}
          </div>
        )}

        {activeSection === 'actions' && (
          <div>
            {actionsLoading && actionItems.length === 0 ? (
              <div className="flex items-center justify-center h-24 text-xs text-[var(--muted-foreground)] opacity-40 uppercase tracking-widest">
                Analyzing portfolio...
              </div>
            ) : actionItems.length === 0 ? (
              <EmptyState icon={<Zap />} message="No action items — AI analyst is watching the portfolio." />
            ) : (
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <Badge variant="purple" className="text-xs">AI Analyst</Badge>
                  {actionsTs > 0 && (
                    <span className="text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-40">
                      {new Date(actionsTs * 1000).toLocaleString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false })}
                    </span>
                  )}
                  <span className="text-xs text-[var(--muted-foreground)] opacity-40 ml-auto">
                    → fed to Director
                  </span>
                </div>
                {actionItems.map((item, i) => (
                  <ActionItemCard key={i} item={item} />
                ))}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
