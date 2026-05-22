import { Link, useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

const NAV_LINKS = [
  { to: "/upload", label: "Upload" },
  { to: "/query",  label: "Query"  },
  { to: "/agent",  label: "Agent"  },
  { to: "/jobs",   label: "Jobs"   },
];

export default function NavBar() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const { pathname } = useLocation();

  const handleLogout = () => { logout(); nav("/login"); };

  const linkClass = (to: string) =>
    `text-sm font-medium transition-colors ${
      pathname === to
        ? "text-white border-b-2 border-white pb-0.5"
        : "text-indigo-200 hover:text-white"
    }`;

  return (
    <nav className="bg-indigo-700 text-white px-6 py-3 flex items-center gap-6">
      <span className="font-bold text-lg tracking-tight shrink-0">GeminiRAG</span>
      {NAV_LINKS.map(({ to, label }) => (
        <Link key={to} className={linkClass(to)} to={to}>{label}</Link>
      ))}
      {user?.role === "admin" && (
        <Link className={linkClass("/admin")} to="/admin">Admin</Link>
      )}
      <div className="ml-auto flex items-center gap-4">
        <span className="text-sm text-indigo-200 hidden sm:block">{user?.email}</span>
        <button
          onClick={handleLogout}
          className="bg-white text-indigo-700 px-3 py-1 rounded text-sm font-medium hover:bg-indigo-50"
        >
          Logout
        </button>
      </div>
    </nav>
  );
}
