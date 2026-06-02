import React, { useState, useEffect, useCallback } from "react";
import NavBar from "../components/NavBar";
import api from "../api/client";

interface Job {
  job_id: string;
  filename: string;
  file_type: string;
  status: string;
  step?: string;
  retry_count: number;
  created_at: string;
  error_message?: string;
  chunk_count?: number;
  result?: Record<string, unknown>;
}

const STATUS_BADGE: Record<string, string> = {
  COMPLETED: "badge badge-ok",
  PROCESSING: "badge badge-warn",
  PENDING: "badge badge-neutral",
  FAILED: "badge badge-err",
  FAILED_PERMANENT: "badge badge-err",
};

const FILE_ICONS: Record<string, string> = {
  pdf: "📄",
  docx: "📝",
  xlsx: "📊",
  csv: "📊",
  image: "🖼️",
  video: "🎬",
  audio: "🎵",
};

type SortKey = keyof Job;
type FilterTab = "all" | "completed" | "pending" | "processing" | "failed";

const FILTER_TABS: { key: FilterTab; label: string }[] = [
  { key: "all", label: "All" },
  { key: "completed", label: "Completed" },
  { key: "pending", label: "Pending" },
  { key: "processing", label: "Processing" },
  { key: "failed", label: "Failed" },
];

