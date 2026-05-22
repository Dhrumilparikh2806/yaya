import React, { createContext, useContext, useState, useCallback, useEffect } from "react";
import axios from "axios";
import { setTokenGetter, setUnauthorizedHandler } from "../api/client";

interface AuthUser {
  id: string;
  email: string;
  role: "admin" | "user";
  token: string;
}

interface AuthContextType {
  user: AuthUser | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);

  const logout = useCallback(() => {
    setUser(null);
  }, []);

  useEffect(() => {
    setTokenGetter(() => user?.token ?? null);
    setUnauthorizedHandler(() => {
      setUser(null);
      window.location.href = "/login";
    });
  }, [user, logout]);

  const login = useCallback(async (email: string, password: string) => {
    const base = import.meta.env.VITE_API_URL || "http://localhost:8000";
    const r = await axios.post(`${base}/auth/login`, { email, password });
    const { access_token } = r.data;
    const payload = JSON.parse(atob(access_token.split(".")[1]));
    setUser({ id: payload.sub, email: payload.email || email, role: payload.role || "user", token: access_token });
  }, []);

  return <AuthContext.Provider value={{ user, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be inside AuthProvider");
  return ctx;
}
