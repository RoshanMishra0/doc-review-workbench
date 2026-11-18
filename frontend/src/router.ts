import { useEffect, useState } from "react";

export interface Route {
  parts: string[];
  query: URLSearchParams;
}

function parse(hash: string): Route {
  const raw = hash.replace(/^#/, "") || "/";
  const [path, query] = raw.split("?");
  return { parts: path.split("/").filter(Boolean), query: new URLSearchParams(query || "") };
}

export function useRoute(): Route {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const onChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return parse(hash);
}

export function navigate(path: string): void {
  window.location.hash = path;
}

export function withQuery(path: string, params: Record<string, string | undefined | null | false>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) p.set(k, v);
  const s = p.toString();
  return s ? `${path}?${s}` : path;
}
