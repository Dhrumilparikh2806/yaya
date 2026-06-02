import { useState, useRef, useCallback } from "react";
import NavBar from "../components/NavBar";
import api from "../api/client";
import { useToastContext } from "../context/ToastContext";

const FILE_ICONS: Record<string, string> = {
  pdf: "📄", docx: "📝", xlsx: "📊", csv: "📊",
  image: "🖼️", video: "🎬", audio: "🎵",
};

const EXT_TO_TYPE: Record<string, string> = {
  pdf: "pdf", docx: "docx", xlsx: "xlsx", csv: "csv",
  png: "image", jpg: "image", jpeg: "image", webp: "image",
  mp4: "video", mov: "video", avi: "video", mkv: "video", m4v: "video", webm: "video",
  mp3: "audio", wav: "audio", m4a: "audio", aac: "audio", flac: "audio", ogg: "audio",
};

const STATUS_BADGE: Record<string, string> = {
  COMPLETED: "badge badge-ok",
  PROCESSING: "badge badge-warn",
  PENDING: "badge badge-neutral",
  FAILED: "badge badge-err",
  FAILED_PERMANENT: "badge badge-err",
};

const FMT_TAGS = [
  "PDF","DOCX","XLSX","CSV","PNG","JPG","WEBP",
  "MP4","MOV","AVI","MKV","MP3","WAV","M4A","AAC","FLAC","OGG",
];

const HOWTO_STEPS = [
  { n: "01", title: "Parse", desc: "Extract raw text, tables, and media frames from your document." },
  { n: "02", title: "Chunk", desc: "Split content into overlapping passages sized for retrieval." },
  { n: "03", title: "Embed", desc: "Generate semantic vector embeddings and store in the index." },
  { n: "04", title: "Query", desc: "Run natural-language queries across all indexed documents." },
];

interface JobCard {
  job_id: string;
  filename: string;
  file_type: string;
  status: string;
  step?: string;
  retry_count?: number;
  chunk_count?: number;
  error_message?: string;
  result?: Record<string, unknown>;
  _file?: File;
}

