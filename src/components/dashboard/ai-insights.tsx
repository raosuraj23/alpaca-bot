"use client"

import * as React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Newspaper, BrainCircuit, RefreshCw, ExternalLink, Clock } from "lucide-react";

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
  published: string | null;
}

interface Commentary {
  text:         string | null;
  generated_at: number;
  cached:       boolean;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function CommentaryPanel({ commentary, loading, onRefresh }: {
  commentary: Commentary | null;
  loading: boolean;
  onRefresh: () => void;
}) {
  const ageMinutes = commentary
    ? Math.floor((Date.now() / 1000 - commentary.generated_at) / 60)
    : null;

  return (
    <div className="border-b border-[var(--border)] shrink-0">
      <div className="px-3 py-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BrainCircuit className="w-3 h-3 text-[var(--kraken-light)]" />
          <span className="text-xs uppercase tracking-wider font-semibold text-[var(--muted-foreground)]">
            Haiku Commentary
          </span>
          {commentary && (
            <span className="text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-40">
              {ageMinutes != null ? `${ageMinutes}m ago` : ''}
            </span>
          )}
        </div>
        <button
          onClick={onRefresh}
          disabled={loading}
          className="p-1 text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors disabled:opacity-30"
        >
          <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>
      <div className="px-3 pb-3 max-h-36 overflow-y-auto">
        {loading && !commentary?.text ? (
          <div className="text-xs text-[var(--muted-foreground)] opacity-40 italic">
            Generating commentary...
          </div>
        ) : commentary?.text ? (
          <p className="text-xs text-[var(--muted-foreground)] leading-relaxed whitespace-pre-wrap">
            {commentary.text}
          </p>
        ) : (
          <div className="text-xs text-[var(--muted-foreground)] opacity-40 italic">
            Commentary loads every 30 minutes. Click refresh to generate now.
          </div>
        )}
      </div>
    </div>
  );
}

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
    <div className="py-2 border-b border-[var(--border)]/40 last:border-b-0 group">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
            {item.symbols.slice(0, 3).map(s => (
              <span key={s} className="text-xs font-mono font-bold text-[var(--kraken-light)]">{s}</span>
            ))}
            {item.source && (
              <span className="text-xs text-[var(--muted-foreground)] opacity-50">{item.source}</span>
            )}
            {age && (
              <span className="text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-40 ml-auto">{age}</span>
            )}
          </div>
          <p className="text-xs text-[var(--foreground)] leading-snug line-clamp-2 group-hover:line-clamp-none transition-all">
            {item.headline}
          </p>
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
// AiInsights — News Feed + Haiku Commentary
// Export name kept as AiInsights so trading-desk.tsx import is unchanged.
// ---------------------------------------------------------------------------

export function AiInsights() {
  const [news, setNews]               = React.useState<NewsItem[]>([]);
  const [commentary, setCommentary]   = React.useState<Commentary | null>(null);
  const [newsLoading, setNewsLoading] = React.useState(false);
  const [commLoading, setCommLoading] = React.useState(false);
  const [lastNewsRefresh, setLastNewsRefresh] = React.useState<Date | null>(null);
  const [mounted, setMounted]         = React.useState(false);
  const [activeSection, setActiveSection] = React.useState<'news' | 'commentary'>('news');

  React.useEffect(() => { setMounted(true); }, []);

  const fetchNews = React.useCallback(async () => {
    setNewsLoading(true);
    try {
      const res = await fetch('http://localhost:8000/api/market/news', {
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
        `http://localhost:8000/api/market/commentary${force ? '?force=true' : ''}`,
        { signal: AbortSignal.timeout(30000) },
      );
      if (res.ok) {
        const data = await res.json();
        if (data.text) setCommentary(data);
      }
    } catch { /* silent */ }
    finally { setCommLoading(false); }
  }, []);

  // News: initial load + 5-min refresh
  React.useEffect(() => {
    fetchNews();
    const interval = setInterval(fetchNews, 300_000); // 5 min
    return () => clearInterval(interval);
  }, [fetchNews]);

  // Commentary: initial load + 30-min refresh
  React.useEffect(() => {
    fetchCommentary();
    const interval = setInterval(() => fetchCommentary(), 1_800_000); // 30 min
    return () => clearInterval(interval);
  }, [fetchCommentary]);

  if (!mounted) return null;

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
            <BrainCircuit className="w-3 h-3" /> Haiku
          </button>
        </div>

        <div className="flex items-center gap-2">
          {activeSection === 'news' && lastNewsRefresh && (
            <span className="text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-40 flex items-center gap-1">
              <Clock className="w-2.5 h-2.5" />
              {lastNewsRefresh.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
          <button
            onClick={() => activeSection === 'news' ? fetchNews() : fetchCommentary(true)}
            disabled={activeSection === 'news' ? newsLoading : commLoading}
            className="p-1 text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors disabled:opacity-30"
          >
            <RefreshCw className={`w-3 h-3 ${(activeSection === 'news' ? newsLoading : commLoading) ? 'animate-spin' : ''}`} />
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
              <div className="flex flex-col items-center justify-center h-16 text-center">
                <Newspaper className="w-5 h-5 text-[var(--muted-foreground)] opacity-20 mb-2" />
                <span className="text-xs text-[var(--muted-foreground)] opacity-40 uppercase tracking-widest">
                  No news — check API key config
                </span>
              </div>
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
                  <Badge variant="purple" className="text-xs">Claude Haiku</Badge>
                  {commentary.generated_at > 0 && (
                    <span className="text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-40">
                      {new Date(commentary.generated_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  )}
                  {commentary.cached && (
                    <span className="text-xs text-[var(--muted-foreground)] opacity-40">cached</span>
                  )}
                </div>
                <p className="text-xs text-[var(--foreground)] leading-relaxed whitespace-pre-wrap">
                  {commentary.text}
                </p>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center h-24 text-center gap-2">
                <BrainCircuit className="w-5 h-5 text-[var(--muted-foreground)] opacity-20" />
                <span className="text-xs text-[var(--muted-foreground)] opacity-40">
                  Click refresh to generate Haiku market commentary
                </span>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
