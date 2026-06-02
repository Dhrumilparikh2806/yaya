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

const FILE_ICONS: Record<string, string> = {
  pdf: "PDF", docx: "DOC", xlsx: "XLS", csv: "CSV", image: "IMG", video: "VID", audio: "AUD",
};

const SUGGESTED_QUERIES = [
  "Summarize the key findings",
  "What are the main risks?",
  "List all action items",
  "What conclusions were drawn?",
];

function ragasBadgeClass(v: number, isFaith = false): string {
  const hi = isFaith ? 0.8 : 0.7;
  const mid = isFaith ? 0.7 : 0.5;
  if (v >= hi) return "badge badge-ok";
  if (v >= mid) return "badge badge-warn";
  return "badge badge-err";
}

function renderAnswer(text: string) {
  const parts = text.split(/(\[\d+\])/g);
  return parts.map((p, i) => {
    const m = p.match(/^\[(\d+)\]$/);
    if (m) {
      return (
        <sup
          key={i}
          className="cite"
          style={{ cursor: "pointer", color: "var(--teal-link)", fontWeight: 600 }}
          onClick={() => document.getElementById(`cite-${m[1]}`)?.scrollIntoView({ behavior: "smooth" })}
        >
          [{m[1]}]
        </sup>
      );
    }
    return <span key={i}>{p}</span>;
  });
}

