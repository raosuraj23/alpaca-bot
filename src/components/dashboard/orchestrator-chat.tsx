"use client"

import { API_BASE } from '@/lib/api';
import * as React from 'react';
import ReactMarkdown from 'react-markdown';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { MessageSquare, X, Send, Bot, User } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

function stripCommandBlocks(text: string): string {
  return text.replace(/```json[\s\S]*?```/g, '').trim();
}

const MD_COMPONENTS: React.ComponentProps<typeof ReactMarkdown>['components'] = {
  p:    ({ children }) => <p className="mb-1 last:mb-0 leading-relaxed">{children}</p>,
  ul:   ({ children }) => <ul className="list-disc list-inside mb-1 space-y-0.5">{children}</ul>,
  ol:   ({ children }) => <ol className="list-decimal list-inside mb-1 space-y-0.5">{children}</ol>,
  li:   ({ children }) => <li className="leading-relaxed">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold text-[var(--foreground)]">{children}</strong>,
  em:   ({ children }) => <em className="text-[var(--muted-foreground)] not-italic">{children}</em>,
  h1:   ({ children }) => <p className="font-bold text-sm text-[var(--foreground)] mb-1 mt-2">{children}</p>,
  h2:   ({ children }) => <p className="font-semibold text-xs text-[var(--foreground)] mb-1 mt-2 uppercase tracking-wide">{children}</p>,
  h3:   ({ children }) => <p className="font-semibold text-xs text-[var(--muted-foreground)] mb-0.5 mt-1">{children}</p>,
  code: ({ children }) => <code className="font-mono text-[var(--neon-green)] bg-[var(--panel-muted)] px-1 rounded-sm text-xs">{children}</code>,
  pre:  ({ children }) => <pre className="font-mono text-xs bg-[var(--panel-muted)] border border-[var(--border)] rounded-sm p-2 my-1 overflow-x-auto whitespace-pre-wrap">{children}</pre>,
  blockquote: ({ children }) => <blockquote className="border-l-2 border-[var(--kraken-purple)] pl-2 text-[var(--muted-foreground)] my-1">{children}</blockquote>,
};

interface Message {
  id: string;
  sender: 'ai' | 'user';
  text: string;
}

