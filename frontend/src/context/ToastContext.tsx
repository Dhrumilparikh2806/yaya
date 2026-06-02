import { createContext, useContext, ReactNode, CSSProperties } from "react";
import { useToast, Toast, ToastType } from "../hooks/useToast";

interface ToastCtx {
  addToast: (message: string, type?: ToastType) => void;
}

const ToastContext = createContext<ToastCtx>({ addToast: () => {} });

export function useToastContext() {
  return useContext(ToastContext);
}

const TOAST_STYLES: Record<ToastType, CSSProperties> = {
  success: {
    background: "var(--ok-bg)",
    color: "var(--ok-fg)",
  },
  error: {
    background: "var(--err-bg)",
    color: "var(--err-fg)",
  },
  warning: {
    background: "var(--warn-bg)",
    color: "var(--warn-fg)",
  },
  info: {
    background: "var(--line-2, #EDF1EE)",
    color: "var(--slate, #46566B)",
  },
};

const containerStyle: CSSProperties = {
  position: "fixed",
  bottom: "16px",
  right: "16px",
  zIndex: 9999,
  display: "flex",
  flexDirection: "column",
  gap: "8px",
  alignItems: "flex-end",
};

function ToastItem({ toast, onRemove }: { toast: Toast; onRemove: (id: number) => void }) {
  const toastStyle: CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: "10px",
    padding: "12px 16px",
    borderRadius: "10px",
    fontSize: "14px",
    fontWeight: 500,
    fontFamily: "var(--font-body, 'Hanken Grotesk', sans-serif)",
    boxShadow: "0 4px 16px rgba(4,9,26,.16)",
    minWidth: "220px",
    maxWidth: "360px",
    ...TOAST_STYLES[toast.type],
  };

  const closeStyle: CSSProperties = {
    marginLeft: "auto",
    background: "transparent",
    border: "none",
    cursor: "pointer",
    opacity: 0.6,
    fontSize: "18px",
    lineHeight: 1,
    color: "inherit",
    padding: "0 0 0 4px",
    flexShrink: 0,
  };

  return (
    <div style={toastStyle}>
      <span style={{ flex: 1 }}>{toast.message}</span>
      <button
        style={closeStyle}
        onClick={() => onRemove(toast.id)}
        aria-label="Dismiss notification"
      >
        ×
      </button>
    </div>
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const { toasts, addToast, removeToast } = useToast();

  return (
    <ToastContext.Provider value={{ addToast }}>
      {children}
      <div style={containerStyle}>
        {toasts.map((t) => (
          <ToastItem key={t.id} toast={t} onRemove={removeToast} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}
