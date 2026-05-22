import { useState, useRef, useEffect } from "react";
import NavBar from "../components/NavBar";
import api from "../api/client";

interface ToolEntry { name: string; index: number; }
interface Message {
  role: "user" | "agent";
  text: string;
  toolNames?: string[];
  promptTokens?: number;
  completionTokens?: number;
}

const TOOL_ICONS: Record<string, string> = {
  ingest_file: "📎",
  get_job_status: "🔍",
  query_rag: "💬",
  list_documents: "📋",
  summarize_document: "📄",
};

export default function AgentPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [toolLog, setToolLog] = useState<ToolEntry[]>([]);
  const [expandedTools, setExpandedTools] = useState<Set<number>>(new Set());
  const [uploadDir] = useState("/tmp/geminirag_uploads");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async () => {
    if (!input.trim() || loading) return;
    const msg = input.trim();
    setInput("");
    setMessages(prev => [...prev, { role: "user", text: msg }]);
    setLoading(true);

    try {
      const r = await api.post("/v1/agent/chat", { message: msg, session_id: sessionId });
      const { response, tool_calls_made, session_id, prompt_tokens, completion_tokens } = r.data;
      if (!sessionId) setSessionId(session_id);

      if (tool_calls_made?.length) {
        const startIdx = toolLog.length;
        setToolLog(prev => [
          ...prev,
          ...(tool_calls_made as string[]).map((name, i) => ({ name, index: startIdx + i })),
        ]);
      }

      setMessages(prev => [...prev, {
        role: "agent",
        text: response || "(no response)",
        toolNames: tool_calls_made,
        promptTokens: prompt_tokens,
        completionTokens: completion_tokens,
      }]);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setMessages(prev => [...prev, { role: "agent", text: `Error: ${err.response?.data?.detail || err.message}` }]);
    } finally { setLoading(false); }
  };

  const clear = () => {
    setMessages([]); setToolLog([]); setSessionId(undefined); setExpandedTools(new Set());
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  };

  const toggleTool = (i: number) =>
    setExpandedTools(prev => { const s = new Set(prev); s.has(i) ? s.delete(i) : s.add(i); return s; });

  function renderMarkdown(text: string) {
    const lines = text.split("\n");
    return lines.map((line, i) => {
      const parts = line.split(/(\*\*[^*]+\*\*|`[^`]+`|\[\d+\])/g);
      return (
        <span key={i}>
          {parts.map((p, j) => {
            if (/^\*\*(.+)\*\*$/.test(p)) return <strong key={j}>{p.slice(2, -2)}</strong>;
            if (/^`(.+)`$/.test(p)) return <code key={j} className="bg-gray-100 px-1 rounded text-xs font-mono">{p.slice(1, -1)}</code>;
            if (/^\[\d+\]$/.test(p)) return <sup key={j} className="text-indigo-600 font-semibold">{p}</sup>;
            return <span key={j}>{p}</span>;
          })}
          {i < lines.length - 1 && <br />}
        </span>
      );
    });
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar />
      <div className="flex h-[calc(100vh-56px)]">
        {/* Tool log panel */}
        <aside className="w-72 shrink-0 border-r bg-white flex flex-col">
          <div className="px-4 py-3 border-b flex items-center justify-between">
            <h2 className="font-semibold text-gray-700 text-sm">Tool calls</h2>
            <span className="text-xs text-gray-400">{toolLog.length}</span>
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {toolLog.length === 0 && <p className="text-xs text-gray-400 text-center mt-4">No tool calls yet</p>}
            {toolLog.map((tc, i) => (
              <div key={i} className="border rounded-lg overflow-hidden">
                <button onClick={() => toggleTool(i)}
                  className="w-full px-3 py-2 flex items-center gap-2 text-left hover:bg-gray-50 text-sm">
                  <span>{TOOL_ICONS[tc.name] || "🔧"}</span>
                  <span className="font-medium text-gray-700 flex-1">{tc.name}</span>
                  <span className="text-xs bg-green-100 text-green-700 px-1.5 py-0.5 rounded-full">called</span>
                  <span className="text-gray-400 text-xs">{expandedTools.has(i) ? "▲" : "▼"}</span>
                </button>
                {expandedTools.has(i) && (
                  <div className="border-t bg-gray-50 px-3 py-2 text-xs text-gray-500">
                    <p><span className="font-medium">Tool:</span> {tc.name}</p>
                    <p className="mt-1"><span className="font-medium">Result:</span> see agent response</p>
                  </div>
                )}
              </div>
            ))}
          </div>
          <div className="px-3 py-2 border-t">
            <p className="text-xs text-gray-400 mb-1">Upload dir:</p>
            <p className="text-xs text-gray-600 font-mono break-all">{uploadDir}</p>
          </div>
        </aside>

        {/* Chat panel */}
        <main className="flex-1 flex flex-col">
          <div className="px-4 py-3 border-b bg-white flex items-center justify-between">
            <h2 className="font-semibold text-gray-700">Agent Chat</h2>
            <button onClick={clear} className="text-xs text-gray-500 hover:text-gray-700 border px-2 py-1 rounded">
              Clear conversation
            </button>
          </div>

          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
            {messages.length === 0 && (
              <div className="text-center text-gray-400 text-sm mt-12">
                <p className="text-2xl mb-2">🤖</p>
                <p>Ask me to ingest a file, answer questions, or list your documents.</p>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`flex flex-col ${m.role === "user" ? "items-end" : "items-start"}`}>
                <div className={`max-w-xl rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                  m.role === "user"
                    ? "bg-indigo-600 text-white rounded-br-sm"
                    : "bg-white border shadow-sm text-gray-800 rounded-bl-sm"
                }`}>
                  {m.role === "agent" ? renderMarkdown(m.text) : m.text}
                </div>
                {m.role === "agent" && (m.promptTokens || m.completionTokens) && (
                  <p className="text-xs text-gray-400 mt-1 px-1">
                    {m.promptTokens ? `prompt: ${m.promptTokens} tok` : ""}
                    {m.promptTokens && m.completionTokens ? " · " : ""}
                    {m.completionTokens ? `completion: ${m.completionTokens} tok` : ""}
                  </p>
                )}
              </div>
            ))}
            {loading && (
              <div className="flex justify-start">
                <div className="bg-white border shadow-sm rounded-2xl rounded-bl-sm px-4 py-3 text-sm text-gray-500">
                  <span className="inline-flex gap-1">
                    <span className="animate-bounce">●</span>
                    <span className="animate-bounce" style={{ animationDelay: "0.1s" }}>●</span>
                    <span className="animate-bounce" style={{ animationDelay: "0.2s" }}>●</span>
                  </span>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="border-t bg-white px-4 py-3">
            <div className="flex gap-2">
              <textarea value={input} onChange={e => setInput(e.target.value)} onKeyDown={handleKeyDown}
                rows={2} placeholder="Message the agent... (Enter to send, Shift+Enter for newline)"
                disabled={loading}
                className="flex-1 border rounded-xl px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50" />
              <button onClick={send} disabled={loading || !input.trim()}
                className="bg-indigo-600 text-white px-4 rounded-xl font-medium hover:bg-indigo-700 disabled:opacity-50 text-sm">
                Send
              </button>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
