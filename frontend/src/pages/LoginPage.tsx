import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

const BULLETS = [
  "Cited, grounded answers — no hallucinations",
  "Upload PDFs, DOCX, and text in seconds",
  "Multi-doc reasoning with source attribution",
];

export default function LoginPage() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
      nav("/upload");
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } };
      setError(e.response?.data?.detail || "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-wrap">
      <aside className="auth-aside">
        <div className="glow" />

        {/* Logo — top */}
        <div className="a-logo">
          <span className="mark" />
          GeminiRAG
        </div>

        {/* Main content — middle */}
        <div style={{ position: "relative", zIndex: 1 }}>
          <h2>
            Knowledge,<br />retrieved.
          </h2>
          <p style={{ color: "rgba(255,255,255,.65)", marginTop: 18, fontSize: 15.5, lineHeight: 1.55 }}>
            Upload, query, and reason across your documents with grounded AI — fast, measurable, and built to scale.
          </p>
          <ul style={{ listStyle: "none", marginTop: 28, display: "flex", flexDirection: "column", gap: 14, padding: 0 }}>
            {BULLETS.map((text) => (
              <li key={text} style={{ display: "flex", gap: 11, alignItems: "center", color: "#fff", fontSize: 14.5 }}>
                <span style={{ width: 22, height: 22, borderRadius: 99, background: "rgba(41,232,132,.18)", display: "grid", placeItems: "center", flexShrink: 0 }}>
                  <span style={{ width: 7, height: 7, borderRadius: 99, background: "var(--mint)" }} />
                </span>
                {text}
              </li>
            ))}
          </ul>
        </div>

        {/* Version — bottom */}
        <div className="aside-ver">v2.4 · secure workspace</div>

        <div className="auth-hex" />
      </aside>

      <main className="auth-main">
        <div className="auth-card">
          <h1>Sign in</h1>
          <p className="sub">Welcome back. Enter your credentials to continue.</p>

          <form onSubmit={handleSubmit}>
            <div className="field">
              <label htmlFor="login-email">Email</label>
              <input
                id="login-email"
                className="input"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            <div className="field">
              <label htmlFor="login-password">Password</label>
              <input
                id="login-password"
                className="input"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>

            {error && (
              <div
                style={{
                  background: "var(--err-bg)",
                  color: "var(--err-fg)",
                  borderRadius: 8,
                  padding: "10px 14px",
                  fontSize: 13.5,
                  marginBottom: 4,
                }}
              >
                {error}
              </div>
            )}

            <button
              className="btn btn-mint btn-block"
              type="submit"
              disabled={loading}
            >
              {loading ? "Signing in…" : "Sign in"}
            </button>
          </form>

          <p className="auth-foot">
            No account? <Link to="/register">Register</Link>
          </p>
        </div>
      </main>
    </div>
  );
}
