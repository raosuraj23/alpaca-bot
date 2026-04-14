"use client"

import * as React from 'react';
import { motion } from 'framer-motion';

export function ValueTicker({ value, decimals = 2, prefix = '' }: { value: number, decimals?: number, prefix?: string }) {
  const [prev, setPrev] = React.useState(value);
  const [flash, setFlash] = React.useState<'up' | 'down' | null>(null);

  React.useEffect(() => {
    if (value > prev) {
      setFlash('up');
    } else if (value < prev) {
      setFlash('down');
    }
    setPrev(value);
    
    const t = setTimeout(() => setFlash(null), 300);
    return () => clearTimeout(t);
  }, [value, prev]);

  return (
    <motion.div
      className={`tabular-nums font-mono transition-colors duration-300 ${
        flash === 'up' ? 'text-[var(--neon-green)]' 
        : flash === 'down' ? 'text-[var(--neon-red)]' 
        : 'text-[var(--foreground)]'
      }`}
      key={`${value}-${flash}`} // This breaks the standard text-nodes for react, but ensures no glitching. Wait, no we'll just let css handle color transitions
    >
      {prefix}{value.toFixed(decimals)}
    </motion.div>
  );
}
