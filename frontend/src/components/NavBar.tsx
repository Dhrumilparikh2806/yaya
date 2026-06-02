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

  return (
    <header className="appnav">
      <div className="appnav-inner">
        <Link className="logo" to="/upload">
          <span className="mark"></span> GeminiRAG
        </Link>
        <nav className="appnav-links">
          {NAV_LINKS.map(({ to, label }) => (
            <Link key={to} to={to} className={pathname === to ? "active" : undefined}>
              {label}
            </Link>
          ))}
          {user?.role === "admin" && (
            <Link to="/admin" className={pathname === "/admin" ? "active" : undefined}>
              Admin
            </Link>
          )}
        </nav>
        <div className="appnav-right">
          <span className="user-email">{user?.email}</span>
          <button className="btn-logout" onClick={handleLogout}>Logout</button>
        </div>
      </div>
    </header>
  );
}
