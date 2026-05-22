import React, { useState, useEffect } from "react";
import NavBar from "../components/NavBar";
import api from "../api/client";

interface Job {
  id: string;
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

const STATUS_COLORS: Record<string, string> = {
  PENDING: "bg-gray-100 text-gray-600",
  PROCESSING: "bg-blue-100 text-blue-600",
  COMPLETED: "bg-green-100 text-green-600",
  FAILED: "bg-red-100 text-red-600",
  FAILED_PERMANENT: "bg-red-200 text-red-800",
};
const FILE_ICONS: Record<string, string> = {
  pdf: "📄", docx: "📝", xlsx: "📊", csv: "📊", image: "🖼️", video: "🎬", audio: "🎵",
};

type SortKey = keyof Job;

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("created_at");
  const [sortAsc, setSortAsc] = useState(false);
  const [drawerJob, setDrawerJob] = useState<Job | null>(null);

  const fetchJobs = async () => {
    setFetchError(false);
    try {
      const r = await api.get("/v1/jobs");
      setJobs(r.data);
    } catch {
      setFetchError(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchJobs();
    const interval = setInterval(fetchJobs, 10000);
    return () => clearInterval(interval);
  }, []);

  const sort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(a => !a);
    else { setSortKey(key); setSortAsc(true); }
  };

  const sorted = [...jobs].sort((a, b) => {
    const va = a[sortKey] ?? ""; const vb = b[sortKey] ?? "";
    const cmp = String(va).localeCompare(String(vb));
    return sortAsc ? cmp : -cmp;
  });

  const openSummary = async (job: Job, e: React.MouseEvent) => {
    e.stopPropagation();
    if (job.result) { setDrawerJob(job); return; }
    try {
      const r = await api.get(`/v1/documents/${job.id}/summary`);
      const enriched = { ...job, result: r.data.summary };
      setJobs(prev => prev.map(j => j.id === job.id ? enriched : j));
      setDrawerJob(enriched);
    } catch { setDrawerJob(job); }
  };

  const Th = ({ label, k }: { label: string; k: SortKey }) => (
    <th className="text-left px-4 py-2 text-xs font-semibold text-gray-500 uppercase cursor-pointer hover:text-gray-800 select-none whitespace-nowrap"
      onClick={() => sort(k)}>
      {label} {sortKey === k ? (sortAsc ? "↑" : "↓") : ""}
    </th>
  );

  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar />
      <div className="max-w-5xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-gray-800">Jobs</h1>
          <div className="flex items-center gap-3">
            {fetchError && (
              <button onClick={fetchJobs} className="text-xs text-indigo-600 hover:underline border border-indigo-200 px-2 py-1 rounded">
                Retry
              </button>
            )}
            <span className="text-xs text-gray-400">Auto-refreshes every 10s</span>
          </div>
        </div>

        {fetchError && !loading && (
          <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm mb-4">
            Failed to load jobs. Check your connection and try again.
          </div>
        )}

