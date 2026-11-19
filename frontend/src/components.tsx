import { createContext, useContext, useEffect, type ReactNode } from "react";
import type { Tone } from "./format";
import type { Meta, TemplateSummary } from "./types";

export const MetaContext = createContext<Meta | null>(null);

export function useMeta(): Meta {
  const meta = useContext(MetaContext);
  if (!meta) throw new Error("Meta not loaded");
  return meta;
}

export function useTemplate(templateId: string): TemplateSummary {
  const meta = useMeta();
  const t = meta.templates.find((x) => x.id === templateId);
  if (!t) throw new Error(`Template ${templateId} is not installed`);
  return t;
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** Role wording from the template: "invoice"/"register row" for invoices, "claim"/"register row" for expenses. */
export function roleWords(t: TemplateSummary) {
  const rec = t.roles.invoice.label.toLowerCase();
  const refRow = t.roles.reference.label.toLowerCase();
  return {
    rec,
    Rec: cap(rec),
    recs: t.roles.invoice.plural.toLowerCase(),
    refRow,
    RefRow: cap(refRow),
    ref: t.roles.reference.plural.toLowerCase(),
    count: (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`,
  };
}

export function Badge({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span className={`badge badge-${tone}`} title={title}>
      {children}
    </span>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="spinner-wrap" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      {label && <span>{label}</span>}
    </span>
  );
}

export function ErrorBanner({ error, onRetry, onDismiss }: { error: string | null; onRetry?: () => void; onDismiss?: () => void }) {
  if (!error) return null;
  return (
    <div className="banner banner-error" role="alert">
      <span>{error}</span>
      <span className="banner-actions">
        {onRetry && (
          <button className="btn btn-small" onClick={onRetry}>
            Try again
          </button>
        )}
        {onDismiss && (
          <button className="btn btn-small btn-ghost" onClick={onDismiss} aria-label="Dismiss">
            Dismiss
          </button>
        )}
      </span>
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "good"; children: ReactNode }) {
  return <div className={`banner banner-${tone}`}>{children}</div>;
}

export function EmptyState({ title, children, actions }: { title: string; children?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children && <div className="muted">{children}</div>}
      {actions && <div className="empty-actions">{actions}</div>}
    </div>
  );
}

export function Card({ title, actions, children, className }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className ?? ""}`}>
      {(title || actions) && (
        <header className="card-head">
          {title && <h2>{title}</h2>}
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      <div className="card-body">{children}</div>
    </section>
  );
}

export function Progress({ value, total }: { value: number; total: number }) {
  const pct = total ? Math.round((value / total) * 100) : 0;
  return (
    <div className="progress" title={`${value} of ${total} reviewed`}>
      <div className="progress-bar">
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="progress-text">
        {value}/{total}
      </span>
    </div>
  );
}

export function Modal({ title, onClose, children, footer, wide }: { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? "modal-wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <header className="modal-head">
          <h2>{title}</h2>
          <button className="btn btn-ghost btn-small" onClick={onClose} aria-label="Close">
            Close
          </button>
        </header>
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-foot">{footer}</footer>}
      </div>
    </div>
  );
}