const jobId = (j: Job) => j.job_id;

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("created_at");
  const [sortAsc, setSortAsc] = useState(false);
  const [filter, setFilter] = useState<FilterTab>("all");
  const [drawerJob, setDrawerJob] = useState<Job | null>(null);
  const [drawerLoading, setDrawerLoading] = useState(false);
  const [reprocessingAll, setReprocessingAll] = useState(false);

  const fetchJobs = useCallback(async () => {
    setFetchError(false);
    try {
      const r = await api.get("/v1/jobs");
      setJobs(r.data);
    } catch {
      setFetchError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchJobs();
    const interval = setInterval(fetchJobs, 10000);
    return () => clearInterval(interval);
  }, [fetchJobs]);

  const sort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(a => !a);
    else { setSortKey(key); setSortAsc(true); }
  };

  const filterFn = (j: Job): boolean => {
    if (filter === "all") return true;
    if (filter === "completed") return j.status === "COMPLETED";
    if (filter === "pending") return j.status === "PENDING";
    if (filter === "processing") return j.status === "PROCESSING";
    if (filter === "failed") return j.status === "FAILED" || j.status === "FAILED_PERMANENT";
    return true;
  };

  const sorted = [...jobs]
    .filter(filterFn)
    .sort((a, b) => {
      const va = a[sortKey] ?? "";
      const vb = b[sortKey] ?? "";
      const cmp = String(va).localeCompare(String(vb), undefined, { numeric: true });
      return sortAsc ? cmp : -cmp;
    });

  const openSummary = async (job: Job, e: React.MouseEvent) => {
    e.stopPropagation();
    if (job.result) { setDrawerJob(job); return; }
    setDrawerLoading(true);
    setDrawerJob(job);
    try {
      const r = await api.get(`/v1/documents/${jobId(job)}/summary`);
      const enriched = { ...job, result: r.data.summary };
      setJobs(prev => prev.map(j => jobId(j) === jobId(job) ? enriched : j));
      setDrawerJob(enriched);
    } catch {
      setDrawerJob(job);
    } finally {
      setDrawerLoading(false);
    }
  };

  const reprocess = async (job: Job, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await api.post(`/v1/jobs/${jobId(job)}/reprocess`);
      fetchJobs();
    } catch { /* ignore */ }
  };

  const reprocessAllFailed = async () => {
    const failed = jobs.filter(j => j.status === "FAILED" || j.status === "FAILED_PERMANENT");
    if (failed.length === 0) return;
    setReprocessingAll(true);
    try {
      await Promise.allSettled(failed.map(j => api.post(`/v1/jobs/${jobId(j)}/reprocess`)));
      fetchJobs();
    } finally {
      setReprocessingAll(false);
    }
  };

  // Stats
  const total = jobs.length;
  const completed = jobs.filter(j => j.status === "COMPLETED").length;
  const inProgress = jobs.filter(j => j.status === "PROCESSING" || j.status === "PENDING").length;
  const failed = jobs.filter(j => j.status === "FAILED" || j.status === "FAILED_PERMANENT").length;

  const SortTh = ({ label, k }: { label: string; k: SortKey }) => (
    <th
      onClick={() => sort(k)}
      style={{ cursor: "pointer", userSelect: "none", whiteSpace: "nowrap" }}
    >
      {label}
      {sortKey === k ? (sortAsc ? " ↑" : " ↓") : ""}
    </th>
  );

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)" }}>
      <NavBar />

      <div className="page">
        {/* Page header */}
        <div className="page-head jobs-head" style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap", gap: "1rem" }}>
          <div>
            <h1 className="page-title">Jobs</h1>
            <p className="page-sub">Ingestion status across your documents.</p>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginTop: "0.25rem" }}>
            <span
              className="pulse"
              style={{
                display: "inline-block",
                width: "8px",
                height: "8px",
                borderRadius: "50%",
                background: "var(--mint)",
                animation: "pulse 1.8s ease-in-out infinite",
              }}
            />
            <span style={{ fontSize: "0.78rem", color: "var(--slate-2)" }}>Auto-refreshes every 10s</span>
          </div>
        </div>

        {/* Stat strip */}
        <div className="stat-grid" style={{ gridTemplateColumns: "repeat(4, 1fr)", marginBottom: "1.5rem" }}>
          <div className="stat-card">
            <span className="k">Total Jobs</span>
            <span className="v">{total}</span>
          </div>
          <div className="stat-card">
            <span className="k">Completed</span>
            <span className="v" style={{ color: "var(--ok-fg)" }}>{completed}</span>
          </div>
          <div className="stat-card">
            <span className="k">Processing / Pending</span>
            <span className="v" style={{ color: "var(--warn-fg)" }}>{inProgress}</span>
          </div>
          <div className="stat-card">
            <span className="k">Failed</span>
            <span className="v" style={{ color: "var(--err-fg)" }}>{failed}</span>
          </div>
        </div>

        {/* Error banner */}
        {fetchError && !loading && (
          <div
            className="badge badge-err"
            style={{
              display: "block",
              padding: "0.75rem 1rem",
              borderRadius: "8px",
              marginBottom: "1rem",
              fontSize: "0.85rem",
              background: "var(--err-bg)",
              color: "var(--err-fg)",
            }}
          >
            Failed to load jobs. Check your connection and try again.{" "}
            <button
              className="btn btn-ghost btn-sm"
              onClick={fetchJobs}
              style={{ marginLeft: "0.5rem" }}
            >
              Retry
            </button>
          </div>
        )}

        {/* Section head: filter tabs + re-process all failed */}
        <div className="section-head" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "0.75rem", marginBottom: "0.75rem" }}>
          <div className="seg" style={{ display: "flex", gap: "2px" }}>
            {FILTER_TABS.map(tab => (
              <button
                key={tab.key}
                className={filter === tab.key ? "active" : ""}
                onClick={() => setFilter(tab.key)}
                style={{ cursor: "pointer" }}
              >
                {tab.label}
                {tab.key !== "all" && (
                  <span style={{ marginLeft: "5px", fontSize: "0.7rem", opacity: 0.7 }}>
                    ({tab.key === "completed" ? completed
                      : tab.key === "pending" ? jobs.filter(j => j.status === "PENDING").length
                      : tab.key === "processing" ? jobs.filter(j => j.status === "PROCESSING").length
                      : failed})
                  </span>
                )}
              </button>
            ))}
          </div>
          {failed > 0 && (
            <button
              onClick={reprocessAllFailed}
              disabled={reprocessingAll}
              style={{
                fontSize: "0.8rem",
                color: "var(--err-fg)",
                background: "none",
                border: "none",
                cursor: reprocessingAll ? "not-allowed" : "pointer",
                textDecoration: "underline",
                opacity: reprocessingAll ? 0.6 : 1,
                padding: 0,
              }}
            >
              {reprocessingAll ? "Re-processing..." : "Re-process all failed"}
            </button>
          )}
        </div>

        {/* Table card */}
        <div className="card" style={{ overflow: "hidden", padding: 0 }}>
          {loading ? (
            <div style={{ padding: "2rem", display: "flex", flexDirection: "column", gap: "0.5rem" }}>
              {[...Array(5)].map((_, i) => (
                <div
                  key={i}
                  style={{
                    height: "44px",
                    borderRadius: "6px",
                    background: "var(--line-2)",
                    animation: "pulse 1.5s ease-in-out infinite",
                  }}
                />
              ))}
            </div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table className="tbl" style={{ minWidth: "860px" }}>
                <thead>
                  <tr>
                    <SortTh label="File" k="filename" />
                    <th style={{ whiteSpace: "nowrap" }}>Job ID</th>
                    <SortTh label="Type" k="file_type" />
                    <SortTh label="Status" k="status" />
                    <SortTh label="Step" k="step" />
                    <th>Chunks</th>
                    <SortTh label="Retries" k="retry_count" />
                    <SortTh label="Created" k="created_at" />
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {sorted.map(j => (
                    <React.Fragment key={jobId(j)}>
                      <tr
                        onClick={() => setExpanded(expanded === jobId(j) ? null : jobId(j))}
                        style={{ cursor: "pointer" }}
                        className={expanded === jobId(j) ? "expanded" : undefined}
                      >
                        {/* File */}
                        <td>
                          <div className="fcell" style={{ display: "flex", alignItems: "center", gap: "0.5rem", minWidth: 0 }}>
                            <span className="ftype" style={{ fontSize: "1.1rem", flexShrink: 0 }}>
                              {FILE_ICONS[j.file_type] || "📄"}
                            </span>
                            <span
                              className="nm"
                              style={{
                                fontFamily: "var(--mono, 'JetBrains Mono', monospace)",
                                fontSize: "0.78rem",
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                whiteSpace: "nowrap",
                                maxWidth: "180px",
                                display: "block",
                              }}
                              title={j.filename}
                            >
                              {j.filename}
                            </span>
                          </div>
                        </td>

                        {/* Job ID */}
                        <td>
                          <span
                            className="jid"
                            style={{
                              fontFamily: "var(--mono, 'JetBrains Mono', monospace)",
                              fontSize: "0.7rem",
                              color: "var(--slate-2)",
                              display: "block",
                              maxWidth: "110px",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                            }}
                            title={j.job_id}
                          >
                            {j.job_id}
                          </span>
                        </td>

                        {/* Type */}
                        <td>
                          <span
                            className="ftype badge badge-neutral"
                            style={{ textTransform: "uppercase", fontSize: "0.68rem" }}
                          >
                            {j.file_type}
                          </span>
                        </td>

                        {/* Status */}
                        <td>
                          <span className={STATUS_BADGE[j.status] || "badge badge-neutral"}>
                            {j.status.replace("_", " ")}
                          </span>
                        </td>

                        {/* Step */}
                        <td>
                          <span
                            className="step"
                            style={{
                              fontFamily: "var(--mono, 'JetBrains Mono', monospace)",
                              fontSize: "0.72rem",
                              color: "var(--slate)",
                            }}
                          >
                            {j.step || "—"}
                          </span>
                        </td>

                        {/* Chunks */}
                        <td>
                          <span className="num" style={{ fontSize: "0.82rem", color: "var(--slate)" }}>
                            {j.chunk_count !== undefined ? j.chunk_count : "—"}
                          </span>
                        </td>

                        {/* Retries */}
                        <td>
                          <span
                            className="num"
                            style={{
                              fontSize: "0.82rem",
                              color: j.retry_count > 0 ? "var(--warn-fg)" : "var(--slate-2)",
                              fontWeight: j.retry_count > 0 ? 600 : 400,
                            }}
                          >
                            {j.retry_count}
                          </span>
                        </td>

                        {/* Created */}
                        <td style={{ whiteSpace: "nowrap", fontSize: "0.78rem", color: "var(--slate-2)" }}>
                          {fmtDate(j.created_at)}
                        </td>

                        {/* Actions */}
                        <td onClick={e => e.stopPropagation()} style={{ whiteSpace: "nowrap" }}>
                          <div style={{ display: "flex", gap: "0.35rem", alignItems: "center" }}>
                            {j.status === "COMPLETED" && (
                              <button
                                className="btn btn-ghost btn-sm"
                                onClick={e => openSummary(j, e)}
                              >
                                View Summary
                              </button>
                            )}
                            <button
                              className="btn btn-ghost btn-sm"
                              onClick={e => reprocess(j, e)}
                            >
                              Re-process
                            </button>
                          </div>
                        </td>
                      </tr>

                      {/* Expanded sub-row */}
                      {expanded === jobId(j) && (
                        <tr style={{ background: "var(--tile)" }}>
                          <td
                            colSpan={9}
                            style={{ padding: "0.75rem 1.25rem 1rem" }}
                            onClick={e => e.stopPropagation()}
                          >
                            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: "0.5rem 1.5rem", fontSize: "0.8rem", color: "var(--slate)" }}>
                              <div>
                                <span style={{ fontWeight: 600, color: "var(--slate-2)", marginRight: "0.4rem" }}>Job ID:</span>
                                <span
                                  style={{
                                    fontFamily: "var(--mono, 'JetBrains Mono', monospace)",
                                    fontSize: "0.72rem",
                                    wordBreak: "break-all",
                                  }}
                                >
                                  {j.job_id}
                                </span>
                              </div>
                              {j.chunk_count !== undefined && (
                                <div>
                                  <span style={{ fontWeight: 600, color: "var(--slate-2)", marginRight: "0.4rem" }}>Chunks:</span>
                                  <span>{j.chunk_count}</span>
                                </div>
                              )}
                              {j.error_message && (
                                <div style={{ gridColumn: "1 / -1", color: "var(--err-fg)" }}>
                                  <span style={{ fontWeight: 600, marginRight: "0.4rem" }}>Error:</span>
                                  <span>{j.error_message}</span>
                                </div>
                              )}
                              <div style={{ gridColumn: "1 / -1", display: "flex", gap: "0.5rem", flexWrap: "wrap", marginTop: "0.25rem" }}>
                                {j.status === "COMPLETED" && (
                                  <button
                                    className="btn btn-ghost btn-sm"
                                    onClick={e => openSummary(j, e)}
                                  >
                                    View Summary
                                  </button>
                                )}
                                <button
                                  className="btn btn-ghost btn-sm"
                                  onClick={e => reprocess(j, e)}
                                >
                                  Re-process
                                </button>
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  ))}

                  {sorted.length === 0 && !loading && (
                    <tr>
                      <td
                        colSpan={9}
                        style={{ padding: "3rem 1rem", textAlign: "center", color: "var(--slate-2)", fontSize: "0.88rem" }}
                      >
                        {filter === "all"
                          ? "No jobs yet — upload a file to get started"
                          : `No ${filter} jobs`}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Summary drawer */}
      {drawerJob && (
        <>
          <div
            style={{
              position: "fixed",
              inset: 0,
              background: "rgba(4,9,26,0.35)",
              zIndex: 40,
            }}
            onClick={() => setDrawerJob(null)}
          />
          <div
            style={{
              position: "fixed",
              right: 0,
              top: 0,
              height: "100%",
              width: "min(420px, 100vw)",
              background: "var(--card)",
              boxShadow: "-4px 0 32px rgba(4,9,26,0.12)",
              zIndex: 50,
              display: "flex",
              flexDirection: "column",
            }}
          >
            {/* Drawer header */}
            <div
              style={{
                padding: "1.1rem 1.25rem",
                borderBottom: "1px solid var(--line)",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <div style={{ minWidth: 0 }}>
                <p
                  style={{
                    fontWeight: 600,
                    color: "var(--ink)",
                    fontSize: "0.95rem",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {drawerJob.filename}
                </p>
                <p
                  style={{
                    fontSize: "0.7rem",
                    color: "var(--slate-2)",
                    marginTop: "2px",
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                  }}
                >
                  {drawerJob.file_type}
                </p>
              </div>
              <button
                onClick={() => setDrawerJob(null)}
                style={{
                  background: "none",
                  border: "none",
                  fontSize: "1.4rem",
                  color: "var(--slate-2)",
                  cursor: "pointer",
                  lineHeight: 1,
                  flexShrink: 0,
                  marginLeft: "0.75rem",
                }}
                aria-label="Close"
              >
                ×
              </button>
            </div>

            {/* Drawer body */}
            <div style={{ flex: 1, overflowY: "auto", padding: "1.25rem", display: "flex", flexDirection: "column", gap: "0.75rem" }}>
              {drawerLoading ? (
                <div style={{ padding: "2rem 0", textAlign: "center", color: "var(--slate-2)", fontSize: "0.85rem" }}>
                  Loading summary...
                </div>
              ) : (
                <>
                  {drawerJob.chunk_count !== undefined && (
                    <div
                      style={{
                        background: "var(--mint-soft)",
                        borderRadius: "8px",
                        padding: "0.6rem 0.9rem",
                        fontSize: "0.85rem",
                        display: "flex",
                        alignItems: "center",
                        gap: "0.5rem",
                      }}
                    >
                      <span style={{ fontWeight: 600, color: "var(--ok-fg)" }}>Chunks indexed:</span>
                      <span style={{ color: "var(--forest)" }}>{drawerJob.chunk_count}</span>
                    </div>
                  )}

                  {drawerJob.result && Object.keys(drawerJob.result).length > 0 ? (
                    Object.entries(drawerJob.result).map(([k, v]) => (
                      <div
                        key={k}
                        style={{
                          border: "1px solid var(--line)",
                          borderRadius: "8px",
                          padding: "0.75rem",
                        }}
                      >
                        <p
                          style={{
                            fontSize: "0.68rem",
                            fontWeight: 700,
                            color: "var(--slate-2)",
                            textTransform: "uppercase",
                            letterSpacing: "0.07em",
                            marginBottom: "0.4rem",
                          }}
                        >
                          {k.replace(/_/g, " ")}
                        </p>
                        {Array.isArray(v) ? (
                          <ul style={{ margin: 0, paddingLeft: "1.2rem", fontSize: "0.83rem", color: "var(--slate)", lineHeight: 1.6 }}>
                            {(v as unknown[]).map((item, i) => (
                              <li key={i}>{String(item)}</li>
                            ))}
                          </ul>
                        ) : typeof v === "object" && v !== null ? (
                          <pre
                            style={{
                              fontFamily: "var(--mono, 'JetBrains Mono', monospace)",
                              fontSize: "0.72rem",
                              color: "var(--slate)",
                              whiteSpace: "pre-wrap",
                              wordBreak: "break-word",
                              margin: 0,
                            }}
                          >
                            {JSON.stringify(v, null, 2)}
                          </pre>
                        ) : (
                          <p style={{ fontSize: "0.83rem", color: "var(--slate)", margin: 0, lineHeight: 1.6 }}>
                            {String(v)}
                          </p>
                        )}
                      </div>
                    ))
                  ) : (
                    <p style={{ textAlign: "center", color: "var(--slate-2)", fontSize: "0.85rem", marginTop: "2rem" }}>
                      No summary data available
                    </p>
                  )}
                </>
              )}
            </div>
          </div>
        </>
      )}

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.35; }
        }
      `}</style>
    </div>
  );
}
