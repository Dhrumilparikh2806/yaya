import { useState, useRef, useEffect } from "react";
import NavBar from "../components/NavBar";
import api from "../api/client";

interface Message {
  role: "user" | "agent";
  text: string;
  toolNames?: string[];
  promptTokens?: number;
  completionTokens?: number;
}

const SESSION_KEY = "agent_session_id";

const CHIPS = ["List my documents", "Ingest a file", "Summarize the Q3 audit"];

const CAP_CARDS = [
  {
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
      </svg>
    ),
    title: "Search & retrieve",
    desc: "Semantic search across all ingested documents",
  },
  {
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>
      </svg>
    ),
    title: "Ingest documents",
    desc: "Upload and index PDFs, DOCX, and text files",
  },
  {
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/>
      </svg>
    ),
    title: "Analyze & compare",
    desc: "Cross-document analysis and structured summaries",
  },
];

function renderContent(text: string) {
  const lines = text.split("\n");
  return lines.map((line, i) => {
    const parts = line.split(/(\*\*[^*]+\*\*|`[^`]+`|\[\d+\])/g);
    return (
      <span key={i}>
        {parts.map((p, j) => {
          if (/^\*\*(.+)\*\*$/.test(p))
            return <strong key={j}>{p.slice(2, -2)}</strong>;
          if (/^`(.+)`$/.test(p))
            return (
              <code
                key={j}
                style={{
                  fontFamily: "var(--font-mono, 'JetBrains Mono', monospace)",
                  fontSize: "0.82em",
                  background: "var(--tile)",
                  borderRadius: 4,
                  padding: "1px 5px",
                  color: "var(--forest)",
                }}
              >
                {p.slice(1, -1)}
              </code>
            );
          if (/^\[\d+\]$/.test(p))
            return (
              <sup
                key={j}
                style={{ color: "var(--teal-link)", fontWeight: 600, fontSize: "0.78em" }}
              >
                {p}
              </sup>
            );
          return <span key={j}>{p}</span>;
        })}
        {i < lines.length - 1 && <br />}
      </span>
    );
  });
}

export default function AgentPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | undefined>(
    () => localStorage.getItem(SESSION_KEY) || undefined
  );
  const [toolCalls, setToolCalls] = useState<string[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  useEffect(() => {
    if (sessionId) localStorage.setItem(SESSION_KEY, sessionId);
  }, [sessionId]);

  const send = async (text?: string) => {
    const msg = (text ?? input).trim();
    if (!msg || loading) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", text: msg }]);
    setLoading(true);

    try {
      const r = await api.post("/v1/agent/chat", {
        message: msg,
        session_id: sessionId,
      });
      const {
        response,
        tool_calls_made,
        session_id: sid,
        prompt_tokens,
        completion_tokens,
      } = r.data;

      setSessionId(sid);

      if (tool_calls_made?.length) {
        setToolCalls((prev) => [...prev, ...(tool_calls_made as string[])]);
      }

      setMessages((prev) => [
        ...prev,
        {
          role: "agent",
          text: response || "(no response)",
          toolNames: tool_calls_made,
          promptTokens: prompt_tokens,
          completionTokens: completion_tokens,
        },
      ]);
    } catch (e: unknown) {
      const err = e as {
        response?: { data?: { detail?: string } };
        message?: string;
      };
      setMessages((prev) => [
        ...prev,
        {
          role: "agent",
          text: `Error: ${err.response?.data?.detail ?? err.message ?? "unknown error"}`,
        },
      ]);
    } finally {
      setLoading(false);
      textareaRef.current?.focus();
    }
  };

  const clear = () => {
    if (sessionId) {
      api.delete(`/v1/agent/session/${sessionId}`).catch(() => {});
    }
    setMessages([]);
    setToolCalls([]);
    setSessionId(undefined);
    localStorage.removeItem(SESSION_KEY);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  const isEmpty = messages.length === 0;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        overflow: "hidden",
        background: "var(--bg)",
      }}
    >
      <NavBar />

      {/* agent-shell: sidebar + chat */}
      <div
        className="agent-shell"
        style={{
          flex: 1,
          display: "grid",
          gridTemplateColumns: "280px 1fr",
          overflow: "hidden",
          minHeight: 0,
        }}
      >
        {/* ── Sidebar: Tool calls ── */}
        <aside
          className="tools"
          style={{
            borderRight: "1px solid var(--line)",
            background: "var(--card)",
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
          }}
        >
          {/* tools-head */}
          <div
            className="tools-head"
            style={{
              padding: "14px 16px",
              borderBottom: "1px solid var(--line-2)",
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            <h3
              style={{
                margin: 0,
                fontSize: 13,
                fontWeight: 600,
                color: "var(--ink)",
                flex: 1,
              }}
            >
              Tool calls
            </h3>
            <span
              className="count badge badge-neutral"
              style={{ fontSize: 11, minWidth: 22, textAlign: "center" }}
            >
              {toolCalls.length}
            </span>
          </div>

          {/* tools-body */}
          <div
            className="tools-body"
            style={{
              flex: 1,
              overflowY: "auto",
              padding: "12px 12px 8px",
              display: "flex",
              flexDirection: "column",
              gap: 6,
            }}
          >
            {toolCalls.length === 0 ? (
              <p
                style={{
                  textAlign: "center",
                  marginTop: 24,
                  fontSize: 12,
                  color: "var(--slate-2)",
                }}
              >
                No tool calls yet
              </p>
            ) : (
              toolCalls.map((name, i) => (
                <div
                  key={i}
                  className="tool-call"
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "7px 10px",
                    borderRadius: 8,
                    background: "var(--tile)",
                    border: "1px solid var(--line-2)",
                  }}
                >
                  <span
                    className="tname"
                    style={{
                      fontFamily: "var(--font-mono, 'JetBrains Mono', monospace)",
                      fontSize: 11,
                      color: "var(--mint-700)",
                      flex: 1,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {name}
                  </span>
                  <span className="badge badge-ok" style={{ fontSize: 10 }}>
                    called
                  </span>
                </div>
              ))
            )}
          </div>

          {/* tools-foot */}
          <div
            className="tools-foot"
            style={{
              padding: "10px 14px",
              borderTop: "1px solid var(--line-2)",
            }}
          >
            <p style={{ margin: 0, fontSize: 11, color: "var(--slate-2)", marginBottom: 2 }}>
              Upload dir
            </p>
            <p
              className="dir"
              style={{
                margin: 0,
                fontFamily: "var(--font-mono, 'JetBrains Mono', monospace)",
                fontSize: 10,
                color: "var(--slate)",
                wordBreak: "break-all",
              }}
            >
              /tmp/geminirag_uploads
            </p>
          </div>
        </aside>

        {/* ── Chat panel ── */}
        <section
          className="chat"
          style={{
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
            minHeight: 0,
          }}
        >
          {/* chat-head */}
          <div
            className="chat-head"
            style={{
              padding: "13px 20px",
              borderBottom: "1px solid var(--line)",
              background: "var(--card)",
              display: "flex",
              alignItems: "center",
              gap: 12,
            }}
          >
            <h2
              style={{
                margin: 0,
                fontSize: 15,
                fontWeight: 600,
                color: "var(--ink)",
                flex: 1,
              }}
            >
              Agent Chat
            </h2>
            <button className="btn btn-ghost btn-sm" onClick={clear}>
              Clear
            </button>
          </div>

          {/* chat-body */}
          <div
            className="chat-body"
            style={{
              flex: 1,
              overflowY: "auto",
              padding: "20px",
              display: "flex",
              flexDirection: "column",
              gap: 14,
            }}
          >
            {isEmpty ? (
              /* Empty state */
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  paddingTop: 40,
                  gap: 16,
                }}
              >
                {/* Bot avatar */}
                <div
                  className="av"
                  style={{
                    width: 52,
                    height: 52,
                    borderRadius: "50%",
                    background: "var(--forest)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 24,
                    flexShrink: 0,
                  }}
                >
                  🤖
                </div>

                <p
                  style={{
                    margin: 0,
                    fontSize: 15,
                    color: "var(--slate)",
                    fontWeight: 500,
                    textAlign: "center",
                  }}
                >
                  Ask me anything about your documents
                </p>

                {/* Chip prompts */}
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center" }}>
                  {CHIPS.map((c) => (
                    <button
                      key={c}
                      onClick={() => send(c)}
                      style={{
                        padding: "6px 14px",
                        borderRadius: 999,
                        border: "1px solid var(--line)",
                        background: "var(--card)",
                        color: "var(--slate)",
                        fontSize: 12,
                        cursor: "pointer",
                        fontFamily: "inherit",
                        transition: "border-color 0.15s, color 0.15s",
                      }}
                      onMouseEnter={(e) => {
                        (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--mint)";
                        (e.currentTarget as HTMLButtonElement).style.color = "var(--forest)";
                      }}
                      onMouseLeave={(e) => {
                        (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--line)";
                        (e.currentTarget as HTMLButtonElement).style.color = "var(--slate)";
                      }}
                    >
                      {c}
                    </button>
                  ))}
                </div>

                {/* Capability grid */}
                <div
                  className="cap-grid"
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(3, 1fr)",
                    gap: 12,
                    marginTop: 8,
                    width: "100%",
                    maxWidth: 580,
                  }}
                >
                  {CAP_CARDS.map((cap) => (
                    <div
                      key={cap.title}
                      className="cap card card-pad"
                      style={{
                        display: "flex",
                        flexDirection: "column",
                        gap: 8,
                        padding: "16px 14px",
                        borderRadius: 10,
                        background: "var(--tile)",
                        border: "1px solid var(--line-2)",
                      }}
                    >
                      <span style={{ color: "var(--forest)" }}>{cap.icon}</span>
                      <p
                        style={{
                          margin: 0,
                          fontSize: 12,
                          fontWeight: 600,
                          color: "var(--ink)",
                        }}
                      >
                        {cap.title}
                      </p>
                      <p
                        style={{
                          margin: 0,
                          fontSize: 11,
                          color: "var(--slate-2)",
                          lineHeight: 1.4,
                        }}
                      >
                        {cap.desc}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              /* Message list */
              <>
                {messages.map((m, i) => (
                  <div
                    key={i}
                    className={`msg ${m.role === "user" ? "user" : "bot"}`}
                    style={{
                      display: "flex",
                      flexDirection: m.role === "user" ? "row-reverse" : "row",
                      alignItems: "flex-end",
                      gap: 8,
                    }}
                  >
                    {/* Avatar */}
                    <div
                      className="av"
                      style={{
                        width: 32,
                        height: 32,
                        borderRadius: "50%",
                        flexShrink: 0,
                        background:
                          m.role === "user" ? "var(--forest)" : "var(--mint-soft)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontSize: 14,
                      }}
                    >
                      {m.role === "user" ? "👤" : "🤖"}
                    </div>

                    <div style={{ maxWidth: "68%", display: "flex", flexDirection: "column", gap: 4 }}>
                      {/* Bubble */}
                      <div
                        className="bubble"
                        style={{
                          padding: "10px 14px",
                          borderRadius:
                            m.role === "user"
                              ? "14px 14px 4px 14px"
                              : "14px 14px 14px 4px",
                          background:
                            m.role === "user" ? "var(--forest)" : "var(--card)",
                          color:
                            m.role === "user" ? "#fff" : "var(--ink)",
                          fontSize: 13,
                          lineHeight: 1.55,
                          border:
                            m.role === "agent"
                              ? "1px solid var(--line)"
                              : "none",
                          boxShadow:
                            m.role === "agent"
                              ? "0 1px 3px rgba(4,9,26,0.05)"
                              : "none",
                        }}
                      >
                        {m.role === "agent" ? renderContent(m.text) : m.text}
                      </div>

                      {/* Token metadata */}
                      {m.role === "agent" &&
                        (m.promptTokens || m.completionTokens) ? (
                        <p
                          style={{
                            margin: 0,
                            fontSize: 10,
                            color: "var(--slate-2)",
                            paddingLeft: 2,
                          }}
                        >
                          {m.promptTokens ? `prompt: ${m.promptTokens} tok` : ""}
                          {m.promptTokens && m.completionTokens ? " · " : ""}
                          {m.completionTokens
                            ? `completion: ${m.completionTokens} tok`
                            : ""}
                        </p>
                      ) : null}
                    </div>
                  </div>
                ))}

                {/* Typing indicator */}
                {loading && (
                  <div
                    className="msg bot"
                    style={{
                      display: "flex",
                      alignItems: "flex-end",
                      gap: 8,
                    }}
                  >
                    <div
                      className="av"
                      style={{
                        width: 32,
                        height: 32,
                        borderRadius: "50%",
                        flexShrink: 0,
                        background: "var(--mint-soft)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontSize: 14,
                      }}
                    >
                      🤖
                    </div>
                    <div
                      className="bubble"
                      style={{
                        padding: "10px 16px",
                        borderRadius: "14px 14px 14px 4px",
                        background: "var(--card)",
                        border: "1px solid var(--line)",
                        boxShadow: "0 1px 3px rgba(4,9,26,0.05)",
                        display: "flex",
                        alignItems: "center",
                        gap: 5,
                      }}
                    >
                      {[0, 1, 2].map((n) => (
                        <span
                          key={n}
                          style={{
                            width: 7,
                            height: 7,
                            borderRadius: "50%",
                            background: "var(--mint-700)",
                            display: "inline-block",
                            animation: "bounce 1.1s infinite",
                            animationDelay: `${n * 0.17}s`,
                          }}
                        />
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Composer */}
          <div
            className="composer"
            style={{
              borderTop: "1px solid var(--line)",
              background: "var(--card)",
              padding: "12px 16px",
            }}
          >
            <div
              className="composer-inner"
              style={{
                display: "flex",
                alignItems: "flex-end",
                gap: 10,
              }}
            >
              <textarea
                ref={textareaRef}
                className="input"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                rows={2}
                disabled={loading}
                placeholder="Message the agent… (Enter to send, Shift+Enter for newline)"
                style={{
                  flex: 1,
                  resize: "none",
                  borderRadius: 10,
                  padding: "9px 12px",
                  fontSize: 13,
                  lineHeight: 1.5,
                  fontFamily: "inherit",
                  minHeight: 54,
                  maxHeight: 160,
                  overflowY: "auto",
                }}
              />
              <button
                className="btn btn-mint"
                onClick={() => send()}
                disabled={loading || !input.trim()}
                style={{ alignSelf: "flex-end" }}
              >
                Send
              </button>
            </div>
          </div>
        </section>
      </div>

      {/* Bounce keyframes injected once */}
      <style>{`
        @keyframes bounce {
          0%, 80%, 100% { transform: translateY(0); opacity: 0.5; }
          40% { transform: translateY(-6px); opacity: 1; }
        }
      `}</style>
    </div>
  );
}
