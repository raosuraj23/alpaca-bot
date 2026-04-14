"use client"

import * as React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useTradingStore } from '@/hooks/useTradingStream';

type OrderType = 'market' | 'limit' | 'stop';
type OrderStatus = 'idle' | 'pending' | 'success' | 'error';

export function TradePanel() {
  const { activeSymbol } = useTradingStore();
  const [size, setSize] = React.useState('1.0');
  const [orderType, setOrderType] = React.useState<OrderType>('market');
  const [status, setStatus] = React.useState<OrderStatus>('idle');
  const [statusMsg, setStatusMsg] = React.useState('');

  const submitOrder = async (side: 'BUY' | 'SELL') => {
    const qty = parseFloat(size);
    if (!qty || qty <= 0) {
      setStatus('error');
      setStatusMsg('Invalid size');
      return;
    }

    setStatus('pending');
    setStatusMsg('');

    try {
      const res = await fetch('http://localhost:8000/api/seed', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: activeSymbol, side, qty }),
      });

      if (res.ok) {
        setStatus('success');
        setStatusMsg(`${side} ${qty} ${activeSymbol} submitted`);
        // Refresh positions/orders after fill
        setTimeout(() => {
          useTradingStore.getState().fetchAPIIntegrations();
          setStatus('idle');
        }, 2000);
      } else {
        const err = await res.json().catch(() => ({}));
        setStatus('error');
        setStatusMsg((err as { detail?: string }).detail ?? 'Order rejected');
      }
    } catch {
      setStatus('error');
      setStatusMsg('Backend unavailable');
      setTimeout(() => setStatus('idle'), 3000);
    }
  };

  const isLoading = status === 'pending';

  return (
    <Card className="flex flex-col">
      <CardHeader className="py-2.5 px-3">
        <CardTitle className="text-xs uppercase tracking-wider font-semibold text-[var(--muted-foreground)]">Execution</CardTitle>
      </CardHeader>
      <CardContent className="p-3 space-y-4">
        {/* Order Type Tabs */}
        <div className="flex bg-[var(--panel-muted)] border border-[var(--border)] rounded-sm p-0.5">
          {(['market', 'limit', 'stop'] as OrderType[]).map((type) => (
            <button
              key={type}
              onClick={() => setOrderType(type)}
              className={`flex-1 text-xs font-medium py-1 capitalize rounded-sm transition-colors ${
                orderType === type
                  ? 'bg-[var(--panel)] text-[var(--foreground)] border border-[var(--border)] shadow-sm font-semibold'
                  : 'text-[var(--muted-foreground)] hover:text-[var(--foreground)]'
              }`}
            >
              {type.charAt(0).toUpperCase() + type.slice(1)}
            </button>
          ))}
        </div>

        {/* Form Inputs */}
        <div className="space-y-3">
          <div className="space-y-1.5">
            <div className="flex justify-between text-xs">
              <span className="text-[var(--muted-foreground)]">Size ({activeSymbol.split('/')[0]})</span>
              <span className="text-[var(--foreground)] font-mono tabular-nums">Max: 4.25</span>
            </div>
            <input
              type="number"
              value={size}
              onChange={(e) => setSize(e.target.value)}
              min="0"
              step="0.01"
              className="w-full bg-[var(--panel-muted)] border border-[var(--border)] rounded-sm p-2 text-sm font-mono tabular-nums focus:outline-none focus:border-[var(--kraken-purple)] transition-colors"
            />
          </div>

          <div className="grid grid-cols-2 gap-2 pt-2">
            <Button
              variant="success"
              className="w-full font-bold uppercase tracking-wider py-5 rounded-sm"
              onClick={() => submitOrder('BUY')}
              disabled={isLoading}
            >
              {isLoading ? '...' : 'Buy'}
            </Button>
            <Button
              variant="destructive"
              className="w-full font-bold uppercase tracking-wider py-5 rounded-sm"
              onClick={() => submitOrder('SELL')}
              disabled={isLoading}
            >
              {isLoading ? '...' : 'Sell'}
            </Button>
          </div>

          {/* Status feedback */}
          {status !== 'idle' && statusMsg && (
            <div className={`text-xs font-mono px-2 py-1 rounded-sm border ${
              status === 'success'
                ? 'text-[var(--neon-green)] border-[var(--neon-green)]/30 bg-[var(--neon-green)]/5'
                : status === 'error'
                ? 'text-[var(--neon-red)] border-[var(--neon-red)]/30 bg-[var(--neon-red)]/5'
                : 'text-[var(--muted-foreground)] border-[var(--border)]'
            }`}>
              {statusMsg}
            </div>
          )}
        </div>

        {/* Risk Metrics */}
        <div className="pt-3 mt-2 border-t border-[var(--border)] space-y-2">
          <div className="flex justify-between text-xs font-mono tabular-nums">
            <span className="text-[var(--muted-foreground)]">Margin Used</span>
            <span className="text-[var(--foreground)]">12.4%</span>
          </div>
          <div className="flex justify-between text-xs font-mono tabular-nums">
            <span className="text-[var(--muted-foreground)]">Est. Fee</span>
            <span className="text-[var(--foreground)]">$1.24</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
