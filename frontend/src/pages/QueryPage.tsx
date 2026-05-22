import { useState, useEffect, useRef } from "react";
import NavBar from "../components/NavBar";
import api from "../api/client";
import { useToastContext } from "../context/ToastContext";

interface Document { job_id: string; filename: string; file_type: string; chunk_count?: number; }
interface Citation { source: string; page?: string; excerpt: string; index?: number; page_or_segment?: string; filename?: string; }
interface QueryResult {
  answer: string;
  citations: Citation[];
  confidence_gate_passed: boolean;
  prompt_tokens?: number;
  completion_tokens?: number;
  latency_ms?: number;
  ragas_scores?: Record<string, number>;
}
interface HistoryItem { question: string; result: QueryResult; }

const FILE_ICONS: Record<string, string> = { pdf: "PDF", docx: "DOC", xlsx: "XLS", csv: "CSV", image: "IMG", video: "VID", audio: "AUD" };

function scoreColor(v: number, isFaith = false): string {
  const hi = isFaith ? 0.8 : 0.7;
  const mid = isFaith ? 0.7 : 0.5;
  if (v >= hi) return "bg-green-100 text-green-700";
  if (v >= mid) return "bg-amber-100 text-amber-700";
  return "bg-red-100 text-red-700";
}

function renderAnswer(text: string) {
  const parts = text.split(/(\[\d+\])/g);
  return parts.map((p, i) => {
    const m = p.match(/^\[(\d+)\]$/);
    if (m) return <sup key={i} className="text-indigo-600 font-semibold cursor-pointer hover:underline" onClick={() => document.getElementById(`cite-${m[1]}`)?.scrollIntoView({ behavior: "smooth" })}>{p}</sup>;
    return <span key={i}>{p}</span>;
  });
}