export function OrchestratorChat() {
  const [isOpen, setIsOpen] = React.useState(false);
  const [messages, setMessages] = React.useState<Message[]>([
    { id: '1', sender: 'ai', text: 'Orchestrator System initialized. Market connection secure. How should we adjust the simulation boundary?' }
  ]);
  const [inputVal, setInputVal] = React.useState('');
  const [isTyping, setIsTyping] = React.useState(false);

  const submitMsg = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputVal.trim()) return;

    const userMsg: Message = { id: Date.now().toString(), sender: 'user', text: inputVal };
    setMessages(prev => [...prev, userMsg]);
    setInputVal('');

    // Hit the LangChain Backend
    setIsTyping(true);
    try {
      const res = await fetch(`${API_BASE}/api/agents/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: inputVal })
      });
      
      const data = await res.json();
      
      setMessages(p => [...p, {
        id: Date.now().toString() + 'ai',
        sender: 'ai',
        text: data.text || "An unexpected error occurred in the Swarm."
      }]);
    } catch (err) {
      setMessages(p => [...p, {
        id: Date.now().toString() + 'err',
        sender: 'ai',
        text: "[NETWORK ERROR] Could not reach the Orchestrator node. Ensure uvicorn is running."
      }]);
    } finally {
      setIsTyping(false);
    }
  };

  return (
    <>
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 20, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.95 }}
            transition={{ duration: 0.2 }}
            className="fixed bottom-20 right-6 z-50 w-[380px] h-[500px]"
          >
            <Card className="h-full flex flex-col shadow-2xl shadow-[var(--kraken-purple)]/20 border-[var(--kraken-purple)]/40 overflow-hidden backdrop-blur-xl bg-[var(--panel)]/95">
              <CardHeader className="py-3 px-4 border-b border-[var(--border)] flex flex-row items-center justify-between bg-gradient-to-r from-[var(--kraken-purple)]/20 to-transparent">
                <div className="flex items-center space-x-2">
                  <Bot className="w-5 h-5 text-[var(--kraken-light)]" />
                  <CardTitle className="text-sm font-bold text-[var(--foreground)] tracking-wide">Orchestrator</CardTitle>
                </div>
                <button onClick={() => setIsOpen(false)} className="text-[var(--muted-foreground)] hover:text-white transition-colors">
                  <X className="w-4 h-4" />
                </button>
              </CardHeader>
              
              <CardContent className="flex-1 p-0 flex flex-col overflow-hidden">
                <div className="flex-1 overflow-y-auto p-4 space-y-4">
                  {messages.map(m => (
                    <div key={m.id} className={`flex ${m.sender === 'user' ? 'justify-end' : 'justify-start'}`}>
                      <div className={`max-w-[85%] rounded-sm p-3 text-sm ${
                        m.sender === 'user' 
                        ? 'bg-[var(--kraken-purple)] text-white shadow-md' 
                        : 'bg-[var(--panel-muted)] border border-[var(--border)] text-[var(--foreground)]'
                      }`}>
                         <div className="flex items-center space-x-2 mb-1.5 opacity-50">
                           {m.sender === 'user' ? <User className="w-3 h-3" /> : <Bot className="w-3 h-3" />}
                           <span className="text-xs uppercase font-bold tracking-wider">{m.sender === 'user' ? 'SUPERUSER' : 'SYSTEM AGENT'}</span>
                         </div>
                         {m.sender === 'user' ? (
                           <p className="leading-relaxed text-xs">{m.text}</p>
                         ) : (
                           <div className="leading-relaxed text-xs">
                             <ReactMarkdown components={MD_COMPONENTS}>
                               {stripCommandBlocks(m.text)}
                             </ReactMarkdown>
                           </div>
                         )}
                      </div>
                    </div>
                  ))}
                  {isTyping && (
                    <div className="flex justify-start">
                      <div className="rounded-sm p-3 text-sm bg-[var(--panel-muted)] border border-[var(--border)] text-[var(--foreground)] opacity-70">
                         <p className="leading-relaxed text-xs">Orchestrator thinking...</p>
                      </div>
                    </div>
                  )}
                </div>

                {/* Input Area */}
                <form onSubmit={submitMsg} className="p-3 border-t border-[var(--border)] bg-[var(--panel)]/50">
                  <div className="relative flex items-center">
                    <input 
                      value={inputVal}
                      onChange={e => setInputVal(e.target.value)}
                      placeholder="Instruct the orchestrator..."
                      className="w-full bg-[var(--background)] border border-[var(--border)] text-[var(--foreground)] text-xs rounded-sm pl-3 pr-10 py-2.5 focus:outline-none focus:border-[var(--kraken-purple)] transition-colors"
                    />
                    <button type="submit" className="absolute right-2 text-[var(--kraken-purple)] hover:text-[var(--kraken-light)] transition-colors disabled:opacity-50" disabled={!inputVal.trim()}>
                      <Send className="w-4 h-4" />
                    </button>
                  </div>
                </form>
              </CardContent>
            </Card>
          </motion.div>
        )}
      </AnimatePresence>

      <motion.button
        whileHover={{ scale: 1.05 }}
        whileTap={{ scale: 0.95 }}
        onClick={() => setIsOpen(!isOpen)}
        className="fixed bottom-6 right-6 z-50 w-14 h-14 bg-[var(--kraken-purple)] rounded-sm flex items-center justify-center shadow-lg shadow-[var(--kraken-purple)]/40 hover:bg-[var(--kraken-light)] transition-colors border border-white/10"
      >
        {isOpen ? <X className="w-6 h-6 text-white" /> : <MessageSquare className="w-6 h-6 text-white" />}
      </motion.button>
    </>
  );
}