export default function QueryPage() {
  const [docs, setDocs] = useState<Document[]>([]);
  const [docsLoading, setDocsLoading] = useState(true);
  const [docsError, setDocsError] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [streamingText, setStreamingText] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamMode, setStreamMode] = useState(false);
  const [error, setError] = useState("");
  const [queryHistory, setQueryHistory] = useState<HistoryItem[]>([]);
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
    setSelectedIds(prev => { const s = new Set(prev); s.has(id) ? s.delete(id) : s.add(id); return s; });

  const toggleAll = () =>
    setSelectedIds(prev => prev.size === docs.length ? new Set() : new Set(docs.map(d => d.job_id)));

  const submitStream = async () => {
    setError(""); setLoading(true); setResult(null); setStreamingText(""); setStreaming(true);
    addToast("Query submitted", "info");
    const body: { question: string; job_ids?: string[] } = { question };
    if (selectedIds.size > 0) body.job_ids = [...selectedIds];

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
            setQueryHistory(prev => [{ question, result: finalResult }, ...prev.slice(0, 9)]);
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
      if (selectedIds.size > 0) body.job_ids = [...selectedIds];
      const r = await api.post("/v1/query", body);
      setResult(r.data);
      setQueryHistory(prev => [{ question, result: r.data }, ...prev.slice(0, 9)]);
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
  const latencyDisplay = result?.latency_ms ? `${(result.latency_ms / 1000).toFixed(1)}s` : "—";
  const confidenceDisplay = result ? (result.confidence_gate_passed ? "High" : "Low") : "—";

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)" }}>
      <NavBar />

      <div className="page">
        {/* Page header */}
        <div className="page-head">
          <h1 className="page-title">Query your documents</h1>
          <p className="page-sub">Ask questions across your indexed documents using semantic search and RAG.</p>
        </div>

        {/* Stat strip */}
        <div className="stat-grid" style={{ marginBottom: 28 }}>
          <div className="stat-card">
            <div className="head">Indexed Documents</div>
            <div className="v">{docs.length}</div>
            <div className="k">ready to query</div>
          </div>
          <div className="stat-card">
            <div className="head">Queries Today</div>
            <div className="v">{queryHistory.length}</div>
            <div className="k">this session</div>
          </div>
          <div className="stat-card">
            <div className="head">Confidence</div>
            <div
              className="v"
              style={{
                color: result
                  ? result.confidence_gate_passed ? "var(--ok-fg)" : "var(--warn-fg)"
                  : "var(--slate-2)",
                fontSize: "1.25rem",
              }}
            >
              {confidenceDisplay}
            </div>
            <div className="k">last result</div>
          </div>
          <div className="stat-card">
            <div className="head">Latency</div>
            <div className="v">{latencyDisplay}</div>
            <div className="k">last query</div>
          </div>
        </div>

        {/* Query grid: sidebar + main */}
        <div
          className="query-grid"
          style={{
            display: "grid",
            gridTemplateColumns: "300px 1fr",
            gap: 24,
            alignItems: "start",
          }}
        >
          {/* LEFT: Document panel */}
          <aside className="doc-panel" style={{ position: "sticky", top: 80 }}>
            <div className="card">
              <div
                className="doc-head"
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "16px 20px 12px",
                  borderBottom: "1px solid var(--line)",
                }}
              >
                <h3 style={{ fontSize: "0.9375rem", fontWeight: 700, color: "var(--navy)" }}>Documents</h3>
                <button
                  onClick={toggleAll}
                  style={{
                    fontSize: "0.8125rem",
                    fontWeight: 600,
                    color: "var(--teal-link)",
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    padding: 0,
                  }}
                >
                  {selectedIds.size === docs.length && docs.length > 0 ? "Deselect All" : "Select All"}
                </button>
              </div>

              <div className="doc-list" style={{ padding: "8px 12px 12px", maxHeight: 400, overflowY: "auto" }}>
                {docsLoading && (
                  <div style={{ padding: "8px 0" }}>
                    {[0, 1, 2].map(i => (
                      <div
                        key={i}
                        className="is-processing"
                        style={{
                          height: 32,
                          background: "var(--line)",
                          borderRadius: "var(--r-sm)",
                          marginBottom: 8,
                        }}
                      />
                    ))}
                  </div>
                )}

                {docsError && (
                  <div style={{ textAlign: "center", padding: "12px 0" }}>
                    <p style={{ fontSize: "0.8125rem", color: "var(--err-fg)", marginBottom: 6 }}>Failed to load documents</p>
                    <button
                      onClick={loadDocs}
                      style={{ fontSize: "0.8125rem", color: "var(--teal-link)", fontWeight: 600, background: "none", border: "none", cursor: "pointer" }}
                    >
                      Retry
                    </button>
                  </div>
                )}

                {!docsLoading && !docsError && docs.length === 0 && (
                  <p style={{ fontSize: "0.8125rem", color: "var(--slate-2)", padding: "8px 4px" }}>No completed documents</p>
                )}

                {docs.map(d => (
                  <label
                    key={d.job_id}
                    className="doc-item"
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      padding: "7px 8px",
                      borderRadius: "var(--r-sm)",
                      cursor: "pointer",
                      transition: "background var(--t-fast)",
                    }}
                    onMouseEnter={e => (e.currentTarget.style.background = "var(--tile)")}
                    onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
                  >
                    <input
                      type="checkbox"
                      checked={selectedIds.has(d.job_id)}
                      onChange={() => toggleDoc(d.job_id)}
                      style={{ accentColor: "var(--mint)", flexShrink: 0 }}
                    />
                    <span className="ftype">{FILE_ICONS[d.file_type] || "DOC"}</span>
                    <span
                      className="fname"
                      style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: "0.8125rem",
                        color: "var(--navy)",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        flex: 1,
                        minWidth: 0,
                      }}
                      title={d.filename}
                    >
                      {d.filename}
                    </span>
                  </label>
                ))}

                {selectedIds.size === 0 && docs.length > 0 && (
                  <p style={{ fontSize: "0.75rem", color: "var(--slate-2)", padding: "4px 8px", marginTop: 4 }}>
                    None selected — searches all
                  </p>
                )}
              </div>
            </div>
          </aside>

          {/* RIGHT: Main panel */}
          <main style={{ display: "flex", flexDirection: "column", gap: 20, minWidth: 0 }}>
            {/* Ask card */}
            <div className="card ask-card">
              <div className="card-pad">
                <textarea
                  ref={textareaRef}
                  className="input"
                  value={question}
                  onChange={e => setQuestion(e.target.value)}
                  onKeyDown={handleKeyDown}
                  rows={4}
                  placeholder="Ask a question… (Ctrl+Enter to submit)"
                  style={{ marginBottom: 12 }}
                />

                {/* Suggested queries */}
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 14 }}>
                  {SUGGESTED_QUERIES.map(q => (
                    <button
                      key={q}
                      onClick={() => setQuestion(q)}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        fontSize: "0.8125rem",
                        fontWeight: 500,
                        color: "var(--teal-link)",
                        background: "var(--mint-soft)",
                        border: "1px solid var(--line)",
                        borderRadius: "var(--r-full)",
                        padding: "4px 12px",
                        cursor: "pointer",
                        transition: "background var(--t-fast)",
                        fontFamily: "var(--font-body)",
                      }}
                    >
                      {q}
                    </button>
                  ))}
                </div>

                <div className="ask-row" style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                  {error && (
                    <span style={{ color: "var(--err-fg)", fontSize: "0.875rem", flex: 1 }}>
                      {error}{" "}
                      <button
                        onClick={submit}
                        style={{ color: "var(--teal-link)", fontWeight: 600, background: "none", border: "none", cursor: "pointer", fontSize: "0.875rem" }}
                      >
                        Retry
                      </button>
                    </span>
                  )}

                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginLeft: "auto" }}>
                    <label
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                        fontSize: "0.8375rem",
                        fontWeight: 500,
                        color: "var(--slate)",
                        cursor: "pointer",
                        userSelect: "none",
                        whiteSpace: "nowrap",
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={streamMode}
                        onChange={e => setStreamMode(e.target.checked)}
                        style={{ accentColor: "var(--mint)" }}
                      />
                      Stream
                    </label>

                    <button
                      className="btn btn-mint"
                      onClick={submit}
                      disabled={loading || !question.trim()}
                    >
                      {loading && (
                        <span
                          style={{
                            display: "inline-block",
                            width: 14,
                            height: 14,
                            border: "2px solid var(--forest)",
                            borderTopColor: "transparent",
                            borderRadius: "50%",
                            animation: "spin 0.7s linear infinite",
                          }}
                        />
                      )}
                      {loading ? (streaming ? "Streaming…" : "Searching…") : "Search"}
                    </button>
                  </div>
                </div>
              </div>
            </div>

            {/* Answer card */}
            {(displayAnswer || result) && (
              <div className="card card-pad" style={{ animation: "fadeIn 200ms ease both" }}>
                {/* Answer meta row */}
                <div
                  className="a-meta"
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    marginBottom: 14,
                  }}
                >
                  <span
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: "50%",
                      background: result
                        ? result.confidence_gate_passed ? "var(--ok-fg)" : "var(--warn-fg)"
                        : "var(--slate-2)",
                      flexShrink: 0,
                    }}
                  />
                  <span style={{ fontSize: "0.8125rem", fontWeight: 700, color: "var(--slate-2)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
                    Answer
                  </span>
                  <div style={{ flex: 1 }} />
                  {result && (
                    <button
                      onClick={copyAnswer}
                      title="Copy answer"
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 5,
                        fontSize: "0.8125rem",
                        fontWeight: 600,
                        color: copied ? "var(--ok-fg)" : "var(--slate-2)",
                        background: "none",
                        border: "none",
                        cursor: "pointer",
                        padding: "4px 8px",
                        borderRadius: "var(--r-sm)",
                        transition: "color var(--t-fast)",
                      }}
                    >
                      {copied ? (
                        <>
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
                            <path d="M20 6L9 17l-5-5" />
                          </svg>
                          Copied
                        </>
                      ) : (
                        <>
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                            <rect x="9" y="9" width="13" height="13" rx="2" />
                            <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
                          </svg>
                          Copy
                        </>
                      )}
                    </button>
                  )}
                </div>

                {/* Confidence warning banner */}
                {result && !result.confidence_gate_passed && (
                  <div
                    style={{
                      background: "var(--warn-bg)",
                      color: "var(--warn-fg)",
                      border: "1px solid var(--warn-fg)",
                      borderRadius: "var(--r-md)",
                      padding: "10px 14px",
                      fontSize: "0.875rem",
                      fontWeight: 500,
                      marginBottom: 14,
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                    }}
                  >
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                      <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                      <line x1="12" y1="9" x2="12" y2="13" />
                      <line x1="12" y1="17" x2="12.01" y2="17" />
                    </svg>
                    Low confidence — answer may be unreliable. Consider refining your question.
                  </div>
                )}

                {/* Answer text */}
                <p
                  style={{
                    color: "var(--navy)",
                    lineHeight: 1.75,
                    fontSize: "0.9375rem",
                    marginBottom: result ? 20 : 0,
                  }}
                >
                  {result
                    ? renderAnswer(result.answer)
                    : <>{streamingText}<span style={{ animation: "pulse 1s ease infinite", opacity: 0.7 }}>▌</span></>
                  }
                </p>

                {/* RAGAS scores */}
                {result && result.ragas_scores && Object.keys(result.ragas_scores).length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 16 }}>
                    {Object.entries(result.ragas_scores).map(([k, v]) => (
                      <span key={k} className={ragasBadgeClass(v, k === "faithfulness")}>
                        {k.replace(/_/g, " ")}: {v.toFixed(2)}
                      </span>
                    ))}
                  </div>
                )}

                {result && !(result.ragas_scores && Object.keys(result.ragas_scores).length > 0) && (
                  <div style={{ marginBottom: 16 }}>
                    <span className="badge badge-neutral is-processing">Evaluating quality scores…</span>
                  </div>
                )}

                {/* Token / latency metadata */}
                {result && (result.prompt_tokens || result.latency_ms) && (
                  <div
                    style={{
                      display: "flex",
                      gap: 16,
                      flexWrap: "wrap",
                      fontSize: "0.8125rem",
                      fontFamily: "var(--font-mono)",
                      color: "var(--slate-2)",
                      borderTop: "1px solid var(--line-2)",
                      paddingTop: 12,
                      marginBottom: result.citations?.length > 0 ? 20 : 0,
                    }}
                  >
                    {result.prompt_tokens && <span>prompt: {result.prompt_tokens} tok</span>}
                    {result.completion_tokens && <span>completion: {result.completion_tokens} tok</span>}
                    {result.latency_ms && <span>latency: {result.latency_ms}ms</span>}
                  </div>
                )}

                {/* Sources section */}
                {result && result.citations?.length > 0 && (
                  <div className="sources" style={{ borderTop: "1px solid var(--line)", paddingTop: 18 }}>
                    <h4
                      style={{
                        fontSize: "0.8375rem",
                        fontWeight: 700,
                        color: "var(--slate)",
                        textTransform: "uppercase",
                        letterSpacing: "0.07em",
                        marginBottom: 14,
                      }}
                    >
                      Sources &middot; {result.citations.length} chunk{result.citations.length !== 1 ? "s" : ""}
                    </h4>
                    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                      {result.citations.map((c, i) => (
                        <div
                          id={`cite-${i + 1}`}
                          key={i}
                          className="src"
                          style={{
                            display: "flex",
                            gap: 12,
                            padding: "12px 14px",
                            background: "var(--tile)",
                            border: "1px solid var(--line)",
                            borderRadius: "var(--r-md)",
                            borderLeft: "3px solid var(--mint)",
                          }}
                        >
                          <span
                            style={{
                              flexShrink: 0,
                              width: 22,
                              height: 22,
                              borderRadius: "var(--r-full)",
                              background: "var(--mint-soft)",
                              color: "var(--ok-fg)",
                              fontSize: "0.75rem",
                              fontWeight: 700,
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "center",
                              marginTop: 1,
                            }}
                          >
                            {i + 1}
                          </span>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div
                              style={{
                                fontFamily: "var(--font-mono)",
                                fontWeight: 600,
                                fontSize: "0.8375rem",
                                color: "var(--navy)",
                                marginBottom: 4,
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                whiteSpace: "nowrap",
                              }}
                            >
                              {c.source || c.filename || "unknown"}
                              {(c.page || c.page_or_segment) && (
                                <span style={{ fontWeight: 400, color: "var(--slate-2)", marginLeft: 6 }}>
                                  — {c.page || c.page_or_segment}
                                </span>
                              )}
                            </div>
                            {c.excerpt && (
                              <p
                                style={{
                                  fontSize: "0.8375rem",
                                  color: "var(--slate)",
                                  lineHeight: 1.55,
                                  display: "-webkit-box",
                                  WebkitLineClamp: 3,
                                  WebkitBoxOrient: "vertical",
                                  overflow: "hidden",
                                }}
                              >
                                {c.excerpt}
                              </p>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Query history */}
            {queryHistory.length > 0 && (
              <div className="card card-pad">
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    marginBottom: 14,
                  }}
                >
                  <h4
                    style={{
                      fontSize: "0.8375rem",
                      fontWeight: 700,
                      color: "var(--slate-2)",
                      textTransform: "uppercase",
                      letterSpacing: "0.07em",
                    }}
                  >
                    Recent Queries
                  </h4>
                  <span
                    className="badge badge-neutral"
                    style={{ fontFamily: "var(--font-mono)" }}
                  >
                    {queryHistory.length}
                  </span>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {queryHistory.map((h, i) => (
                    <button
                      key={i}
                      onClick={() => { setQuestion(h.question); setResult(h.result); }}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                        padding: "9px 12px",
                        borderRadius: "var(--r-md)",
                        background: "transparent",
                        border: "1px solid var(--line-2)",
                        cursor: "pointer",
                        textAlign: "left",
                        fontFamily: "var(--font-body)",
                        transition: "background var(--t-fast), border-color var(--t-fast)",
                        width: "100%",
                      }}
                      onMouseEnter={e => {
                        e.currentTarget.style.background = "var(--tile)";
                        e.currentTarget.style.borderColor = "var(--line)";
                      }}
                      onMouseLeave={e => {
                        e.currentTarget.style.background = "transparent";
                        e.currentTarget.style.borderColor = "var(--line-2)";
                      }}
                    >
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--slate-2)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                        <circle cx="11" cy="11" r="8" />
                        <path d="m21 21-4.35-4.35" />
                      </svg>
                      <span
                        style={{
                          fontSize: "0.875rem",
                          color: "var(--navy)",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                          flex: 1,
                        }}
                      >
                        {h.question}
                      </span>
                      <span
                        className={`badge ${h.result.confidence_gate_passed ? "badge-ok" : "badge-warn"}`}
                        style={{ fontSize: "0.6875rem", flexShrink: 0 }}
                      >
                        {h.result.confidence_gate_passed ? "High" : "Low"}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}