export default function QueryPage() {
  const [docs, setDocs] = useState<Document[]>([]);
  const [docsLoading, setDocsLoading] = useState(true);
  const [docsError, setDocsError] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [streamingText, setStreamingText] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamMode, setStreamMode] = useState(false);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { addToast } = useToastContext();

  const loadDocs = () => {
    setDocsLoading(true);
    setDocsError(false);
    api.get("/v1/documents")
      .then(r => setDocs(r.data))
      .catch(() => setDocsError(true))
      .finally(() => setDocsLoading(false));
  };

  useEffect(() => { loadDocs(); }, []);

  const toggleDoc = (id: string) =>
    setSelected(prev => { const s = new Set(prev); s.has(id) ? s.delete(id) : s.add(id); return s; });
  const toggleAll = () =>
    setSelected(prev => prev.size === docs.length ? new Set() : new Set(docs.map(d => d.job_id)));

  const submitStream = async () => {
    setError(""); setLoading(true); setResult(null); setStreamingText(""); setStreaming(true);
    addToast("Query submitted", "info");
    const body: { question: string; job_ids?: string[] } = { question };
    if (selected.size > 0) body.job_ids = [...selected];

    try {
      const token = (api.defaults.headers.common["Authorization"] as string | undefined)?.replace("Bearer ", "");
      const resp = await fetch(`${api.defaults.baseURL}/v1/query/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: "Stream request failed" }));
        throw new Error(err.detail || "Stream request failed");
      }

      const reader = resp.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = JSON.parse(line.slice(6));
          if (data.type === "chunk") {
            setStreamingText(prev => prev + data.text);
          } else if (data.type === "done") {
            const finalResult: QueryResult = {
              answer: data.answer,
              citations: (data.citations || []).map((c: { filename?: string; page_or_segment?: string; excerpt?: string }) => ({
                source: c.filename || "",
                page: c.page_or_segment,
                excerpt: c.excerpt || "",
              })),
              confidence_gate_passed: data.confidence_gate_passed,
              ragas_scores: data.ragas_scores,
            };
            setResult(finalResult);
            setStreamingText("");
            setHistory(prev => [{ question, result: finalResult }, ...prev.slice(0, 9)]);
          } else if (data.type === "error") {
            throw new Error(data.message);
          }
        }
      }
    } catch (e: unknown) {
      const err = e as Error;
      setError(err.message || "Stream query failed");
    } finally {
      setLoading(false);
      setStreaming(false);
    }
  };

  const submit = async () => {
    if (!question.trim()) return;
    if (streamMode) { await submitStream(); return; }
    setError(""); setLoading(true); setResult(null);
    addToast("Query submitted", "info");
    try {
      const body: { question: string; job_ids?: string[] } = { question };
      if (selected.size > 0) body.job_ids = [...selected];
      const r = await api.post("/v1/query", body);
      setResult(r.data);
      setHistory(prev => [{ question, result: r.data }, ...prev.slice(0, 9)]);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      setError(err.response?.data?.detail || "Query failed");
    } finally { setLoading(false); }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && e.ctrlKey) submit();
  };

  const copyAnswer = () => {
    if (!result?.answer) return;
    navigator.clipboard.writeText(result.answer).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const displayAnswer = result?.answer || streamingText;

  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar />
      <div className="flex flex-col md:flex-row max-w-6xl mx-auto px-4 py-6 gap-6">
        {/* Sidebar */}
        <aside className="w-full md:w-64 shrink-0">
          <div className="bg-white rounded-xl shadow-sm border p-4">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-semibold text-gray-700 text-sm">Documents</h2>
              <button onClick={toggleAll} className="text-xs text-indigo-600 hover:underline">
                {selected.size === docs.length && docs.length > 0 ? "Deselect all" : "Select all"}
              </button>
            </div>
            {docsLoading && (
              <div className="space-y-2">
                {[...Array(3)].map((_, i) => <div key={i} className="h-6 bg-gray-200 animate-pulse rounded" />)}
              </div>
            )}
            {docsError && (
              <div className="text-center py-3">
                <p className="text-xs text-red-500 mb-2">Failed to load documents</p>
                <button onClick={loadDocs} className="text-xs text-indigo-600 hover:underline">Retry</button>
              </div>
            )}
            {!docsLoading && !docsError && docs.length === 0 && (
              <p className="text-xs text-gray-400">No completed documents</p>
            )}
            {docs.map(d => (
              <label key={d.job_id} className="flex items-center gap-2 py-1 cursor-pointer hover:bg-gray-50 rounded px-1">
                <input type="checkbox" checked={selected.has(d.job_id)} onChange={() => toggleDoc(d.job_id)} className="accent-indigo-600" />
                <span className="text-xs font-mono bg-gray-100 px-1 rounded">{FILE_ICONS[d.file_type] || "DOC"}</span>
                <span className="text-sm text-gray-700 truncate" title={d.filename}>{d.filename}</span>
              </label>
            ))}
            {selected.size === 0 && docs.length > 0 && <p className="text-xs text-gray-400 mt-2">None selected — searches all</p>}
          </div>
        </aside>

        {/* Main */}
        <main className="flex-1 min-w-0">
          <div className="bg-white rounded-xl shadow-sm border p-5">
            <textarea ref={textareaRef} value={question} onChange={e => setQuestion(e.target.value)}
              onKeyDown={handleKeyDown} rows={3} placeholder="Ask a question... (Ctrl+Enter to submit)"
              className="w-full border rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-indigo-500" />
            <div className="flex items-center justify-between mt-2 flex-wrap gap-2">
              {error && (
                <span className="text-red-600 text-sm flex items-center gap-2">
                  {error}
                  <button onClick={submit} className="text-xs text-indigo-600 hover:underline">Retry</button>
                </span>
              )}
              <div className="flex items-center gap-3 ml-auto">
                <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer select-none">
                  <input type="checkbox" checked={streamMode} onChange={e => setStreamMode(e.target.checked)} className="accent-indigo-600" />
                  Stream
                </label>
                <button onClick={submit} disabled={loading || !question.trim()}
                  className="bg-indigo-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 flex items-center gap-2">
                  {loading && <span className="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />}
                  {loading ? (streaming ? "Streaming..." : "Searching...") : "Search"}
                </button>
              </div>
            </div>
          </div>

          {(displayAnswer || result) && (
            <div className="mt-4 bg-white rounded-xl shadow-sm border p-5 space-y-4">
              {result && !result.confidence_gate_passed && (
                <div className="bg-amber-50 border border-amber-200 text-amber-700 rounded px-3 py-2 text-sm">
                  Low confidence — answer may be unreliable
                </div>
              )}
              <div className="flex items-start justify-between gap-3">
                <p className="text-gray-800 leading-relaxed flex-1">
                  {result ? renderAnswer(result.answer) : <span>{streamingText}<span className="animate-pulse">▌</span></span>}
                </p>
                {result && (
                  <button onClick={copyAnswer} title="Copy answer" className="shrink-0 text-gray-400 hover:text-gray-700 p-1 rounded transition-colors">
                    {copied ? (
                      <svg className="w-4 h-4 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" /></svg>
                    ) : (
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>
                    )}
                  </button>
                )}
              </div>

              {result && result.citations?.length > 0 && (
                <div className="border-t pt-3">
                  <h3 className="text-sm font-semibold text-gray-600 mb-2">Citations</h3>
                  {result.citations.map((c, i) => (
                    <div id={`cite-${i + 1}`} key={i} className="text-sm text-gray-600 mb-2 pl-3 border-l-2 border-indigo-200">
                      <span className="font-medium text-indigo-600">[{i + 1}]</span> {c.source || c.filename}{(c.page || c.page_or_segment) ? ` — ${c.page || c.page_or_segment}` : ""}
                      {c.excerpt && <p className="text-gray-500 text-xs mt-0.5 line-clamp-2">{c.excerpt}</p>}
                    </div>
                  ))}
                </div>
              )}

              {result && (result.ragas_scores && Object.keys(result.ragas_scores).length > 0 ? (
                <div className="border-t pt-3 flex gap-2 flex-wrap">
                  {Object.entries(result.ragas_scores).map(([k, v]) => (
                    <span key={k} className={`text-xs px-2 py-1 rounded-full font-medium ${scoreColor(v, k === "faithfulness")}`}>
                      {k.replace(/_/g, " ")}: {v.toFixed(2)}
                    </span>
                  ))}
                </div>
              ) : (
                <div className="border-t pt-3">
                  <span className="text-xs bg-gray-100 text-gray-500 px-2 py-1 rounded-full animate-pulse">
                    Evaluating quality scores...
                  </span>
                </div>
              ))}

              {result && (result.prompt_tokens || result.latency_ms) && (
                <div className="border-t pt-2 text-xs text-gray-400 flex gap-4">
                  {result.prompt_tokens && <span>Prompt: {result.prompt_tokens} tok</span>}
                  {result.completion_tokens && <span>Completion: {result.completion_tokens} tok</span>}
                  {result.latency_ms && <span>Latency: {result.latency_ms}ms</span>}
                </div>
              )}
            </div>
          )}

          {history.length > 0 && (
            <div className="mt-4">
              <button onClick={() => setHistoryOpen(o => !o)} className="text-sm text-indigo-600 hover:underline mb-2">
                {historyOpen ? "Hide" : "Show"} query history ({history.length})
              </button>
              {historyOpen && (
                <div className="space-y-2">
                  {history.map((h, i) => (
                    <div key={i} className="bg-white rounded-lg border px-4 py-2 text-sm cursor-pointer hover:bg-gray-50"
                      onClick={() => { setQuestion(h.question); setResult(h.result); }}>
                      <p className="text-gray-700 truncate">{h.question}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
