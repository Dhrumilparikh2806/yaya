import { useState, useRef, useCallback } from "react";
import NavBar from "../components/NavBar";
import api from "../api/client";
import { useToastContext } from "../context/ToastContext";

const STATUS_COLORS: Record<string, string> = {
  PENDING: "bg-gray-200 text-gray-700",
  PROCESSING: "bg-blue-100 text-blue-700 animate-pulse",
  COMPLETED: "bg-green-100 text-green-700",
  FAILED: "bg-red-100 text-red-700",
  FAILED_PERMANENT: "bg-red-200 text-red-900",
};
const FILE_ICONS: Record<string, string> = {
  pdf: "📄", docx: "📝", xlsx: "📊", csv: "📊",
  image: "🖼️", video: "🎬", audio: "🎵",
};
const EXT_TO_TYPE: Record<string, string> = {
  pdf: "pdf", docx: "docx", xlsx: "xlsx", csv: "csv",
  png: "image", jpg: "image", jpeg: "image", webp: "image",
  mp4: "video", mov: "video", avi: "video",
  mp3: "audio", wav: "audio", m4a: "audio",
};

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
  const [error, setError] = useState("");
  const [drawerJob, setDrawerJob] = useState<JobCard | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollers = useRef<Record<string, ReturnType<typeof setInterval>>>({});
  const { addToast } = useToastContext();

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
    setError(""); setUploading(true);
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
      setError(msg);
      addToast(msg, "error");
    } finally { setUploading(false); }
  }, [addToast, pollJob]);

  const retryUpload = useCallback(async (job: JobCard) => {
    if (!job._file) return;
    await uploadFile(job._file);
  }, [uploadFile]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) uploadFile(file);
  }, [uploadFile]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) uploadFile(file);
    e.target.value = "";
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar />
      <div className="max-w-2xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold text-gray-800 mb-6">Upload Document</h1>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 rounded px-4 py-2 mb-4 text-sm flex items-center justify-between">
            <span>{error}</span>
            <button onClick={() => setError("")} className="font-bold ml-2">×</button>
          </div>
        )}

        <div
          onDragOver={e => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className={`border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-colors ${dragging ? "border-indigo-400 bg-indigo-50" : "border-gray-300 bg-white hover:border-indigo-300"}`}
        >
          <div className="text-4xl mb-3">📎</div>
          <p className="text-gray-600 font-medium">Drag &amp; drop a file here, or click to browse</p>
          <p className="text-xs text-gray-400 mt-1">PDF, DOCX, XLSX, CSV, PNG, JPG, WEBP, MP4, MOV, MP3, WAV, M4A</p>
          {uploading && <p className="text-indigo-600 text-sm mt-2 animate-pulse">Uploading...</p>}
          <input ref={fileInputRef} type="file" className="hidden" onChange={handleFileChange}
            accept=".pdf,.docx,.xlsx,.csv,.png,.jpg,.jpeg,.webp,.mp4,.mov,.avi,.mp3,.wav,.m4a" />
        </div>

        <div className="mt-6 space-y-3">
          {jobs.length === 0 && (
            <p className="text-center text-gray-400 text-sm py-8">No uploads yet — drop a file above to get started</p>
          )}
          {jobs.map(j => (
            <div key={j.job_id} className="bg-white rounded-xl shadow-sm border p-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3 min-w-0">
                  <span className="text-2xl shrink-0">{FILE_ICONS[j.file_type] || "📄"}</span>
                  <div className="min-w-0">
                    <p className="font-medium text-gray-800 truncate">{j.filename}</p>
                    {j.step && <p className="text-xs text-gray-500 mt-0.5 capitalize">{j.step.replace(/_/g, " ")}...</p>}
                    {j.retry_count !== undefined && j.retry_count > 0 && (
                      <p className="text-xs text-amber-600 mt-0.5">Retried {j.retry_count}×</p>
                    )}
                    {j.error_message && <p className="text-xs text-red-600 mt-0.5">{j.error_message}</p>}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0 ml-3 flex-wrap justify-end">
                  <span className={`text-xs font-semibold px-2 py-1 rounded-full whitespace-nowrap ${STATUS_COLORS[j.status] || "bg-gray-100 text-gray-700"}`}>
                    {j.status}
                  </span>
                  {j.status === "COMPLETED" && (
                    <button
                      onClick={() => setDrawerJob(j)}
                      className="text-xs bg-indigo-50 text-indigo-700 px-2 py-1 rounded-full hover:bg-indigo-100 whitespace-nowrap">
                      View Summary
                    </button>
                  )}
                  {(j.status === "FAILED" || j.status === "FAILED_PERMANENT") && j._file && (
                    <button
                      onClick={() => retryUpload(j)}
                      className="text-xs bg-amber-50 text-amber-700 px-2 py-1 rounded-full hover:bg-amber-100 whitespace-nowrap">
                      Retry
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Right-side summary drawer */}
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
