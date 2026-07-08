import { useState, useRef, useEffect } from 'react';
import { Send, Bot, User, Loader, AlertCircle, BookOpen, Wifi, WifiOff, Settings } from 'lucide-react';

interface Source {
  pmc_id: string;
  molecule_name: string;
  similarity?: number;
}

interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  sources?: Source[];
  mode?: string;
  chunks_retrieved?: number;
  timestamp: Date;
}

const EXAMPLE_QUESTIONS = [
  "What piezoelectric crystals are in the monoclinic system?",
  "Tell me about L-Arginine Hydrochloride Monohydrate",
  "Which crystals have the highest piezoelectric coefficients?",
  "Compare the crystal structures of PMC-007 and PMC-010",
  "How many crystals are in the database?",
  "What is the space group of L-Alanine?",
];

export default function AiChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [llmStatus, setLlmStatus] = useState<'unknown' | 'connected' | 'disconnected'>('unknown');
  const [llmMessage, setLlmMessage] = useState('');
  const chatEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Read settings from localStorage (set by Settings page)
  const getSettings = () => {
    try {
      const stored = localStorage.getItem('piezo_settings');
      if (stored) {
        const s = JSON.parse(stored);
        return {
          backendUrl: s.backendUrl || 'http://localhost:5000',
          llmUrl: s.llmUrl || 'http://localhost:11434',
          temperature: s.temperature ?? 0.2,
          topK: s.topK ?? 5,
        };
      }
    } catch { /* use defaults */ }
    return {
      backendUrl: 'http://localhost:5000',
      llmUrl: 'http://localhost:11434',
      temperature: 0.2,
      topK: 5,
    };
  };

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  // Check LLM connection on mount
  useEffect(() => {
    checkLlmConnection();
  }, []);

  const checkLlmConnection = async () => {
    const settings = getSettings();
    try {
      const resp = await fetch(`${settings.backendUrl}/api/chat/test-llm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ llm_url: settings.llmUrl }),
      });
      const data = await resp.json();
      setLlmStatus(data.connected && data.qwen3_loaded ? 'connected' : 'disconnected');
      setLlmMessage(data.message || data.error || '');
    } catch {
      setLlmStatus('disconnected');
      setLlmMessage('Backend not reachable');
    }
  };

  const sendMessage = async () => {
    const question = input.trim();
    if (!question || loading) return;

    const settings = getSettings();

    // Add user message
    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: question,
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    try {
      const resp = await fetch(`${settings.backendUrl}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question,
          temperature: settings.temperature,
          top_k: settings.topK,
          llm_url: settings.llmUrl,
        }),
      });

      const data = await resp.json();

      if (data.error) {
        const errorMsg: Message = {
          id: (Date.now() + 1).toString(),
          role: 'system',
          content: data.error + (data.hint ? `\n\n💡 ${data.hint}` : ''),
          timestamp: new Date(),
        };
        setMessages(prev => [...prev, errorMsg]);
      } else {
        const assistantMsg: Message = {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          content: data.answer,
          sources: data.sources,
          mode: data.mode,
          chunks_retrieved: data.chunks_retrieved,
          timestamp: new Date(),
        };
        setMessages(prev => [...prev, assistantMsg]);
      }
    } catch (err) {
      const errorMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: 'system',
        content: `Failed to reach backend. Is Flask running at ${settings.backendUrl}?`,
        timestamp: new Date(),
      };
      setMessages(prev => [...prev, errorMsg]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const handleExampleClick = (q: string) => {
    setInput(q);
    inputRef.current?.focus();
  };

  return (
    <div className="flex flex-col h-[calc(100vh-64px)]">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700/50">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-600 to-purple-700 flex items-center justify-center">
            <Bot className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white">Piezo-LLM Chat</h1>
            <p className="text-xs text-gray-400">Qwen3-8B · RAG over {'>'}40 molecular crystals</p>
          </div>
        </div>
        <button
          onClick={checkLlmConnection}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm transition-colors ${
            llmStatus === 'connected'
              ? 'bg-green-900/30 text-green-400 border border-green-500/30'
              : llmStatus === 'disconnected'
              ? 'bg-red-900/30 text-red-400 border border-red-500/30'
              : 'bg-gray-800 text-gray-400 border border-gray-600/30'
          }`}
          title={llmMessage}
        >
          {llmStatus === 'connected' ? (
            <Wifi className="w-4 h-4" />
          ) : (
            <WifiOff className="w-4 h-4" />
          )}
          {llmStatus === 'connected' ? 'Qwen3 Online' : llmStatus === 'disconnected' ? 'LLM Offline' : 'Checking...'}
        </button>
      </div>

      {/* Chat messages area */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {messages.length === 0 ? (
          /* Welcome screen */
          <div className="flex flex-col items-center justify-center h-full text-center max-w-2xl mx-auto">
            <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-violet-600 to-purple-700 flex items-center justify-center mb-6">
              <Bot className="w-8 h-8 text-white" />
            </div>
            <h2 className="text-2xl font-bold text-white mb-2">
              Ask about piezoelectric crystals
            </h2>
            <p className="text-gray-400 mb-8">
              I can search the PMC database, retrieve crystal properties,
              compare structures, and answer research questions using
              RAG-powered Qwen3-8B.
            </p>

            {llmStatus === 'disconnected' && (
              <div className="w-full bg-amber-900/20 border border-amber-500/30 rounded-xl p-4 mb-6 text-left">
                <div className="flex items-start gap-3">
                  <AlertCircle className="w-5 h-5 text-amber-400 mt-0.5 flex-shrink-0" />
                  <div>
                    <p className="text-amber-300 font-medium text-sm">LLM server not connected</p>
                    <p className="text-amber-400/70 text-xs mt-1">
                      {llmMessage || 'Start Ollama on your GPU server and run: ollama pull qwen3:8b'}
                    </p>
                    <p className="text-amber-400/70 text-xs mt-1">
                      Configure the LLM URL in Settings → AI Chat Settings.
                    </p>
                  </div>
                </div>
              </div>
            )}

            <div className="w-full">
              <p className="text-sm text-gray-500 mb-3">Try one of these:</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {EXAMPLE_QUESTIONS.map((q, i) => (
                  <button
                    key={i}
                    onClick={() => handleExampleClick(q)}
                    className="text-left px-4 py-3 bg-gray-800/50 hover:bg-gray-700/50 border border-gray-700/50 hover:border-purple-500/30 rounded-xl text-sm text-gray-300 transition-all"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          /* Message list */
          messages.map(msg => (
            <div
              key={msg.id}
              className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              {msg.role !== 'user' && (
                <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 mt-1 ${
                  msg.role === 'system'
                    ? 'bg-amber-900/30'
                    : 'bg-gradient-to-br from-violet-600 to-purple-700'
                }`}>
                  {msg.role === 'system' ? (
                    <AlertCircle className="w-4 h-4 text-amber-400" />
                  ) : (
                    <Bot className="w-4 h-4 text-white" />
                  )}
                </div>
              )}

              <div className={`max-w-[75%] ${msg.role === 'user' ? 'order-first' : ''}`}>
                <div
                  className={`rounded-2xl px-4 py-3 ${
                    msg.role === 'user'
                      ? 'bg-gradient-to-r from-violet-600 to-purple-600 text-white'
                      : msg.role === 'system'
                      ? 'bg-amber-900/20 border border-amber-500/30 text-amber-300'
                      : 'bg-gray-800/80 border border-gray-700/50 text-gray-200'
                  }`}
                >
                  <div className="text-sm whitespace-pre-wrap leading-relaxed">
                    {msg.content}
                  </div>
                </div>

                {/* Source badges */}
                {msg.sources && msg.sources.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <BookOpen className="w-3.5 h-3.5 text-gray-500 mt-0.5" />
                    {msg.sources.map((src, i) => (
                      <span
                        key={i}
                        className="inline-flex items-center gap-1 px-2 py-0.5 bg-purple-900/20 border border-purple-500/20 rounded-md text-xs text-purple-300"
                        title={`${src.molecule_name}${src.similarity ? ` (${Math.round(src.similarity * 100)}% match)` : ''}`}
                      >
                        {src.pmc_id}
                        {src.similarity && (
                          <span className="text-purple-400/60">
                            {Math.round(src.similarity * 100)}%
                          </span>
                        )}
                      </span>
                    ))}
                  </div>
                )}

                <div className="text-[10px] text-gray-600 mt-1 px-1">
                  {msg.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </div>
              </div>

              {msg.role === 'user' && (
                <div className="w-8 h-8 rounded-lg bg-gray-700 flex items-center justify-center flex-shrink-0 mt-1">
                  <User className="w-4 h-4 text-gray-300" />
                </div>
              )}
            </div>
          ))
        )}

        {/* Loading indicator */}
        {loading && (
          <div className="flex gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-600 to-purple-700 flex items-center justify-center flex-shrink-0">
              <Bot className="w-4 h-4 text-white" />
            </div>
            <div className="bg-gray-800/80 border border-gray-700/50 rounded-2xl px-4 py-3">
              <div className="flex items-center gap-2 text-sm text-gray-400">
                <Loader className="w-4 h-4 animate-spin" />
                Searching database & generating answer...
              </div>
            </div>
          </div>
        )}

        <div ref={chatEndRef} />
      </div>

      {/* Input area */}
      <div className="px-6 py-4 border-t border-gray-700/50">
        <div className="flex gap-3 items-end max-w-4xl mx-auto">
          <div className="flex-1 relative">
            <textarea
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about piezoelectric crystals..."
              rows={1}
              className="w-full bg-gray-800/80 border border-gray-700/50 focus:border-purple-500/50 rounded-xl px-4 py-3 pr-12 text-sm text-gray-200 placeholder-gray-500 resize-none outline-none transition-colors"
              style={{ minHeight: '44px', maxHeight: '120px' }}
              onInput={e => {
                const target = e.target as HTMLTextAreaElement;
                target.style.height = '44px';
                target.style.height = Math.min(target.scrollHeight, 120) + 'px';
              }}
              disabled={loading}
            />
          </div>
          <button
            onClick={sendMessage}
            disabled={loading || !input.trim()}
            className="w-11 h-11 rounded-xl bg-gradient-to-r from-violet-600 to-purple-600 hover:from-violet-500 hover:to-purple-500 disabled:from-gray-700 disabled:to-gray-700 flex items-center justify-center transition-all disabled:opacity-40"
          >
            <Send className="w-4 h-4 text-white" />
          </button>
        </div>
        <p className="text-[11px] text-gray-600 text-center mt-2">
          Piezo-LLM answers from the PMC database only. Always verify critical values against original papers.
        </p>
      </div>
    </div>
  );
}