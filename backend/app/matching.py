"""Conservative matching of records against reference rows. Pure functions.

Rules:

* Identity is the configured identity fields (default: normalized supplier,
  invoice number and currency). No fuzzy matching. An amount never creates a
  match on its own.
* A pair is formed only when exactly one active invoice and exactly one free
  reference row share an identity. Duplicate invoices, or several reference
  rows with the same identity, stay ambiguous until a reviewer resolves them
  (exclude a duplicate, or link a specific reference row).
* A reference row is never paired with more than one invoice.
* After pairing, the configured compare fields are checked; any difference
  beyond tolerance is a mismatch, explained in words.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field

from .normalization import format_money, short_date
from .template_config import Template
from .validation import EvaluatedRecord

INVOICE_STATUSES = ("matched", "mismatched", "missing_from_reference", "ambiguous", "invalid", "not_compared")
REFERENCE_STATUSES = ("matched", "mismatched", "no_invoice", "ambiguous", "invalid", "partner_invalid", "not_compared")

# status -> (issue category, severity). Statuses not listed raise no matching issue.
STATUS_ISSUES = {
    "mismatched": ("mismatch", "error"),
    "missing_from_reference": ("missing_from_reference", "error"),
    "no_invoice": ("no_invoice", "error"),
    "ambiguous": ("ambiguous", "error"),
    "invalid": ("needs_correction", "error"),
    "partner_invalid": ("partner_needs_correction", "warning"),
}


@dataclass
class Comparison:
    field: str
    label: str
    record_value: str | None
    reference_value: str | None
    status: str  # equal | within_tolerance | different | not_comparable
    difference: str | None = None
    message: str | None = None


@dataclass
class MatchResult:
    status: str
    partner_id: int | None = None
    method: str | None = None  # identity | manual_link
    explanation: list[str] = field(default_factory=list)
    comparisons: list[Comparison] = field(default_factory=list)
    candidates: list[int] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    no_reference_rows: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


class Matcher:
    def __init__(self, template: Template):
        self.t = template
        self.inv_label = template.roles["invoice"].label.lower()
        self.ref_label = template.roles["reference"].plural.lower()
        self.identity_text = _join([template.label(n).lower() for n in template.matching.identity_fields])

    # -------------------------------------------------------------- helpers
    def _money(self, value, code) -> str:
        c = self.t.currency
        return format_money(value, code, c.symbols, c.minor_units, c.grouping)

    def _currency(self, rec: EvaluatedRecord):
        name = self.t.currency_field
        return rec.typed(name) if name else None

    def compare(self, inv: EvaluatedRecord, ref: EvaluatedRecord, method: str) -> tuple[MatchResult, MatchResult]:
        comparisons: list[Comparison] = []
        inv_problems: list[str] = []
        ref_problems: list[str] = []
        differences: list[str] = []
        tolerated: list[str] = []
        code = self._currency(inv)
        for c in self.t.matching.compare:
            fi, fr = inv.fields[c.field], ref.fields[c.field]
            label = fi.label
            vi, vr = fi.value, fr.value
            if vi is None or vr is None:
                if vi is None:
                    inv_problems.append(f"{label.lower()} is {'missing' if fi.current is None else 'invalid'}")
                if vr is None:
                    ref_problems.append(f"{label.lower()} is {'missing' if fr.current is None else 'invalid'}")
                comparisons.append(Comparison(c.field, label, fi.display or fi.current, fr.display or fr.current,
                                              "not_comparable"))
                continue
            if fi.type == "money":
                diff = vi - vr
                shown_i, shown_r = self._money(vi, code), self._money(vr, code)
                if diff == 0:
                    comparisons.append(Comparison(c.field, label, shown_i, shown_r, "equal"))
                elif abs(diff) <= c.tolerance:
                    msg = f"{label} differs by {self._money(abs(diff), code)}, within the tolerance of {self._money(c.tolerance, code)}."
                    tolerated.append(msg)
                    comparisons.append(Comparison(c.field, label, shown_i, shown_r, "within_tolerance",
                                                  self._money(abs(diff), code), msg))
                else:
                    msg = (f"{self.inv_label.capitalize()} {label.lower()} is {shown_i}; {self.ref_label} "
                           f"{label.lower()} is {shown_r} (difference {self._money(abs(diff), code)}).")
                    differences.append(msg)
                    comparisons.append(Comparison(c.field, label, shown_i, shown_r, "different",
                                                  self._money(abs(diff), code), msg))
            elif fi.type == "date":
                si, sr = short_date(vi), short_date(vr)
                if vi == vr:
                    comparisons.append(Comparison(c.field, label, si, sr, "equal"))
                else:
                    days = abs((vi - vr).days)
                    msg = (f"{self.inv_label.capitalize()} {label.lower()} is {si}; {self.ref_label} "
                           f"{label.lower()} is {sr} ({days} day{'s' if days != 1 else ''} apart).")
                    differences.append(msg)
                    comparisons.append(Comparison(c.field, label, si, sr, "different", f"{days} days", msg))
            else:
                ki = fi.key or (fi.display or "").casefold()
                kr = fr.key or (fr.display or "").casefold()
                if ki == kr:
                    comparisons.append(Comparison(c.field, label, fi.display, fr.display, "equal"))
                else:
                    msg = f"{label} differs: '{fi.display}' on the {self.inv_label}, '{fr.display}' in the {self.ref_label}."
                    differences.append(msg)
                    comparisons.append(Comparison(c.field, label, fi.display, fr.display, "different", None, msg))

        lead = "Linked by a reviewer. " if method == "manual_link" else ""
        if inv_problems:
            r_inv = MatchResult("invalid", ref.id, method, [
                f"{lead}Same {self.identity_text} as {ref.label}, but {_join(inv_problems)}. "
                f"Correct the {self.inv_label} to complete the comparison."], comparisons)
            r_ref = MatchResult("partner_invalid", inv.id, method, [
                f"{lead}Paired by {self.identity_text} with {inv.label}, which needs correction "
                f"({_join(inv_problems)})."], comparisons)
            return r_inv, r_ref
        if ref_problems:
            r_inv = MatchResult("mismatched", ref.id, method, [
                f"{lead}Same {self.identity_text} as {ref.label}, but that row's {_join(ref_problems)}, "
                f"so agreement cannot be confirmed."], comparisons)
            r_ref = MatchResult("invalid", inv.id, method, [
                f"{lead}This row's {_join(ref_problems)}. Correct it to complete the comparison with {inv.label}."],
                comparisons)
            return r_inv, r_ref
        if differences:
            r_inv = MatchResult("mismatched", ref.id, method, [f"{lead}Paired with {ref.label} by {self.identity_text}."]
                                + differences, comparisons)
            r_ref = MatchResult("mismatched", inv.id, method, [f"{lead}Paired with {inv.label} by {self.identity_text}."]
                                + differences, comparisons)
            return r_inv, r_ref
        agreed = _join([self.t.label(c.field).lower() for c in self.t.matching.compare])
        r_inv = MatchResult("matched", ref.id, method, [
            f"{lead}Matched with {ref.label}: same {self.identity_text}, and {agreed} agree."] + tolerated, comparisons)
        r_ref = MatchResult("matched", inv.id, method, [
            f"{lead}Matched with {inv.label}: same {self.identity_text}, and {agreed} agree."] + tolerated, comparisons)
        return r_inv, r_ref

    # -------------------------------------------------------------- hints
    def _build_indexes(self, records: list[EvaluatedRecord]):
        k = len(self.t.matching.identity_fields)
        partial: list[dict[tuple, list[EvaluatedRecord]]] = [defaultdict(list) for _ in range(k)]
        for rec in records:
            keys = [p[1] for p in rec.identity_parts]
            for j in range(k):
                rest = tuple(keys[:j] + keys[j + 1:])
                if all(x is not None for x in rest):
                    partial[j][rest].append(rec)
        return partial

    def hints_for(self, rec: EvaluatedRecord, other_index) -> list[str]:
        """Rows that agree on every identity part except one non-identifier part (e.g. supplier spelling).

        Hints never create a match; they only tell the reviewer where to look.
        Differences in identifier fields (invoice numbers) are not hinted, since
        every other invoice from the same supplier would qualify.
        """
        keys = [p[1] for p in rec.identity_parts]
        types = [self.t.field(n).type for n in self.t.matching.identity_fields]
        hints: list[str] = []
        seen: set[int] = set()
        for j in range(len(keys)):
            if types[j] == "identifier":
                continue
            rest = tuple(keys[:j] + keys[j + 1:])
            if any(x is None for x in rest):
                continue
            for other in other_index[j].get(rest, []):
                if other.id in seen or other.excluded:
                    continue
                okeys = [p[1] for p in other.identity_parts]
                if keys[j] is not None and okeys[j] == keys[j]:
                    continue  # full identity agreement is handled by matching, not hints
                seen.add(other.id)
                agree = _join([rec.identity_parts[i][0].lower() for i in range(len(keys)) if i != j])
                label_j = rec.identity_parts[j][0].lower()
                theirs = other.identity_parts[j][2]
                if keys[j] is None:
                    hints.append(f"{other.label} agrees on {agree}; this record's {label_j} is missing or invalid.")
                elif okeys[j] is None:
                    hints.append(f"{other.label} agrees on {agree}, but its {label_j} is missing or invalid, "
                                 f"so it can't be matched until that record is corrected.")
                else:
                    hints.append(
                        f"{other.label} agrees on {agree} but has {label_j} '{theirs}'. "
                        f"They were not matched because the {label_j} differs after the documented normalization.")
                if len(hints) >= 3:
                    return hints
        return hints

    # -------------------------------------------------------------- main
    def run(self, records: list[EvaluatedRecord], links: dict[int, int]):
        results: dict[int, MatchResult] = {}
        dropped: list[tuple[int, int, str]] = []
        by_id = {r.id: r for r in records}
        inv_all = [r for r in records if r.role == "invoice"]
        ref_all = [r for r in records if r.role == "reference"]
        for r in records:
            if r.excluded:
                results[r.id] = MatchResult("not_compared", explanation=["Excluded by a reviewer, so it is not compared."])
        active_inv = [r for r in inv_all if not r.excluded]
        active_ref = [r for r in ref_all if not r.excluded]

        valid_links: dict[int, int] = {}
        for inv_id, ref_id in links.items():
            i, f = by_id.get(inv_id), by_id.get(ref_id)
            if not i or not f or i.role != "invoice" or f.role != "reference":
                dropped.append((inv_id, ref_id, "One of the linked records no longer exists."))
            elif i.excluded or f.excluded:
                dropped.append((inv_id, ref_id, "One of the linked records was excluded."))
            elif i.identity is None or i.identity != f.identity:
                dropped.append((inv_id, ref_id, "The linked records no longer share the same identity."))
            else:
                valid_links[inv_id] = ref_id

        if not active_ref:
            for r in active_inv:
                results[r.id] = MatchResult("not_compared", no_reference_rows=True, explanation=[
                    f"This batch has no {self.ref_label} rows to compare with."])
            return results, dropped

        ref_index = self._build_indexes(active_ref)
        inv_index = self._build_indexes(active_inv)

        for r in active_inv + active_ref:
            if r.identity is None:
                side_index = ref_index if r.role == "invoice" else inv_index
                results[r.id] = MatchResult("invalid", explanation=[
                    f"Cannot be matched until corrected: {_join(r.identity_problems)}."],
                    hints=self.hints_for(r, side_index))

        inv_groups: dict[tuple, list[EvaluatedRecord]] = defaultdict(list)
        ref_groups: dict[tuple, list[EvaluatedRecord]] = defaultdict(list)
        for r in active_inv:
            if r.identity is not None:
                inv_groups[r.identity].append(r)
        for r in active_ref:
            if r.identity is not None:
                ref_groups[r.identity].append(r)

        used_refs: set[int] = set()
        linked_inv: set[int] = set()
        for inv_id, ref_id in valid_links.items():
            results[inv_id], results[ref_id] = self.compare(by_id[inv_id], by_id[ref_id], "manual_link")
            used_refs.add(ref_id)
            linked_inv.add(inv_id)

        for key, group in inv_groups.items():
            refs_all = ref_groups.get(key, [])
            refs_free = [f for f in refs_all if f.id not in used_refs]
            unlinked = [r for r in group if r.id not in linked_inv]
            if not unlinked:
                continue
            if len(group) > 1:
                for r in unlinked:
                    others = _join([o.label for o in group if o.id != r.id])
                    results[r.id] = MatchResult("ambiguous", candidates=[f.id for f in refs_free], explanation=[
                        f"{len(group)} uploaded invoices share this {self.identity_text} (also {others}). "
                        f"Exclude the duplicate, or link one invoice to a {self.ref_label} row."])
                for f in refs_free:
                    results[f.id] = MatchResult("ambiguous", candidates=[r.id for r in unlinked], explanation=[
                        f"More than one uploaded invoice has this {self.identity_text} "
                        f"({_join([r.label for r in unlinked])}). It is not paired until a reviewer resolves the duplicate."])
                    used_refs.add(f.id)
                continue
            r = unlinked[0]
            if len(refs_free) == 1:
                f = refs_free[0]
                results[r.id], results[f.id] = self.compare(r, f, "identity")
                used_refs.add(f.id)
            elif not refs_free:
                if refs_all:
                    taken = _join([f.label for f in refs_all])
                    explanation = [f"The {self.ref_label} row with this {self.identity_text} ({taken}) is linked to "
                                   f"another invoice by a reviewer."]
                else:
                    explanation = [f"No {self.ref_label} row has this {self.identity_text}."]
                results[r.id] = MatchResult("missing_from_reference", explanation=explanation,
                                            hints=self.hints_for(r, ref_index))
            else:
                rows = _join([f.label for f in refs_free])
                results[r.id] = MatchResult("ambiguous", candidates=[f.id for f in refs_free], explanation=[
                    f"{len(refs_free)} {self.ref_label} rows share this {self.identity_text} ({rows}). "
                    f"Link the correct row; amounts are not used to choose."])
                for f in refs_free:
                    results[f.id] = MatchResult("ambiguous", candidates=[r.id], explanation=[
                        f"{len(refs_free)} {self.ref_label} rows share this {self.identity_text}; "
                        f"{r.label} could belong to any of them."])
                    used_refs.add(f.id)

        for f in active_ref:
            if f.id in results:
                continue
            siblings = [o for o in ref_groups.get(f.identity, []) if o.id != f.id]
            paired = [s for s in siblings if s.id in results and results[s.id].partner_id]
            if paired:
                explanation = [
                    f"The uploaded invoice with this {self.identity_text} is paired with "
                    f"{_join([s.label for s in paired])}, so this row has no invoice of its own. "
                    f"It may be a repeated register entry."]
            else:
                explanation = [f"No uploaded invoice has this {self.identity_text}."]
            results[f.id] = MatchResult("no_invoice", explanation=explanation,
                                        hints=self.hints_for(f, inv_index))
        return results, dropped


def match_records(records: list[EvaluatedRecord], template: Template, links: dict[int, int]):
    return Matcher(template).run(records, links)
