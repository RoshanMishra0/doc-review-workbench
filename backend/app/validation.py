"""Field evaluation and rule checks. Pure functions; no database access.

Only the rule types defined in ``template_config`` are implemented here.
The checks report completeness, readability, arithmetic and duplicates.
They make no claim about tax compliance, fraud, payment status or
accounting correctness.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from .normalization import (
    collapse_ws,
    decimal_places,
    format_money,
    identifier_key,
    normalize_currency,
    parse_date,
    parse_money,
    short_date,
)
from .template_config import (
    CurrencyAllowedRule,
    CurrencyConsistencyRule,
    DateValidRule,
    DuplicateIdentityRule,
    MoneyValidRule,
    RequiredRule,
    SumEqualsRule,
    Template,
)


@dataclass
class RecordInput:
    id: int
    role: str
    values: dict[str, str | None]  # current values: extracted, or the latest correction
    original: dict[str, str | None]  # values exactly as extracted
    kinds: dict[str, str]  # text | number | date_cell | source_default
    corrected: set[str]
    date_order: str
    excluded: bool
    label: str  # e.g. "quillmark_QS-0091.pdf" or "purchase_register.xlsx, row 7"
    notes: list[str] = field(default_factory=list)


@dataclass
class FieldState:
    name: str
    label: str
    type: str
    original: str | None
    current: str | None
    status: str  # extracted | missing | user_corrected | source_default
    display: str | None = None
    normalized: str | None = None
    error: str | None = None
    key: str | None = None
    marker_currency: str | None = None
    ambiguous: bool = False
    value: Any = None  # typed value; not serialized

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("value")
        return d


@dataclass
class Check:
    rule_id: str
    rule_type: str
    label: str
    status: str  # passed | issue | not_checked
    severity: str
    message: str
    field: str | None = None
    category: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvaluatedRecord:
    input: RecordInput
    fields: dict[str, FieldState]
    checks: list[Check] = field(default_factory=list)
    identity: tuple | None = None
    identity_parts: list[tuple[str, str | None, str | None]] = field(default_factory=list)  # (label, key, display)
    identity_problems: list[str] = field(default_factory=list)

    @property
    def id(self) -> int:
        return self.input.id

    @property
    def role(self) -> str:
        return self.input.role

    @property
    def excluded(self) -> bool:
        return self.input.excluded

    @property
    def label(self) -> str:
        return self.input.label

    def typed(self, name: str):
        return self.fields[name].value

    @property
    def issues(self) -> list[Check]:
        return [c for c in self.checks if c.status == "issue"]

    @property
    def validation_status(self) -> str:
        issues = self.issues
        if any(c.severity == "error" for c in issues):
            return "failed"
        if issues:
            return "warnings"
        return "passed"


def _money_text(value: Decimal, currency: str | None, template: Template) -> str:
    c = template.currency
    return format_money(value, currency, c.symbols, c.minor_units, c.grouping)


def evaluate_fields(rec: RecordInput, template: Template) -> dict[str, FieldState]:
    markers = template.currency.markers
    states: dict[str, FieldState] = {}
    for f in template.fields:
        current = rec.values.get(f.name)
        if current is not None and not str(current).strip():
            current = None
        if f.name in rec.corrected:
            status = "user_corrected"
        elif current is None:
            status = "missing"
        elif rec.kinds.get(f.name) == "source_default":
            status = "source_default"
        else:
            status = "extracted"
        fs = FieldState(f.name, f.label, f.type, rec.original.get(f.name), current, status)
        if current is not None:
            if f.type in ("party", "text"):
                fs.display = collapse_ws(current)
                fs.normalized = fs.display
                fs.value = fs.display
                if f.type == "party":
                    fs.key = template.party_key(current)
            elif f.type == "identifier":
                fs.display = current.strip()
                fs.normalized = fs.display
                fs.value = fs.display
                fs.key = identifier_key(current)
            elif f.type == "date":
                # Spreadsheet date cells are stored as ISO text and are unambiguous.
                order = "YMD" if rec.kinds.get(f.name) == "date_cell" and f.name not in rec.corrected else rec.date_order
                parsed = parse_date(current, order)
                if parsed.ok:
                    fs.value = parsed.value
                    fs.normalized = parsed.value.isoformat()
                    fs.display = short_date(parsed.value)
                else:
                    fs.error = parsed.error
                    fs.ambiguous = parsed.ambiguous
            elif f.type == "currency":
                code, err = normalize_currency(current, markers)
                fs.value, fs.error = code, err
                fs.normalized = fs.display = code
            elif f.type == "money":
                parsed = parse_money(current, markers)
                if parsed.ok:
                    fs.value = parsed.value
                    fs.normalized = format(parsed.value, "f")
                    fs.marker_currency = parsed.currency
                else:
                    fs.error = parsed.error
                    fs.marker_currency = parsed.currency
        states[f.name] = fs
    currency_name = template.currency_field
    record_currency = states[currency_name].value if currency_name else None
    for fs in states.values():
        if fs.type == "money" and fs.value is not None:
            fs.display = _money_text(fs.value, record_currency or fs.marker_currency, template)
    return states


def _applies(rule, role: str) -> bool:
    return role in rule.applies_to


def _identity(rec_fields: dict[str, FieldState], names: list[str], template: Template):
    parts: list[tuple[str, str | None, str | None]] = []
    problems: list[str] = []
    for name in names:
        fs = rec_fields[name]
        if fs.type in ("party", "identifier"):
            key = fs.key
        elif fs.type == "currency":
            key = fs.value if fs.value in template.currency.allowed else None
        elif fs.type == "date":
            key = fs.normalized
        else:
            key = fs.display.casefold() if fs.display else None
        parts.append((fs.label, key, fs.display))
        if key is None:
            if fs.current is None:
                problems.append(f"{fs.label.lower()} is missing")
            elif fs.error:
                problems.append(f"{fs.label.lower()} is invalid")
            else:
                problems.append(f"{fs.label.lower()} '{fs.display}' is not supported")
    identity = tuple(p[1] for p in parts) if not problems else None
    return identity, parts, problems


def check_record(rec: EvaluatedRecord, template: Template) -> list[Check]:
    checks: list[Check] = []
    f = rec.fields
    currency_name = template.currency_field
    record_currency = f[currency_name].value if currency_name else None
    for rule in template.validation_rules:
        if not _applies(rule, rec.role):
            continue
        base = {"rule_id": rule.id, "rule_type": rule.type, "label": rule.label}
        if isinstance(rule, RequiredRule):
            missing = [n for n in rule.fields if f[n].current is None]
            for n in missing:
                checks.append(Check(**base, status="issue", severity=rule.severity,
                                    message=f"{f[n].label} is missing.", field=n, category="missing_required"))
            if not missing:
                checks.append(Check(**base, status="passed", severity=rule.severity, message="All required values are present."))
        elif isinstance(rule, DateValidRule):
            bad = False
            for n in rule.fields:
                fs = f[n]
                if fs.current is None:
                    continue
                if fs.error:
                    bad = True
                    checks.append(Check(**base, status="issue", severity=rule.severity, message=fs.error, field=n,
                                        category="ambiguous_date" if fs.ambiguous else "invalid_date"))
            if not bad:
                present = [n for n in rule.fields if f[n].current is not None]
                if present:
                    shown = ", ".join(f"{f[n].label}: {f[n].display}" for n in present)
                    checks.append(Check(**base, status="passed", severity=rule.severity, message=f"Read as {shown}."))
                else:
                    checks.append(Check(**base, status="not_checked", severity=rule.severity, message="No date to check."))
        elif isinstance(rule, MoneyValidRule):
            bad = False
            for n in rule.fields:
                fs = f[n]
                if fs.current is None:
                    continue
                if fs.error:
                    bad = True
                    checks.append(Check(**base, status="issue", severity=rule.severity,
                                        message=f"{fs.label}: {fs.error}", field=n, category="invalid_amount"))
                    continue
                value: Decimal = fs.value
                if value < 0 and not rule.allow_negative:
                    bad = True
                    checks.append(Check(**base, status="issue", severity=rule.severity,
                                        message=f"{fs.label} is negative ({fs.display}); this template does not allow negative amounts.",
                                        field=n, category="invalid_amount"))
                code = record_currency or fs.marker_currency
                places = template.currency.minor_units.get(code) if code else None
                if places is not None and decimal_places(value) > places:
                    bad = True
                    checks.append(Check(**base, status="issue", severity=rule.severity,
                                        message=f"{fs.label} '{fs.current}' has {decimal_places(value)} decimal places; {code} uses {places}.",
                                        field=n, category="invalid_amount"))
            if not bad:
                checks.append(Check(**base, status="passed", severity=rule.severity, message="Amounts are valid."))
        elif isinstance(rule, SumEqualsRule):
            names = [*rule.addends, rule.total]
            unusable = [f[n].label.lower() for n in names if f[n].value is None]
            if unusable:
                checks.append(Check(**base, status="not_checked", severity=rule.severity,
                                    message=f"Not checked because {', '.join(unusable)} is missing or invalid."))
                continue
            total = sum((f[n].value for n in rule.addends), Decimal("0"))
            stated = f[rule.total].value
            diff = stated - total
            code = record_currency
            parts = " plus ".join(f"{f[n].label.lower()} {_money_text(f[n].value, code, template)}" for n in rule.addends)
            if abs(diff) <= rule.tolerance:
                note = "" if diff == 0 else f" (difference {_money_text(abs(diff), code, template)}, within tolerance)"
                checks.append(Check(**base, status="passed", severity=rule.severity,
                                    message=f"{parts[0].upper() + parts[1:]} equals {f[rule.total].label.lower()} "
                                            f"{_money_text(stated, code, template)}{note}."))
            else:
                checks.append(Check(**base, status="issue", severity=rule.severity, field=rule.total, category="arithmetic",
                                    message=f"{parts[0].upper() + parts[1:]} is {_money_text(total, code, template)}, but "
                                            f"{f[rule.total].label.lower()} is {_money_text(stated, code, template)} "
                                            f"(difference {_money_text(abs(diff), code, template)}; tolerance "
                                            f"{_money_text(rule.tolerance, code, template)})."))
        elif isinstance(rule, CurrencyAllowedRule):
            fs = f[rule.field]
            if fs.current is None:
                checks.append(Check(**base, status="not_checked", severity=rule.severity,
                                    message="Not checked because the currency is missing."))
            elif fs.error:
                checks.append(Check(**base, status="issue", severity=rule.severity, message=fs.error, field=rule.field,
                                    category="currency"))
            elif fs.value not in template.currency.allowed:
                checks.append(Check(**base, status="issue", severity=rule.severity, field=rule.field, category="currency",
                                    message=f"Currency {fs.value} is not in the configured list "
                                            f"({', '.join(template.currency.allowed)})."))
            else:
                checks.append(Check(**base, status="passed", severity=rule.severity, message=f"Currency is {fs.value}."))
        elif isinstance(rule, CurrencyConsistencyRule):
            code = f[rule.currency_field].value
            conflicts = []
            for n in rule.amount_fields:
                marker = f[n].marker_currency
                if marker and code and marker != code:
                    conflicts.append(n)
                    checks.append(Check(**base, status="issue", severity=rule.severity, field=n, category="currency",
                                        message=f"{f[n].label} is printed in {marker}, but the record currency is {code}."))
            if not conflicts:
                printed = [n for n in rule.amount_fields if f[n].marker_currency]
                msg = "Amounts printed with a currency use the record currency." if printed else \
                    "No amount carries its own currency marker."
                checks.append(Check(**base, status="passed", severity=rule.severity, message=msg))
    for note in rec.input.notes:
        checks.append(Check("source_note", "note", "Source note", "issue", "warning", note, category="source_note"))
    return checks


def _dup_key(fields: dict[str, FieldState], names: list[str]) -> tuple | None:
    parts = []
    for n in names:
        fs = fields[n]
        if fs.type in ("party", "identifier"):
            k = fs.key
        elif fs.type == "currency":
            k = fs.value
        elif fs.type == "date":
            k = fs.normalized
        else:
            k = fs.display.casefold() if fs.display else None
        if k is None:
            return None
        parts.append(k)
    return tuple(parts)


def duplicate_checks(records: list[EvaluatedRecord], template: Template) -> None:
    for rule in template.validation_rules:
        if not isinstance(rule, DuplicateIdentityRule):
            continue
        labels = [template.label(n).lower() for n in rule.fields]
        described = ", ".join(labels[:-1]) + (" and " if len(labels) > 1 else "") + labels[-1]
        groups: dict[tuple, list[EvaluatedRecord]] = defaultdict(list)
        base = {"rule_id": rule.id, "rule_type": rule.type, "label": rule.label}
        for rec in records:
            if not _applies(rule, rec.role):
                continue
            key = _dup_key(rec.fields, rule.fields)
            if rec.excluded:
                continue
            if key is None:
                rec.checks.append(Check(**base, status="not_checked", severity=rule.severity,
                                        message="Not checked because part of the identity is missing or invalid."))
                continue
            groups[key].append(rec)
        for members in groups.values():
            for rec in members:
                others = [m for m in members if m.id != rec.id]
                if others:
                    names = "; ".join(f"record #{o.id} ({o.label})" for o in others)
                    rec.checks.append(Check(**base, status="issue", severity=rule.severity, category="duplicate",
                                            field=rule.fields[1] if len(rule.fields) > 1 else rule.fields[0],
                                            message=f"Possible duplicate: {names} has the same {described}."))
                else:
                    rec.checks.append(Check(**base, status="passed", severity=rule.severity,
                                            message=f"No other uploaded record has the same {described}."))


def evaluate_batch(inputs: list[RecordInput], template: Template) -> list[EvaluatedRecord]:
    evaluated: list[EvaluatedRecord] = []
    for rec in inputs:
        fields = evaluate_fields(rec, template)
        ev = EvaluatedRecord(rec, fields)
        ev.identity, ev.identity_parts, ev.identity_problems = _identity(fields, template.matching.identity_fields, template)
        ev.checks = check_record(ev, template)
        evaluated.append(ev)
    duplicate_checks(evaluated, template)
    return evaluated


def date_text(value: date | None) -> str | None:
    return short_date(value) if value else None
