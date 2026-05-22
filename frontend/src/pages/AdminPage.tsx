import { useState, useEffect } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
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

function scoreColor(v: number, isFaith = false): string {
  const hi = isFaith ? 0.8 : 0.7; const mid = isFaith ? 0.7 : 0.5;
  if (v >= hi) return "text-green-600"; if (v >= mid) return "text-amber-500"; return "text-red-600";
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
        .then(([u, l]) => { setUsage(u.data); setLogs(l.data); }).finally(() => setLoading(false));
    }
    if (tab === "ragas" && !ragas) {
      setLoading(true);
      api.get("/v1/admin/ragas").then(r => setRagas(r.data)).finally(() => setLoading(false));
    }
    if (tab === "users" && users.length === 0) {
      setLoading(true);
      api.get("/v1/admin/users").then(r => setUsers(r.data)).finally(() => setLoading(false));
    }
  }, [tab]);

  const toggleUser = async (userId: string, currentActive: boolean) => {
    await api.patch(`/v1/admin/users/${userId}`, { is_active: !currentActive });
    setUsers(prev => prev.map(u => u.id === userId ? { ...u, is_active: !currentActive } : u));
  };

  const sortUsers = (key: string) => {
    if (sortKey === key) setSortAsc(a => !a); else { setSortKey(key); setSortAsc(true); }
  };
  const sortedUsers = [...users].sort((a, b) => {
    const aVal = a[sortKey as keyof UserRow] ?? "";
    const bVal = b[sortKey as keyof UserRow] ?? "";
    const cmp = String(aVal).localeCompare(String(bVal));
    return sortAsc ? cmp : -cmp;
  });

  const TabBtn = ({ t, label }: { t: Tab; label: string }) => (
    <button onClick={() => setTab(t)}
      className={`px-4 py-2 text-sm font-medium rounded-t-lg border-b-2 ${tab === t ? "border-indigo-600 text-indigo-600" : "border-transparent text-gray-500 hover:text-gray-700"}`}>
      {label}
    </button>
  );

  const RAGAS_METRICS = ["faithfulness", "answer_relevancy", "context_precision", "context_recall", "answer_correctness"];
  const RAGAS_COLORS = ["#6366f1", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"];

  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar />
      <div className="max-w-6xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold text-gray-800 mb-4">Admin Dashboard</h1>
        <div className="flex gap-1 border-b mb-6">
          <TabBtn t="usage" label="Usage" />
          <TabBtn t="ragas" label="RAGAS" />
          <TabBtn t="users" label="Users" />
        </div>

        {loading && <div className="space-y-3">{[...Array(3)].map((_, i) => <div key={i} className="h-20 bg-gray-200 animate-pulse rounded-xl" />)}</div>}

        {/* ── Usage Tab ── */}
        {tab === "usage" && usage && (
          <div className="space-y-6">
            <div className="grid grid-cols-3 gap-4">
              <Card label="Tokens today" value={usage.today_tokens?.toLocaleString() ?? "—"} />
              <Card label="Avg latency" value={usage.avg_latency_ms != null ? `${Math.round(usage.avg_latency_ms)}ms` : "—"} />
              <Card label="Total API calls" value={usage.total_calls?.toLocaleString() ?? "—"} />
            </div>

            {usage.daily && usage.daily.length > 0 && (
              <div className="bg-white rounded-xl border p-4">
                <h2 className="text-sm font-semibold text-gray-600 mb-3">Tokens per day (7d)</h2>
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={usage.daily}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip />
                    <Legend />
                    <Line type="monotone" dataKey="prompt_tokens" stroke="#6366f1" name="Prompt" dot={false} />
                    <Line type="monotone" dataKey="completion_tokens" stroke="#10b981" name="Completion" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}

            {usage.by_endpoint && usage.by_endpoint.length > 0 && (
              <div className="bg-white rounded-xl border overflow-hidden">
                <h2 className="text-sm font-semibold text-gray-600 px-4 pt-4 pb-2">Top endpoints</h2>
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b">
                    <tr>
                      <th className="text-left px-4 py-2 text-xs text-gray-500">Endpoint</th>
                      <th className="text-right px-4 py-2 text-xs text-gray-500">Calls</th>
                      <th className="text-right px-4 py-2 text-xs text-gray-500">Tokens</th>
                      <th className="text-right px-4 py-2 text-xs text-gray-500">Avg Latency</th>
                    </tr>
                  </thead>
                  <tbody>
                    {usage.by_endpoint.map((e, i) => (
                      <tr key={i} className="border-b hover:bg-gray-50">
                        <td className="px-4 py-2 text-gray-700">{e.endpoint}</td>
                        <td className="px-4 py-2 text-right text-gray-500">{e.calls}</td>
                        <td className="px-4 py-2 text-right text-gray-500">{e.total_tokens?.toLocaleString()}</td>
                        <td className="px-4 py-2 text-right text-gray-500">{e.avg_latency_ms != null ? `${Math.round(e.avg_latency_ms)}ms` : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {usage.by_user && usage.by_user.length > 0 && (
              <div className="bg-white rounded-xl border overflow-hidden">
                <h2 className="text-sm font-semibold text-gray-600 px-4 pt-4 pb-2">Per user</h2>
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b">
                    <tr>
                      <th className="text-left px-4 py-2 text-xs text-gray-500">Email</th>
                      <th className="text-right px-4 py-2 text-xs text-gray-500">Calls</th>
                      <th className="text-right px-4 py-2 text-xs text-gray-500">Tokens</th>
                    </tr>
                  </thead>
                  <tbody>
                    {usage.by_user.map((u, i) => (
                      <tr key={i} className="border-b hover:bg-gray-50">
                        <td className="px-4 py-2 text-gray-700">{u.email ?? u.user_id}</td>
                        <td className="px-4 py-2 text-right text-gray-500">{u.calls}</td>
                        <td className="px-4 py-2 text-right text-gray-500">{u.total_tokens?.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {logs.length > 0 && (
              <div className="bg-white rounded-xl border overflow-hidden">
                <h2 className="text-sm font-semibold text-gray-600 px-4 pt-4 pb-2">Recent logs</h2>
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b">
                    <tr>
                      <th className="text-left px-4 py-2 text-xs text-gray-500">Endpoint</th>
                      <th className="text-left px-4 py-2 text-xs text-gray-500">Model</th>
                      <th className="text-right px-4 py-2 text-xs text-gray-500">Tokens</th>
                      <th className="text-right px-4 py-2 text-xs text-gray-500">Latency</th>
                    </tr>
                  </thead>
                  <tbody>
                    {logs.map((l, i) => (
                      <tr key={i} className="border-b hover:bg-gray-50">
                        <td className="px-4 py-2 text-gray-700">{l.endpoint}</td>
                        <td className="px-4 py-2 text-gray-500">{l.model}</td>
                        <td className="px-4 py-2 text-right text-gray-500">{l.total_tokens}</td>
                        <td className="px-4 py-2 text-right text-gray-500">{l.latency_ms}ms</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* ── RAGAS Tab ── */}
        {tab === "ragas" && ragas && (
          <div className="space-y-6">
            <div className="grid grid-cols-5 gap-3">
              {RAGAS_METRICS.map(k => {
                const v = ragas.averages?.[k];
                return (
                  <div key={k} className="bg-white rounded-xl border p-3 text-center">
                    <p className="text-xs text-gray-500 mb-1 capitalize">{k.replace(/_/g, " ")}</p>
                    <p className={`text-2xl font-bold ${v != null ? scoreColor(v as number, k === "faithfulness") : "text-gray-400"}`}>
                      {v != null ? (v as number).toFixed(2) : "—"}
                    </p>
                  </div>
                );
              })}
            </div>

            {ragas.by_day && ragas.by_day.length > 0 && (
              <div className="bg-white rounded-xl border p-4">
                <h2 className="text-sm font-semibold text-gray-600 mb-3">RAGAS scores over time (7d)</h2>
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={ragas.by_day}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                    <YAxis domain={[0, 1]} tick={{ fontSize: 11 }} />
                    <Tooltip />
                    <Legend />
                    {RAGAS_METRICS.slice(0, 4).map((k, i) => (
                      <Line key={k} type="monotone" dataKey={k} stroke={RAGAS_COLORS[i]}
                        name={k.replace(/_/g, " ")} dot={false} connectNulls />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}

            {ragas.low_scoring && ragas.low_scoring.length > 0 && (
              <div className="bg-white rounded-xl border overflow-hidden">
                <h2 className="text-sm font-semibold text-gray-600 px-4 pt-4 pb-2">Low-scoring queries (faithfulness &lt; 0.8)</h2>
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b">
                    <tr>
                      <th className="text-left px-4 py-2 text-xs text-gray-500">Question</th>
                      <th className="text-left px-4 py-2 text-xs text-gray-500">Answer preview</th>
                      <th className="text-right px-4 py-2 text-xs text-gray-500">Faith.</th>
                      <th className="text-right px-4 py-2 text-xs text-gray-500">Relevancy</th>
                      <th className="text-left px-4 py-2 text-xs text-gray-500">Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ragas.low_scoring.map((r, i) => (
                      <tr key={i} className="border-b hover:bg-gray-50">
                        <td className="px-4 py-2 text-gray-700 max-w-xs truncate">{r.question}</td>
                        <td className="px-4 py-2 text-gray-500 text-xs max-w-xs truncate">{r.answer ?? "—"}</td>
                        <td className={`px-4 py-2 text-right font-medium ${scoreColor(r.faithfulness ?? 0, true)}`}>{r.faithfulness?.toFixed(2) ?? "—"}</td>
                        <td className={`px-4 py-2 text-right font-medium ${scoreColor(r.answer_relevancy ?? 0)}`}>{r.answer_relevancy?.toFixed(2) ?? "—"}</td>
                        <td className="px-4 py-2 text-xs text-gray-400">{new Date(r.created_at).toLocaleDateString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* ── Users Tab ── */}
        {tab === "users" && (
          <div className="bg-white rounded-xl border overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  {[["email", "Email"], ["role", "Role"], ["total_queries", "Queries"], ["total_tokens", "Tokens"], ["last_active_at", "Last Active"]].map(([k, l]) => (
                    <th key={k} onClick={() => sortUsers(k)}
                      className="text-left px-4 py-2 text-xs font-semibold text-gray-500 cursor-pointer hover:text-gray-700 select-none">
                      {l} {sortKey === k ? (sortAsc ? "↑" : "↓") : ""}
                    </th>
                  ))}
                  <th className="px-4 py-2 text-xs text-gray-500">Status</th>
                </tr>
              </thead>
              <tbody>
                {sortedUsers.map(u => {
                  const isSelf = u.id === user?.id;
                  return (
                    <tr key={u.id} className="border-b hover:bg-gray-50">
                      <td className="px-4 py-3 text-gray-700">{u.email}</td>
                      <td className="px-4 py-3">
                        <span className={`text-xs px-2 py-0.5 rounded-full ${u.role === "admin" ? "bg-indigo-100 text-indigo-700" : "bg-gray-100 text-gray-600"}`}>
                          {u.role}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-500">{u.total_queries ?? 0}</td>
                      <td className="px-4 py-3 text-gray-500">{u.total_tokens?.toLocaleString() ?? 0}</td>
                      <td className="px-4 py-3 text-xs text-gray-400">{u.last_active_at ? new Date(u.last_active_at).toLocaleString() : "Never"}</td>
                      <td className="px-4 py-3">
                        <button
                          disabled={isSelf}
                          onClick={() => toggleUser(u.id, u.is_active)}
                          title={isSelf ? "Cannot deactivate your own account" : ""}
                          className={`text-xs px-2 py-1 rounded-full font-medium transition-colors ${
                            isSelf
                              ? "bg-gray-100 text-gray-400 cursor-not-allowed"
                              : u.is_active
                                ? "bg-green-100 text-green-700 hover:bg-red-100 hover:text-red-700"
                                : "bg-red-100 text-red-700 hover:bg-green-100 hover:text-green-700"
                          }`}>
                          {u.is_active ? "Active" : "Inactive"}
                          {isSelf && " (you)"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {sortedUsers.length === 0 && (
                  <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-400">No users</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function Card({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white rounded-xl border p-4">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className="text-2xl font-bold text-gray-800">{value}</p>
    </div>
  );
}
