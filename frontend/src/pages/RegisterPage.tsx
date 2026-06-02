import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import axios from "axios";

const BULLETS = [
  "Ingest PDFs, DOCX, and plain text instantly",
  "Semantic search across your entire knowledge base",
  "Source-attributed answers — always traceable",
];

export default function RegisterPage() {
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [role, setRole] = useState<"user" | "admin">("user");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const passwordMismatch =
    confirmPassword.length > 0 && confirmPassword !== password;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }
    setError("");
    setLoading(true);
    try {
      const base = import.meta.env.VITE_API_URL || "http://localhost:8000";
      await axios.post(`${base}/auth/register`, { email, password, role });
      nav("/login");
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } };
      setError(e.response?.data?.detail || "Registration failed");
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
            Start building<br />your knowledge base.
          </h2>
          <p style={{ color: "rgba(255,255,255,.65)", marginTop: 18, fontSize: 15.5, lineHeight: 1.55 }}>
            Connect your documents and get grounded, cited answers in seconds.
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
          <h1>Create account</h1>
          <p className="sub">
            Get started for free. No credit card required.
          </p>

          <form onSubmit={handleSubmit}>
            <div className="field">
              <label htmlFor="reg-email">Email</label>
              <input
                id="reg-email"
                className="input"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            <div className="field">
              <label htmlFor="reg-password">Password</label>
              <input
                id="reg-password"
                className="input"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
              />
            </div>

            <div className="field">
              <label htmlFor="reg-confirm">Confirm password</label>
              <input
                id="reg-confirm"
                className="input"
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                style={
                  passwordMismatch
                    ? { borderColor: "var(--err-fg)" }
                    : undefined
                }
              />
              {passwordMismatch && (
                <span
                  style={{
                    fontSize: 12.5,
                    color: "var(--err-fg)",
                    marginTop: 4,
                    display: "block",
                  }}
                >
                  Passwords do not match
                </span>
              )}
            </div>

            <div className="field">
              <label htmlFor="reg-role">Role</label>
              <select
                id="reg-role"
                className="input"
                value={role}
                onChange={(e) => setRole(e.target.value as "user" | "admin")}
              >
                <option value="user">User</option>
                <option value="admin">Admin</option>
              </select>
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
              disabled={loading || passwordMismatch}
            >
              {loading ? "Creating account…" : "Create account"}
            </button>
          </form>

          <p className="auth-foot">
            Have an account? <Link to="/login">Sign in</Link>
          </p>
        </div>
      </main>
    </div>
  );
}
