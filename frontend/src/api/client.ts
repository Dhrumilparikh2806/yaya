import axios from "axios";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "http://localhost:8000",
});

// Attach token from module-level getter (set by AuthProvider)
let _getToken: (() => string | null) = () => null;
export function setTokenGetter(fn: () => string | null) { _getToken = fn; }

let _onUnauthorized: (() => void) = () => {};
export function setUnauthorizedHandler(fn: () => void) { _onUnauthorized = fn; }

api.interceptors.request.use((config) => {
  const token = _getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) _onUnauthorized();
    return Promise.reject(err);
  }
);

export default api;
