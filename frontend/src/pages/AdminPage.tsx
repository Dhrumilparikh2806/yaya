import { useState, useEffect } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import NavBar from "../components/NavBar";
import api from "../api/client";
import { useAuth } from "../context/AuthContext";

type Tab = "usage" | "ragas" | "users";

interface UsageData {
  today_tokens?: number;
  avg_latency_ms?: number;
  total_calls?: number;
  daily?: Array<{ date: string; prompt_tokens: number; completion_tokens: number }>;
  by_endpoint?: Array<{ endpoint: string; calls: number; total_tokens: number; avg_latency_ms?: number }>;
  by_user?: Array<{ user_id: string; email: string | null; calls: number; total_tokens: number }>;
}

interface RagasData {
  averages?: Record<string, number | null>;
  by_day?: Array<Record<string, number | null | string>>;
  low_scoring?: Array<{
    question: string;
    answer?: string;
    faithfulness?: number;
    answer_relevancy?: number;
    created_at: string;
  }>;
}

interface UserRow {
  id: string;
  email: string;
  role: string;
  total_queries?: number;
  total_tokens?: number;
  last_active_at?: string;
  is_active: boolean;
}

interface LogEntry {
  endpoint: string;
  model: string;
  total_tokens: number;
  latency_ms: number;
}

const RAGAS_METRICS = [
  "faithfulness",
  "answer_relevancy",
  "context_precision",
  "context_recall",
  "answer_correctness",
];

const RAGAS_LINE_COLORS: Record<string, string> = {
  faithfulness: "#1FCB72",
  answer_relevancy: "#9A44DB",
  context_precision: "#0A6E63",
  context_recall: "#F59E0B",
};

function metricLabel(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function ScoreRing({ score, label }: { score: number | null | undefined; label: string }) {
  const pct = score != null ? Math.round(score * 100) : 0;
  const displayScore = score != null ? score.toFixed(2) : "—";

  const ringStyle: React.CSSProperties = {
    width: 54,
    height: 54,
    borderRadius: "50%",
    background:
      score != null
        ? `conic-gradient(var(--mint-700) ${pct}%, var(--line-2) 0)`
        : "var(--line-2)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
  };

  const innerStyle: React.CSSProperties = {
    width: 38,
    height: 38,
    borderRadius: "50%",
    background: "var(--card)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: "0.6875rem",
    fontWeight: 700,
    color: "var(--navy)",
    fontFamily: "var(--font-mono)",
    fontVariantNumeric: "tabular-nums",
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 10,
        background: "var(--card)",
        border: "1px solid var(--line)",
        borderRadius: "var(--r-lg)",
        padding: "18px 12px",
        boxShadow: "var(--shadow-sm)",
        flex: 1,
        minWidth: 110,
      }}
    >
      <div style={ringStyle}>
        <div style={innerStyle}>{displayScore}</div>
      </div>
      <span
        style={{
          fontSize: "0.75rem",
          fontWeight: 600,
          color: "var(--slate)",
          textAlign: "center",
          lineHeight: 1.3,
        }}
      >
        {metricLabel(label)}
      </span>
    </div>
  );
}

function PanelTitle({ children }: { children: React.ReactNode }) {
  return (
    <p
      style={{
        fontSize: "0.9375rem",
        fontWeight: 700,
        color: "var(--navy)",
        letterSpacing: "-0.01em",
        marginBottom: 14,
      }}
    >
      {children}
    </p>
  );
}

function Panel({
  children,
  style,
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
}) {
  return (
    <div
      className="card"
      style={{ padding: "20px 20px 4px", ...style }}
    >
      {children}
    </div>
  );
}

function SkeletonBlock() {
  return (
    <div
      style={{
        height: 72,
        background: "var(--line-2)",
        borderRadius: "var(--r-lg)",
        animation: "pulse 1.4s ease-in-out infinite",
      }}
    />
  );
}

