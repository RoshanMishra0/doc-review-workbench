import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { ErrorBanner, MetaContext, Spinner } from "./components";
import { navigate, useRoute } from "./router";
import type { BatchDetail, Meta } from "./types";
import BatchList from "./views/BatchList";
import ExportView from "./views/ExportView";
import ImportView from "./views/ImportView";
import RecordsView from "./views/RecordsView";
import ReviewView from "./views/ReviewView";

const TABS = [
  { key: "import", label: "Import" },
  { key: "records", label: "Records" },
  { key: "review", label: "Review" },
  { key: "export", label: "Export" },
];

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const route = useRoute();

  const loadMeta = useCallback(() => {
    setError(null);
    api.meta().then(setMeta).catch((e: Error) => setError(e.message));
  }, []);
  useEffect(loadMeta, [loadMeta]);

  if (!meta) {
    return (
      <div className="boot">
        {error ? <ErrorBanner error={error} onRetry={loadMeta} /> : <Spinner label="Connecting to the local server" />}
      </div>
    );
  }

  const [first, idText, tab, recordId] = route.parts;
  const batchId = first === "batches" && idText ? Number(idText) : null;

  return (
    <MetaContext.Provider value={meta}>
      <div className="app">
        <header className="topbar">
          <a className="brand" href="#/">
            <span className="brand-mark" aria-hidden="true" />
            Document Review Workbench
          </a>
          <nav className="topnav">
            <a href="#/" className={!batchId ? "active" : ""}>
              Batches
            </a>
          </nav>
          <span className="topbar-note">Local single-user app · v{meta.version}</span>
        </header>
        <main className="main">
          {batchId ? (
            <BatchShell batchId={batchId} tab={tab ?? ""} recordId={recordId ? Number(recordId) : null} query={route.query} />
          ) : (
            <BatchList />
          )}
        </main>
      </div>
    </MetaContext.Provider>
  );
}

function BatchShell({ batchId, tab, recordId, query }: { batchId: number; tab: string; recordId: number | null; query: URLSearchParams }) {
  const [batch, setBatch] = useState<BatchDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    return api
      .batch(batchId)
      .then((b) => {
        setBatch(b);
        setError(null);
        return b;
      })
      .catch((e: Error) => {
        setError(e.message);
        return null;
      });
  }, [batchId]);

  useEffect(() => {
    setBatch(null);
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (batch && !tab) {
      navigate(`/batches/${batchId}/${batch.counts.invoices + batch.counts.references > 0 ? "records" : "import"}`);
    }
  }, [batch, tab, batchId]);

  if (error && !batch) {
    return (
      <div className="page">
        <ErrorBanner error={error} onRetry={refresh} />
        <a href="#/">Back to batches</a>
      </div>
    );
  }
  if (!batch) return <Spinner label="Loading batch" />;

  const active = tab === "records" && recordId ? "review" : tab;
  return (
    <div className="page">
      <div className="batch-head">
        <div>
          <div className="crumbs">
            <a href="#/">Batches</a> / <span>{batch.name}</span>
          </div>
          <h1>
            {batch.name} {batch.sample_id && <span className="tag tag-synthetic">Synthetic demo data</span>}
          </h1>
          <div className="muted small">
            {batch.template_name} · v{batch.template_version} · {batch.counts.invoices} invoices · {batch.counts.references} register rows ·{" "}
            {batch.counts.files.total} files
          </div>
        </div>
      </div>
      <nav className="tabs" aria-label="Batch sections">
        {TABS.map((t) => {
          const href =
            t.key === "review"
              ? recordId
                ? `#/batches/${batchId}/records/${recordId}`
                : `#/batches/${batchId}/review`
              : `#/batches/${batchId}/${t.key}`;
          return (
            <a key={t.key} href={href} className={active === t.key ? "active" : ""}>
              {t.label}
              {t.key === "import" && batch.counts.needs_mapping > 0 && <span className="tab-count warn">{batch.counts.needs_mapping}</span>}
              {t.key === "records" && batch.counts.open_exception_records > 0 && (
                <span className="tab-count">{batch.counts.open_exception_records}</span>
              )}
            </a>
          );
        })}
      </nav>
      {error && <ErrorBanner error={error} onRetry={refresh} onDismiss={() => setError(null)} />}
      {active === "import" && <ImportView batch={batch} onChanged={refresh} />}
      {active === "records" && <RecordsView batch={batch} query={query} />}
      {active === "review" && <ReviewView batch={batch} recordId={recordId} query={query} onChanged={refresh} />}
      {active === "export" && <ExportView batch={batch} onRefresh={refresh} />}
    </div>
  );
}
