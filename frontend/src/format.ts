import type { Labels } from "./types";

export function label(labels: Labels | undefined, group: keyof Labels, key: string | null | undefined): string {
  if (!key) return "";
  return labels?.[group]?.[key] ?? key.replace(/_/g, " ");
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export type Tone = "good" | "warn" | "bad" | "neutral" | "info" | "accent";

export function matchTone(status: string): Tone {
  switch (status) {
    case "matched":
      return "good";
    case "mismatched":
    case "invalid":
      return "bad";
    case "ambiguous":
    case "missing_from_reference":
    case "no_invoice":
    case "partner_invalid":
      return "warn";
    default:
      return "neutral";
  }
}

export function validationTone(status: string): Tone {
  return status === "passed" ? "good" : status === "warnings" ? "warn" : status === "failed" ? "bad" : "neutral";
}

export function reviewTone(status: string): Tone {
  return status === "approved" ? "good" : status === "excluded" ? "neutral" : "info";
}

export function fileTone(status: string): Tone {
  switch (status) {
    case "processed":
      return "good";
    case "rejected":
      return "bad";
    case "needs_mapping":
      return "warn";
    case "removed":
      return "neutral";
    default:
      return "info";
  }
}

export function fieldTone(status: string): Tone {
  return status === "missing" ? "bad" : status === "user_corrected" ? "accent" : status === "source_default" ? "warn" : "neutral";
}

export const ACTION_LABELS: Record<string, string> = {
  batch_created: "Batch created",
  file_uploaded: "File uploaded",
  mapping_confirmed: "Column mapping confirmed",
  file_removed: "File removed",
  batch_processed: "Batch processed",
  corrected: "Value corrected",
  correction_reverted: "Correction reverted",
  approved: "Approved",
  excluded: "Excluded",
  reopened: "Reopened",
  note: "Note",
  linked: "Linked manually",
  unlinked: "Manual link removed",
  link_removed: "Manual link removed by the system",
  approval_withdrawn: "Approval withdrawn",
};