export default function AdminPage() {
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>("usage");
  const [usage, setUsage] = useState<UsageData | null>(null);
  const [ragas, setRagas] = useState<RagasData | null>(null);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [sortKey, setSortKey] = useState("email");
  const [sortAsc, setSortAsc] = useState(true);

  useEffect(() => {
    if (tab === "usage" && !usage) {
      setLoading(true);
      Promise.all([api.get("/v1/admin/usage"), api.get("/v1/admin/logs?limit=20")])
        .then(([u, l]) => {
          setUsage(u.data);
          setLogs(l.data);
        })
        .finally(() => setLoading(false));
    }
    if (tab === "ragas" && !ragas) {
      setLoading(true);
      api
        .get("/v1/admin/ragas")
        .then((r) => setRagas(r.data))
        .finally(() => setLoading(false));
    }
    if (tab === "users" && users.length === 0) {
      setLoading(true);
      api
        .get("/v1/admin/users")
        .then((r) => setUsers(r.data))
        .finally(() => setLoading(false));
    }
  }, [tab]);

  const toggleUser = async (userId: string, currentActive: boolean) => {
    await api.patch(`/v1/admin/users/${userId}`, { is_active: !currentActive });
    setUsers((prev) =>
      prev.map((u) => (u.id === userId ? { ...u, is_active: !currentActive } : u))
    );
  };

  const sortUsers = (key: string) => {
    if (sortKey === key) setSortAsc((a) => !a);
    else {
      setSortKey(key);
      setSortAsc(true);
    }
  };

  const sortedUsers = [...users].sort((a, b) => {
    const aVal = a[sortKey as keyof UserRow] ?? "";
    const bVal = b[sortKey as keyof UserRow] ?? "";
    const cmp = String(aVal).localeCompare(String(bVal));
    return sortAsc ? cmp : -cmp;
  });

  const sortArrow = (key: string) => {
    if (sortKey !== key) return " ↕";
    return sortAsc ? " ↑" : " ↓";
  };

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)" }}>
      <NavBar />

      <div className="page">
        {/* Page header */}
        <div className="page-head">
          <h1 className="page-title">Admin Dashboard</h1>
        </div>

        {/* Tabs */}
        <div className="tabs">
          {(
            [
              ["usage", "Usage"],
              ["ragas", "RAGAS"],
              ["users", "Users"],
            ] as [Tab, string][]
          ).map(([t, label]) => (
            <a
              key={t}
              href="#"
              className={tab === t ? "active" : ""}
              onClick={(e) => {
                e.preventDefault();
                setTab(t);
              }}
            >
              {label}
            </a>
          ))}
        </div>

        {/* Loading skeleton */}
        {loading && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <SkeletonBlock />
            <SkeletonBlock />
            <SkeletonBlock />
          </div>
        )}

        {/* ── USAGE TAB ── */}
        {tab === "usage" && !loading && usage && (
          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

            {/* Stat cards */}
            <div className="stat-grid" style={{ gridTemplateColumns: "repeat(3,1fr)" }}>
              <StatCard
                label="Tokens Today"
                value={usage.today_tokens?.toLocaleString() ?? "—"}
              />
              <StatCard
                label="Avg Latency"
                value={
                  usage.avg_latency_ms != null
                    ? `${Math.round(usage.avg_latency_ms)} ms`
                    : "—"
                }
              />
              <StatCard
                label="Total API Calls"
                value={usage.total_calls?.toLocaleString() ?? "—"}
              />
            </div>

            {/* Token chart */}
            {usage.daily && usage.daily.length > 0 && (
              <Panel>
                <PanelTitle>Tokens per day</PanelTitle>
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={usage.daily} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
                    <XAxis
                      dataKey="date"
                      tick={{ fontSize: 11, fill: "var(--slate-2)" }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <YAxis
                      tick={{ fontSize: 11, fill: "var(--slate-2)" }}
                      axisLine={false}
                      tickLine={false}
                      width={48}
                    />
                    <Tooltip
                      contentStyle={{
                        background: "var(--card)",
                        border: "1px solid var(--line)",
                        borderRadius: 8,
                        fontSize: 12,
                      }}
                    />
                    <Legend
                      iconType="circle"
                      iconSize={8}
                      wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
                    />
                    <Line
                      type="monotone"
                      dataKey="prompt_tokens"
                      stroke="#9A44DB"
                      name="Prompt"
                      dot={false}
                      strokeWidth={2}
                    />
                    <Line
                      type="monotone"
                      dataKey="completion_tokens"
                      stroke="#1FCB72"
                      name="Completion"
                      dot={false}
                      strokeWidth={2}
                    />
                  </LineChart>
                </ResponsiveContainer>
                {/* Legend annotation */}
                <div
                  style={{
                    display: "flex",
                    gap: 20,
                    padding: "8px 0 12px",
                    fontSize: "0.8125rem",
                  }}
                >
                  <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span
                      style={{
                        width: 10,
                        height: 10,
                        borderRadius: "50%",
                        background: "#9A44DB",
                        display: "inline-block",
                        flexShrink: 0,
                      }}
                    />
                    <span style={{ color: "var(--slate)" }}>Prompt</span>
                  </span>
                  <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span
                      style={{
                        width: 10,
                        height: 10,
                        borderRadius: "50%",
                        background: "#1FCB72",
                        display: "inline-block",
                        flexShrink: 0,
                      }}
                    />
                    <span style={{ color: "var(--slate)" }}>Completion</span>
                  </span>
                </div>
              </Panel>
            )}

            {/* Top endpoints */}
            {usage.by_endpoint && usage.by_endpoint.length > 0 && (
              <Panel>
                <PanelTitle>Top Endpoints</PanelTitle>
                <div style={{ overflowX: "auto", marginBottom: 8 }}>
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Endpoint</th>
                        <th style={{ textAlign: "right" }}>Calls</th>
                        <th style={{ textAlign: "right" }}>Tokens</th>
                        <th style={{ textAlign: "right" }}>Avg Latency</th>
                      </tr>
                    </thead>
                    <tbody>
                      {usage.by_endpoint.map((e, i) => (
                        <tr key={i}>
                          <td>
                            <code
                              style={{
                                fontFamily: "var(--font-mono)",
                                fontSize: "0.8125rem",
                                background: "var(--tile)",
                                padding: "2px 6px",
                                borderRadius: 4,
                                border: "1px solid var(--line)",
                                color: "var(--navy)",
                              }}
                            >
                              {e.endpoint}
                            </code>
                          </td>
                          <td className="num" style={{ textAlign: "right" }}>
                            {e.calls.toLocaleString()}
                          </td>
                          <td className="num" style={{ textAlign: "right" }}>
                            {e.total_tokens?.toLocaleString() ?? "—"}
                          </td>
                          <td
                            className="num"
                            style={{ textAlign: "right", color: "var(--slate-2)" }}
                          >
                            {e.avg_latency_ms != null
                              ? `${Math.round(e.avg_latency_ms)} ms`
                              : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>
            )}

            {/* Per-user */}
            {usage.by_user && usage.by_user.length > 0 && (
              <Panel>
                <PanelTitle>Per User</PanelTitle>
                <div style={{ overflowX: "auto", marginBottom: 8 }}>
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Email</th>
                        <th style={{ textAlign: "right" }}>Calls</th>
                        <th style={{ textAlign: "right" }}>Tokens</th>
                      </tr>
                    </thead>
                    <tbody>
                      {usage.by_user.map((u, i) => (
                        <tr key={i}>
                          <td style={{ color: "var(--slate)" }}>
                            {u.email ?? u.user_id}
                          </td>
                          <td className="num" style={{ textAlign: "right" }}>
                            {u.calls.toLocaleString()}
                          </td>
                          <td className="num" style={{ textAlign: "right" }}>
                            {u.total_tokens?.toLocaleString() ?? "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>
            )}

            {/* Recent logs */}
            {logs.length > 0 && (
              <Panel>
                <PanelTitle>Recent Logs</PanelTitle>
                <div style={{ overflowX: "auto", marginBottom: 8 }}>
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Endpoint</th>
                        <th>Model</th>
                        <th style={{ textAlign: "right" }}>Tokens</th>
                        <th style={{ textAlign: "right" }}>Latency</th>
                      </tr>
                    </thead>
                    <tbody>
                      {logs.map((l, i) => (
                        <tr key={i}>
                          <td>
                            <code
                              style={{
                                fontFamily: "var(--font-mono)",
                                fontSize: "0.8125rem",
                                background: "var(--tile)",
                                padding: "2px 6px",
                                borderRadius: 4,
                                border: "1px solid var(--line)",
                                color: "var(--navy)",
                              }}
                            >
                              {l.endpoint}
                            </code>
                          </td>
                          <td style={{ color: "var(--slate-2)", fontSize: "0.8125rem" }}>
                            {l.model}
                          </td>
                          <td className="num" style={{ textAlign: "right" }}>
                            {l.total_tokens?.toLocaleString()}
                          </td>
                          <td
                            className="num"
                            style={{ textAlign: "right", color: "var(--slate-2)" }}
                          >
                            {l.latency_ms} ms
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>
            )}
          </div>
        )}

        {/* ── RAGAS TAB ── */}
        {tab === "ragas" && !loading && ragas && (
          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

            {/* Metric rings */}
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: 12,
              }}
            >
              {RAGAS_METRICS.map((key) => (
                <ScoreRing
                  key={key}
                  score={ragas.averages?.[key] as number | null | undefined}
                  label={key}
                />
              ))}
            </div>

            {/* RAGAS trend chart */}
            {ragas.by_day && ragas.by_day.length > 0 && (
              <Panel>
                <PanelTitle>RAGAS Scores over Time</PanelTitle>
                <ResponsiveContainer width="100%" height={240}>
                  <LineChart
                    data={ragas.by_day}
                    margin={{ top: 4, right: 8, left: 0, bottom: 4 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
                    <XAxis
                      dataKey="date"
                      tick={{ fontSize: 11, fill: "var(--slate-2)" }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <YAxis
                      domain={[0, 1]}
                      tick={{ fontSize: 11, fill: "var(--slate-2)" }}
                      axisLine={false}
                      tickLine={false}
                      width={36}
                    />
                    <Tooltip
                      contentStyle={{
                        background: "var(--card)",
                        border: "1px solid var(--line)",
                        borderRadius: 8,
                        fontSize: 12,
                      }}
                    />
                    <Legend
                      iconType="circle"
                      iconSize={8}
                      wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
                    />
                    {Object.entries(RAGAS_LINE_COLORS).map(([key, color]) => (
                      <Line
                        key={key}
                        type="monotone"
                        dataKey={key}
                        stroke={color}
                        name={metricLabel(key)}
                        dot={false}
                        strokeWidth={2}
                        connectNulls
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </Panel>
            )}

            {/* Low-scoring queries */}
            {ragas.low_scoring && ragas.low_scoring.length > 0 && (
              <Panel>
                <PanelTitle>Low-scoring Queries (faithfulness &lt; 0.8)</PanelTitle>
                <div style={{ overflowX: "auto", marginBottom: 8 }}>
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Question</th>
                        <th>Answer preview</th>
                        <th style={{ textAlign: "right" }}>Faith.</th>
                        <th style={{ textAlign: "right" }}>Relevancy</th>
                        <th>Date</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ragas.low_scoring.map((r, i) => (
                        <tr key={i}>
                          <td
                            style={{
                              maxWidth: 240,
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                            }}
                          >
                            {r.question}
                          </td>
                          <td
                            style={{
                              maxWidth: 200,
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                              color: "var(--slate-2)",
                              fontSize: "0.8125rem",
                            }}
                          >
                            {r.answer ?? "—"}
                          </td>
                          <td
                            className="num"
                            style={{
                              textAlign: "right",
                              color: scoreColor(r.faithfulness ?? 0, true),
                            }}
                          >
                            {r.faithfulness?.toFixed(2) ?? "—"}
                          </td>
                          <td
                            className="num"
                            style={{
                              textAlign: "right",
                              color: scoreColor(r.answer_relevancy ?? 0),
                            }}
                          >
                            {r.answer_relevancy?.toFixed(2) ?? "—"}
                          </td>
                          <td
                            style={{
                              fontSize: "0.75rem",
                              color: "var(--slate-2)",
                              whiteSpace: "nowrap",
                            }}
                          >
                            {new Date(r.created_at).toLocaleDateString()}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>
            )}
          </div>
        )}

        {/* ── USERS TAB ── */}
        {tab === "users" && !loading && (
          <Panel style={{ padding: "0" }}>
            <div style={{ overflowX: "auto" }}>
              <table className="tbl">
                <thead>
                  <tr>
                    {(
                      [
                        ["email", "Email"],
                        ["role", "Role"],
                        ["total_queries", "Queries"],
                        ["total_tokens", "Tokens"],
                        ["last_active_at", "Last Active"],
                      ] as [string, string][]
                    ).map(([key, label]) => (
                      <th
                        key={key}
                        onClick={() => sortUsers(key)}
                        style={{ cursor: "pointer", userSelect: "none" }}
                      >
                        {label}
                        <span style={{ color: "var(--mint-700)", fontWeight: 700 }}>
                          {sortArrow(key)}
                        </span>
                      </th>
                    ))}
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedUsers.map((u) => {
                    const isSelf = u.id === user?.id;
                    return (
                      <tr key={u.id}>
                        <td style={{ fontWeight: 500 }}>{u.email}</td>
                        <td>
                          <span
                            className={`badge ${u.role === "admin" ? "badge-role" : "badge-neutral"}`}
                            style={
                              u.role === "admin"
                                ? {
                                    background: "rgba(154,68,219,0.12)",
                                    color: "#9A44DB",
                                    border: "1px solid rgba(154,68,219,0.25)",
                                  }
                                : {}
                            }
                          >
                            {u.role}
                          </span>
                        </td>
                        <td className="num">{u.total_queries ?? 0}</td>
                        <td className="num">{u.total_tokens?.toLocaleString() ?? 0}</td>
                        <td>
                          {u.last_active_at ? (
                            <span style={{ fontSize: "0.8125rem", color: "var(--slate)" }}>
                              {new Date(u.last_active_at).toLocaleString()}
                            </span>
                          ) : (
                            <span
                              style={{
                                fontSize: "0.8125rem",
                                color: "var(--slate-2)",
                                fontStyle: "italic",
                              }}
                            >
                              Never
                            </span>
                          )}
                        </td>
                        <td>
                          {isSelf ? (
                            <span
                              className="badge badge-ok"
                              style={{ opacity: 0.7, cursor: "default" }}
                            >
                              Active (you)
                            </span>
                          ) : (
                            <button
                              onClick={() => toggleUser(u.id, u.is_active)}
                              className={`badge btn ${u.is_active ? "badge-ok" : "badge-err"}`}
                              style={{
                                border: "none",
                                cursor: "pointer",
                                transition: "opacity var(--t-fast)",
                              }}
                              title={
                                u.is_active
                                  ? "Click to deactivate"
                                  : "Click to activate"
                              }
                            >
                              {u.is_active ? "Active" : "Inactive"}
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                  {sortedUsers.length === 0 && (
                    <tr>
                      <td
                        colSpan={6}
                        style={{
                          textAlign: "center",
                          padding: "36px 16px",
                          color: "var(--slate-2)",
                        }}
                      >
                        No users found.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Panel>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat-card">
      <span className="head">{label}</span>
      <span className="v">{value}</span>
    </div>
  );
}

function scoreColor(v: number, isFaith = false): string {
  const hi = isFaith ? 0.8 : 0.7;
  const mid = isFaith ? 0.7 : 0.5;
  if (v >= hi) return "var(--ok-fg)";
  if (v >= mid) return "var(--warn-fg)";
  return "var(--err-fg)";
}