        {loading ? (
          <div className="space-y-2">
            {[...Array(5)].map((_, i) => <div key={i} className="h-12 bg-gray-200 animate-pulse rounded-lg" />)}
          </div>
        ) : (
          <div className="bg-white rounded-xl shadow-sm border overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px]">
                <thead className="border-b bg-gray-50">
                  <tr>
                    <Th label="File" k="filename" />
                    <Th label="Type" k="file_type" />
                    <Th label="Status" k="status" />
                    <Th label="Step" k="step" />
                    <Th label="Retries" k="retry_count" />
                    <Th label="Created" k="created_at" />
                  </tr>
                </thead>
                <tbody>
                  {sorted.map(j => (
                    <React.Fragment key={j.id}>
                      <tr
                        className="border-b hover:bg-gray-50 cursor-pointer"
                        onClick={() => setExpanded(expanded === j.id ? null : j.id)}
                      >
                        <td className="px-4 py-3 text-sm text-gray-800">
                          <span className="mr-1">{FILE_ICONS[j.file_type] || "📄"}</span>{j.filename}
                        </td>
                        <td className="px-4 py-3 text-xs text-gray-500 uppercase">{j.file_type}</td>
                        <td className="px-4 py-3">
                          <span className={`text-xs px-2 py-1 rounded-full font-medium ${STATUS_COLORS[j.status] || "bg-gray-100"}`}>
                            {j.status}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-xs text-gray-500">{j.step || "—"}</td>
                        <td className="px-4 py-3 text-xs text-gray-500">{j.retry_count}</td>
                        <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">{new Date(j.created_at).toLocaleString()}</td>
                      </tr>
                      {expanded === j.id && (
                        <tr className="bg-gray-50 border-b">
                          <td colSpan={6} className="px-4 py-3 text-sm text-gray-700">
                            <div className="grid grid-cols-2 gap-2">
                              <div><span className="font-medium text-gray-500">Job ID:</span> <span className="font-mono text-xs">{j.id}</span></div>
                              {j.chunk_count !== undefined && (
                                <div><span className="font-medium text-gray-500">Chunks:</span> {j.chunk_count}</div>
                              )}
                              {j.error_message && (
                                <div className="col-span-2 text-red-600">
                                  <span className="font-medium">Error:</span> {j.error_message}
                                </div>
                              )}
                              <div className="col-span-2 mt-1 flex gap-2 flex-wrap">
                              {j.status === "COMPLETED" && (
                                <button
                                  onClick={e => openSummary(j, e)}
                                  className="text-xs bg-indigo-50 text-indigo-700 px-3 py-1 rounded-full hover:bg-indigo-100">
                                  View Summary
                                </button>
                              )}
                              {(j.status === "COMPLETED" || j.status === "FAILED" || j.status === "FAILED_PERMANENT") && (
                                <button
                                  onClick={async e => {
                                    e.stopPropagation();
                                    try {
                                      await api.post(`/v1/jobs/${j.id}/reprocess`);
                                      fetchJobs();
                                    } catch { /* ignore */ }
                                  }}
                                  className="text-xs bg-gray-100 text-gray-600 px-3 py-1 rounded-full hover:bg-gray-200">
                                  Re-process
                                </button>
                              )}
                            </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  ))}
                  {sorted.length === 0 && !fetchError && (
                    <tr>
                      <td colSpan={6} className="px-4 py-8 text-center text-gray-400 text-sm">
                        No jobs yet — upload a file to get started
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Summary drawer */}
      {drawerJob && (
        <>
          <div className="fixed inset-0 bg-black/30 z-40" onClick={() => setDrawerJob(null)} />
          <div className="fixed right-0 top-0 h-full w-full sm:w-96 bg-white shadow-2xl z-50 flex flex-col">
            <div className="px-5 py-4 border-b flex items-center justify-between">
              <div>
                <h2 className="font-semibold text-gray-800">{drawerJob.filename}</h2>
                <p className="text-xs text-gray-400 mt-0.5 uppercase">{drawerJob.file_type}</p>
              </div>
              <button onClick={() => setDrawerJob(null)} className="text-gray-400 hover:text-gray-700 text-xl font-bold">×</button>
            </div>
            <div className="flex-1 overflow-y-auto p-5 space-y-3">
              {drawerJob.chunk_count !== undefined && (
                <div className="bg-indigo-50 rounded-lg px-3 py-2 text-sm">
                  <span className="font-medium text-indigo-700">Chunks indexed:</span>
                  <span className="ml-2 text-indigo-600">{drawerJob.chunk_count}</span>
                </div>
              )}
              {drawerJob.result && Object.keys(drawerJob.result).length > 0 ? (
                Object.entries(drawerJob.result).map(([k, v]) => (
                  <div key={k} className="border rounded-lg p-3">
                    <p className="text-xs font-semibold text-gray-500 uppercase mb-1">{k.replace(/_/g, " ")}</p>
                    {Array.isArray(v) ? (
                      <ul className="list-disc list-inside text-sm text-gray-700 space-y-0.5">
                        {(v as unknown[]).map((item, i) => <li key={i}>{String(item)}</li>)}
                      </ul>
                    ) : typeof v === "object" && v !== null ? (
                      <pre className="text-xs text-gray-600 whitespace-pre-wrap">{JSON.stringify(v, null, 2)}</pre>
                    ) : (
                      <p className="text-sm text-gray-700">{String(v)}</p>
                    )}
                  </div>
                ))
              ) : (
                <p className="text-sm text-gray-400 text-center mt-8">No summary data available</p>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
