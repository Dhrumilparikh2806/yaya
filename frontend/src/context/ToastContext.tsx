import { createContext, useContext, ReactNode } from "react";
import { useToast, Toast, ToastType } from "../hooks/useToast";

interface ToastCtx {
  addToast: (message: string, type?: ToastType) => void;
}

const ToastContext = createContext<ToastCtx>({ addToast: () => {} });

export function useToastContext() {
  return useContext(ToastContext);
}

const BG: Record<ToastType, string> = {
  success: "bg-green-600",
  error: "bg-red-600",
  info: "bg-blue-600",
};

function ToastItem({ toast, onRemove }: { toast: Toast; onRemove: (id: number) => void }) {
  return (
    <div className={`flex items-center gap-3 ${BG[toast.type]} text-white px-4 py-3 rounded-lg shadow-lg min-w-64 max-w-sm`}>
      <span className="flex-1 text-sm">{toast.message}</span>
      <button onClick={() => onRemove(toast.id)} className="text-white/70 hover:text-white text-lg leading-none">×</button>
    </div>
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const { toasts, addToast, removeToast } = useToast();

  return (
    <ToastContext.Provider value={{ addToast }}>
      {children}
      <div className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 items-end">
        {toasts.map(t => (
          <ToastItem key={t.id} toast={t} onRemove={removeToast} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}
