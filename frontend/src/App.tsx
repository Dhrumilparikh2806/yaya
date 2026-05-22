import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import { ToastProvider } from "./context/ToastContext";
import PrivateRoute from "./components/PrivateRoute";

const LoginPage    = lazy(() => import("./pages/LoginPage"));
const RegisterPage = lazy(() => import("./pages/RegisterPage"));
const UploadPage   = lazy(() => import("./pages/UploadPage"));
const QueryPage    = lazy(() => import("./pages/QueryPage"));
const JobsPage     = lazy(() => import("./pages/JobsPage"));
const AdminPage    = lazy(() => import("./pages/AdminPage"));
const AgentPage    = lazy(() => import("./pages/AgentPage"));

function PageLoader() {
  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="w-8 h-8 border-4 border-indigo-600 border-t-transparent rounded-full animate-spin" />
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ToastProvider>
          <Suspense fallback={<PageLoader />}>
            <Routes>
              <Route path="/login"    element={<LoginPage />} />
              <Route path="/register" element={<RegisterPage />} />
              <Route path="/upload"   element={<PrivateRoute><UploadPage /></PrivateRoute>} />
              <Route path="/query"    element={<PrivateRoute><QueryPage /></PrivateRoute>} />
              <Route path="/agent"    element={<PrivateRoute><AgentPage /></PrivateRoute>} />
              <Route path="/jobs"     element={<PrivateRoute><JobsPage /></PrivateRoute>} />
              <Route path="/admin"    element={<PrivateRoute adminOnly><AdminPage /></PrivateRoute>} />
              <Route path="*"         element={<Navigate to="/upload" replace />} />
            </Routes>
          </Suspense>
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