export default function UploadPage() {
  const [jobs, setJobs] = useState<JobCard[]>([]);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [drawerJob, setDrawerJob] = useState<JobCard | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollers = useRef<Record<string, ReturnType<typeof setInterval>>>({});
  const { addToast } = useToastContext();

  const completedCount = jobs.filter(j => j.status === "COMPLETED").length;
  const inQueueCount = jobs.filter(j => j.status === "PENDING" || j.status === "PROCESSING").length;

  const pollJob = useCallback((job_id: string, filename: string) => {
    if (pollers.current[job_id]) return;
    pollers.current[job_id] = setInterval(async () => {
      try {
        const r = await api.get(`/v1/jobs/${job_id}`);
        const j = r.data;
        const parsed = j.result
          ? (typeof j.result === "string" ? JSON.parse(j.result) : j.result)
          : undefined;
        setJobs(prev => prev.map(card =>
          card.job_id === job_id
            ? { ...card, status: j.status, step: j.step, retry_count: j.retry_count, chunk_count: j.chunk_count, error_message: j.error_message, result: parsed }
            : card
        ));
        if (j.status === "COMPLETED") {
          clearInterval(pollers.current[job_id]);
          delete pollers.current[job_id];
          addToast(`Job completed — ${filename}`, "success");
        }
        if (j.status === "FAILED_PERMANENT") {
          clearInterval(pollers.current[job_id]);
          delete pollers.current[job_id];
          addToast(`Job failed — ${filename}: ${j.error_message || "unknown error"}`, "error");
        }
      } catch { /* ignore poll errors */ }
    }, 3000);
  }, [addToast]);

  const uploadFile = useCallback(async (file: File) => {
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await api.post("/v1/files/upload", fd);
      const { job_id } = r.data;
      const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
      const file_type = EXT_TO_TYPE[ext] ?? "pdf";
      setJobs(prev => [{ job_id, filename: file.name, file_type, status: "PENDING", _file: file }, ...prev]);
      addToast(`File uploaded successfully — ${file.name}`, "success");
      pollJob(job_id, file.name);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      const msg = err.response?.data?.detail || "Upload failed";
      addToast(msg, "error");
    } finally {
      setUploading(false);
    }
  }, [addToast, pollJob]);

  const retryUpload = useCallback(async (job: JobCard) => {
    if (!job._file) return;
    await uploadFile(job._file);
  }, [uploadFile]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) uploadFile(file);
  }, [uploadFile]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) uploadFile(file);
    e.target.value = "";
  };

  return (
    <div className="min-h-screen" style={{ background: "var(--bg)" }}>
      <NavBar />

      <div className="page">
        {/* Page header */}
        <div className="page-head">
          <div>
            <div className="eyebrow">Knowledge Base</div>
            <h1 className="page-title">Upload Document</h1>
            <p className="page-sub">Add files to the RAG pipeline — parsed, chunked, and embedded automatically.</p>
          </div>
        </div>

        {/* Metric strip */}
        <div className="metricbar" style={{ marginBottom: "1.5rem" }}>
          <div className="m">
            <span className="k">Documents</span>
            <span className="v">{completedCount}</span>
          </div>
          <div className="m">
            <span className="k">In queue</span>
            <span className="v">{inQueueCount}</span>
          </div>
          <div className="m">
            <span className="k">Formats supported</span>
            <span className="v">16</span>
          </div>
        </div>

        {/* Two-column layout */}
        <div className="col2" style={{ marginBottom: "2rem" }}>
          {/* Drop zone */}
          <div
            className="card card-pad"
            onDragOver={e => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: "1rem",
            }}
          >
            <div
              className="dropzone"
              onClick={() => fileInputRef.current?.click()}
              style={{
                width: "100%",
                border: `2px dashed ${dragging ? "var(--mint)" : "var(--line)"}`,
                borderRadius: "12px",
                padding: "2.5rem 1.5rem",
                textAlign: "center",
                cursor: "pointer",
                background: dragging ? "var(--mint-soft)" : "var(--tile)",
                transition: "border-color .15s, background .15s",
              }}
            >
              <div style={{ fontSize: "2.25rem", marginBottom: ".5rem" }}>📎</div>
              <p style={{ fontWeight: 600, color: "var(--ink)", marginBottom: ".25rem" }}>
                Drag &amp; drop a file here
              </p>
              <p style={{ fontSize: ".8125rem", color: "var(--slate-2)", marginBottom: "1rem" }}>or</p>
              <button
                className="btn btn-ghost btn-sm"
                type="button"
                onClick={e => { e.stopPropagation(); fileInputRef.current?.click(); }}
              >
                {uploading ? "Uploading…" : "Browse files"}
              </button>
              <input
                ref={fileInputRef}
                type="file"
                style={{ display: "none" }}
                onChange={handleFileChange}
                accept=".pdf,.docx,.xlsx,.csv,.png,.jpg,.jpeg,.webp,.mp4,.mov,.avi,.mkv,.m4v,.webm,.mp3,.wav,.m4a,.aac,.flac,.ogg"
              />
            </div>

            {/* Format grid */}
            <div
              className="fmt-grid"
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: ".375rem",
                justifyContent: "center",
                width: "100%",
              }}
            >
              {FMT_TAGS.map(tag => (
                <span
                  key={tag}
                  style={{
                    fontSize: ".6875rem",
                    fontFamily: "var(--font-mono, 'JetBrains Mono', monospace)",
                    fontWeight: 600,
                    color: "var(--teal-link)",
                    background: "var(--mint-soft)",
                    borderRadius: "4px",
                    padding: "2px 6px",
                    letterSpacing: ".02em",
                  }}
                >
                  {tag}
                </span>
              ))}
            </div>
          </div>

          {/* How-to panel */}
          <div className="card card-pad">
            <p className="eyebrow" style={{ marginBottom: ".75rem" }}>Pipeline</p>
            <h2 style={{ fontSize: "1rem", fontWeight: 700, color: "var(--ink)", marginBottom: "1.25rem" }}>
              How it works
            </h2>
            <ol className="howto" style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: "1.125rem" }}>
              {HOWTO_STEPS.map(s => (
                <li key={s.n} style={{ display: "flex", gap: ".875rem", alignItems: "flex-start" }}>
                  <span
                    style={{
                      flexShrink: 0,
                      width: "2rem",
                      height: "2rem",
                      borderRadius: "50%",
                      background: "var(--mint-soft)",
                      color: "var(--forest)",
                      fontWeight: 700,
                      fontSize: ".75rem",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontFamily: "var(--font-mono, 'JetBrains Mono', monospace)",
                    }}
                  >
                    {s.n}
                  </span>
                  <div>
                    <p style={{ fontWeight: 700, color: "var(--ink)", marginBottom: ".125rem" }}>{s.title}</p>
                    <p style={{ fontSize: ".8125rem", color: "var(--slate-2)", lineHeight: 1.5 }}>{s.desc}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </div>

        {/* Recent uploads */}
        <div className="section-head" style={{ marginBottom: "1rem" }}>
          <h2>Recent uploads</h2>
        </div>

        <div className="card">
          {jobs.length === 0 ? (
            <div className="card-pad" style={{ textAlign: "center", padding: "3rem 1.5rem", color: "var(--slate-2)", fontSize: ".875rem" }}>
              No uploads yet — drop a file above to get started
            </div>
          ) : (
            <>
              <div
                className="list-head"
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr auto auto auto",
                  gap: ".75rem",
                  padding: ".625rem 1.25rem",
                  borderBottom: "1px solid var(--line-2)",
                  fontSize: ".75rem",
                  fontWeight: 600,
                  color: "var(--slate-2)",
                  textTransform: "uppercase",
                  letterSpacing: ".05em",
                }}
              >
                <span>File</span>
                <span>Step</span>
                <span>Status</span>
                <span></span>
              </div>

              {jobs.map(j => (
                <div
                  key={j.job_id}
                  className="lrow"
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr auto auto auto",
                    alignItems: "center",
                    gap: ".75rem",
                    padding: ".875rem 1.25rem",
                    borderBottom: "1px solid var(--line-2)",
                  }}
                >
                  {/* Doc icon + name */}
                  <div style={{ display: "flex", alignItems: "center", gap: ".75rem", minWidth: 0 }}>
                    <div
                      className="doc-icon"
                      style={{
                        flexShrink: 0,
                        width: "2.25rem",
                        height: "2.25rem",
                        borderRadius: "8px",
                        background: "var(--tile)",
                        border: "1px solid var(--line)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontSize: "1.125rem",
                        position: "relative",
                      }}
                    >
                      {FILE_ICONS[j.file_type] || "📄"}
                      <span
                        style={{
                          position: "absolute",
                          bottom: "-4px",
                          right: "-4px",
                          fontSize: ".5rem",
                          fontFamily: "var(--font-mono, 'JetBrains Mono', monospace)",
                          fontWeight: 700,
                          background: "var(--forest)",
                          color: "#fff",
                          borderRadius: "3px",
                          padding: "1px 3px",
                          lineHeight: 1,
                          textTransform: "uppercase",
                        }}
                      >
                        {j.file_type}
                      </span>
                    </div>
                    <div style={{ minWidth: 0 }}>
                      <p
                        style={{
                          fontFamily: "var(--font-mono, 'JetBrains Mono', monospace)",
                          fontSize: ".8125rem",
                          fontWeight: 500,
                          color: "var(--ink)",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {j.filename}
                      </p>
                      {j.error_message && (
                        <p style={{ fontSize: ".75rem", color: "var(--err-fg)", marginTop: ".125rem" }}>
                          {j.error_message}
                        </p>
                      )}
                      {j.retry_count !== undefined && j.retry_count > 0 && (
                        <p style={{ fontSize: ".75rem", color: "var(--warn-fg)", marginTop: ".125rem" }}>
                          Retried {j.retry_count}&times;
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Step */}
                  <span style={{ fontSize: ".8125rem", color: "var(--slate-2)", whiteSpace: "nowrap" }}>
                    {j.step ? j.step.replace(/_/g, " ") : "—"}
                  </span>

                  {/* Status badge */}
                  <span className={STATUS_BADGE[j.status] || "badge badge-neutral"}>
                    {j.status === "FAILED_PERMANENT" ? "FAILED" : j.status}
                  </span>

                  {/* Actions */}
                  <div style={{ display: "flex", gap: ".5rem", justifyContent: "flex-end" }}>
                    {j.status === "COMPLETED" && (
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => setDrawerJob(j)}
                      >
                        View Summary
                      </button>
                    )}
                    {(j.status === "FAILED" || j.status === "FAILED_PERMANENT") && j._file && (
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => retryUpload(j)}
                      >
                        Retry
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </>
          )}
        </div>
      </div>

      {/* Right-side summary drawer */}
      {drawerJob && (
        <>
          {/* Overlay */}
          <div
            onClick={() => setDrawerJob(null)}
            style={{
              position: "fixed",
              inset: 0,
              background: "rgba(4,9,26,.3)",
              zIndex: 40,
            }}
          />

          {/* Drawer */}
          <div
            style={{
              position: "fixed",
              right: 0,
              top: 0,
              height: "100%",
              width: "24rem",
              background: "var(--card)",
              boxShadow: "-4px 0 32px rgba(4,9,26,.12)",
              zIndex: 50,
              display: "flex",
              flexDirection: "column",
            }}
          >
            {/* Drawer header */}
            <div
              style={{
                padding: "1.25rem 1.5rem",
                borderBottom: "1px solid var(--line)",
                display: "flex",
                alignItems: "flex-start",
                justifyContent: "space-between",
                gap: "1rem",
              }}
            >
              <div style={{ minWidth: 0 }}>
                <p
                  style={{
                    fontWeight: 700,
                    color: "var(--ink)",
                    fontFamily: "var(--font-mono, 'JetBrains Mono', monospace)",
                    fontSize: ".875rem",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {drawerJob.filename}
                </p>
                <span
                  style={{
                    display: "inline-block",
                    marginTop: ".25rem",
                    fontSize: ".6875rem",
                    fontWeight: 700,
                    fontFamily: "var(--font-mono, 'JetBrains Mono', monospace)",
                    color: "var(--teal-link)",
                    background: "var(--mint-soft)",
                    borderRadius: "4px",
                    padding: "2px 6px",
                    textTransform: "uppercase",
                    letterSpacing: ".04em",
                  }}
                >
                  {drawerJob.file_type}
                </span>
              </div>
              <button
                onClick={() => setDrawerJob(null)}
                style={{
                  flexShrink: 0,
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  fontSize: "1.25rem",
                  color: "var(--slate-2)",
                  lineHeight: 1,
                  padding: "2px",
                }}
                aria-label="Close drawer"
              >
                &times;
              </button>
            </div>

            {/* Drawer body */}
            <div
              style={{
                flex: 1,
                overflowY: "auto",
                padding: "1.25rem 1.5rem",
                display: "flex",
                flexDirection: "column",
                gap: "1rem",
              }}
            >
              {drawerJob.chunk_count !== undefined && (
                <div
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: ".375rem",
                    background: "var(--mint-soft)",
                    color: "var(--ok-fg)",
                    borderRadius: "6px",
                    padding: ".375rem .75rem",
                    fontSize: ".8125rem",
                    fontWeight: 600,
                  }}
                >
                  <span>Chunks indexed:</span>
                  <span
                    style={{
                      fontFamily: "var(--font-mono, 'JetBrains Mono', monospace)",
                      fontSize: ".875rem",
                    }}
                  >
                    {drawerJob.chunk_count}
                  </span>
                </div>
              )}

              {drawerJob.result && Object.keys(drawerJob.result).length > 0 ? (
                Object.entries(drawerJob.result).map(([k, v]) => (
                  <div
                    key={k}
                    style={{
                      border: "1px solid var(--line)",
                      borderRadius: "8px",
                      padding: ".875rem 1rem",
                    }}
                  >
                    <p
                      style={{
                        fontSize: ".6875rem",
                        fontWeight: 700,
                        color: "var(--slate-2)",
                        textTransform: "uppercase",
                        letterSpacing: ".06em",
                        marginBottom: ".5rem",
                      }}
                    >
                      {k.replace(/_/g, " ")}
                    </p>
                    {Array.isArray(v) ? (
                      <ul style={{ margin: 0, paddingLeft: "1.25rem", display: "flex", flexDirection: "column", gap: ".25rem" }}>
                        {(v as unknown[]).map((item, i) => (
                          <li key={i} style={{ fontSize: ".875rem", color: "var(--ink)", lineHeight: 1.55 }}>
                            {String(item)}
                          </li>
                        ))}
                      </ul>
                    ) : typeof v === "object" && v !== null ? (
                      <pre
                        style={{
                          fontFamily: "var(--font-mono, 'JetBrains Mono', monospace)",
                          fontSize: ".75rem",
                          color: "var(--slate)",
                          whiteSpace: "pre-wrap",
                          wordBreak: "break-all",
                          margin: 0,
                        }}
                      >
                        {JSON.stringify(v, null, 2)}
                      </pre>
                    ) : (
                      <p style={{ fontSize: ".875rem", color: "var(--ink)", lineHeight: 1.55 }}>
                        {String(v)}
                      </p>
                    )}
                  </div>
                ))
              ) : (
                <p
                  style={{
                    fontSize: ".875rem",
                    color: "var(--slate-2)",
                    textAlign: "center",
                    marginTop: "3rem",
                  }}
                >
                  No summary data available
                </p>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
