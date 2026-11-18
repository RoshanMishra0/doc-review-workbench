"""Workflow template configuration: schema, validation and loading.

A template is a JSON file in ``app/template_configs``. It declares the
canonical fields, aliases, date and currency assumptions, validation rules
(from a fixed set of implemented rule types) and matching keys. Rules are
data, never executable expressions.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

from .normalization import DATE_ORDERS, normalize_header, party_key
from .settings import TEMPLATE_DIR

FieldType = Literal["party", "text", "identifier", "date", "currency", "money"]
Role = Literal["invoice", "reference"]
SourceKind = Literal["pdf", "csv", "xlsx"]
ROLES: tuple[str, ...] = ("invoice", "reference")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoleDef(_Strict):
    label: str
    plural: str
    description: str = ""
    accepts: list[SourceKind]


class FieldDef(_Strict):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,40}$")
    label: str
    type: FieldType
    required: bool = False
    aliases: list[str] = []
    description: str = ""


class _RuleBase(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,60}$")
    label: str
    severity: Literal["error", "warning"] = "error"
    applies_to: list[Role] = ["invoice", "reference"]


class RequiredRule(_RuleBase):
    type: Literal["required"]
    fields: list[str]


class DateValidRule(_RuleBase):
    type: Literal["date_valid"]
    fields: list[str]


class MoneyValidRule(_RuleBase):
    type: Literal["money_valid"]
    fields: list[str]
    allow_negative: bool = False


class SumEqualsRule(_RuleBase):
    type: Literal["sum_equals"]
    addends: list[str]
    total: str
    tolerance: Decimal = Decimal("0")

    @field_validator("tolerance")
    @classmethod
    def _non_negative(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("tolerance must not be negative")
        return v


class CurrencyAllowedRule(_RuleBase):
    type: Literal["currency_allowed"]
    field: str


class CurrencyConsistencyRule(_RuleBase):
    type: Literal["currency_consistency"]
    currency_field: str
    amount_fields: list[str]


class DuplicateIdentityRule(_RuleBase):
    type: Literal["duplicate_identity"]
    fields: list[str]


Rule = Annotated[
    Union[RequiredRule, DateValidRule, MoneyValidRule, SumEqualsRule,
          CurrencyAllowedRule, CurrencyConsistencyRule, DuplicateIdentityRule],
    Field(discriminator="type"),
]


class CompareDef(_Strict):
    field: str
    tolerance: Decimal = Decimal("0")

    @field_validator("tolerance")
    @classmethod
    def _non_negative(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("tolerance must not be negative")
        return v


class MatchingDef(_Strict):
    identity_fields: list[str]
    compare: list[CompareDef]


class DateSettings(_Strict):
    default_order: str = "DMY"

    @field_validator("default_order")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in DATE_ORDERS:
            raise ValueError(f"date order must be one of {DATE_ORDERS}")
        return v


class CurrencySettings(_Strict):
    default: str | None = None
    allowed: list[str]
    symbols: dict[str, str] = {}
    markers: dict[str, str] = {}
    minor_units: dict[str, int] = {}
    grouping: dict[str, Literal["standard", "indian"]] = {}

    @model_validator(mode="after")
    def _codes(self) -> "CurrencySettings":
        for code in self.allowed + list(self.markers.values()) + ([self.default] if self.default else []):
            if len(code) != 3 or not code.isalpha() or not code.isupper():
                raise ValueError(f"currency code {code!r} must be three upper-case letters")
        if self.default and self.default not in self.allowed:
            raise ValueError("default currency must be in the allowed list")
        if "$" in self.markers:
            raise ValueError("'$' is ambiguous between currencies and cannot be a marker")
        return self


class PartyNormalization(_Strict):
    casefold: bool = True
    replace_ampersand: bool = True
    strip_punctuation: bool = True
    legal_suffixes: list[str] = []
    aliases: dict[str, list[str]] = {}


class Template(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,60}$")
    version: int
    name: str
    description: str = ""
    synthetic_note: str = ""
    roles: dict[Role, RoleDef]
    fields: list[FieldDef]
    dates: DateSettings = DateSettings()
    currency: CurrencySettings
    party_normalization: PartyNormalization = PartyNormalization()
    validation_rules: list[Rule]
    matching: MatchingDef
    pdf_layouts: list[str] = []
    summary_fields: list[str] = []  # columns for the Records table; derived from field types if empty

    _alias_cache: dict[str, str] = PrivateAttr(default_factory=dict)

    # ------------------------------------------------------------ lookups
    def field(self, name: str) -> FieldDef:
        for f in self.fields:
            if f.name == name:
                return f
        raise KeyError(name)

    @property
    def field_names(self) -> list[str]:
        return [f.name for f in self.fields]

    def label(self, name: str) -> str:
        return self.field(name).label

    def party_alias_table(self) -> dict[str, str]:
        """alias key -> canonical key, both normalized with the same rules."""
        pn = self.party_normalization
        table: dict[str, str] = {}
        for canonical, alternatives in pn.aliases.items():
            canonical_key = self._party_key_raw(canonical)
            for alt in alternatives:
                table[self._party_key_raw(alt)] = canonical_key
        return table

    def _party_key_raw(self, text: str) -> str:
        pn = self.party_normalization
        return party_key(text, casefold=pn.casefold, ampersand=pn.replace_ampersand,
                         punctuation=pn.strip_punctuation, legal_suffixes=tuple(pn.legal_suffixes))

    def party_key(self, text: str) -> str:
        pn = self.party_normalization
        return party_key(text, casefold=pn.casefold, ampersand=pn.replace_ampersand,
                         punctuation=pn.strip_punctuation, legal_suffixes=tuple(pn.legal_suffixes),
                         aliases=self._alias_cache)

    def alias_index(self) -> dict[str, str]:
        """normalized column heading -> field name."""
        index: dict[str, str] = {}
        for f in self.fields:
            for alias in [f.name, f.label, *f.aliases]:
                index.setdefault(normalize_header(alias), f.name)
        return index

    # ------------------------------------------------------------ validation
    @model_validator(mode="after")
    def _check_references(self) -> "Template":
        names = [f.name for f in self.fields]
        if len(set(names)) != len(names):
            raise ValueError("field names must be unique")
        by_name = {f.name: f for f in self.fields}
        seen_alias: dict[str, str] = {}
        for f in self.fields:
            for alias in [f.name, f.label, *f.aliases]:
                key = normalize_header(alias)
                owner = seen_alias.get(key)
                if owner and owner != f.name:
                    raise ValueError(f"alias {alias!r} is used by both {owner} and {f.name}")
                seen_alias[key] = f.name
        if set(self.roles) != set(ROLES):
            raise ValueError(f"template must define roles {ROLES}")

        def need(name: str, types: tuple[str, ...] | None, where: str) -> None:
            if name not in by_name:
                raise ValueError(f"{where} refers to unknown field {name!r}")
            if types and by_name[name].type not in types:
                raise ValueError(f"{where} needs a field of type {types}, but {name!r} is {by_name[name].type}")

        rule_ids = [r.id for r in self.validation_rules]
        if len(set(rule_ids)) != len(rule_ids):
            raise ValueError("validation rule ids must be unique")
        for rule in self.validation_rules:
            where = f"rule {rule.id!r}"
            if isinstance(rule, RequiredRule):
                for n in rule.fields:
                    need(n, None, where)
            elif isinstance(rule, DateValidRule):
                for n in rule.fields:
                    need(n, ("date",), where)
            elif isinstance(rule, MoneyValidRule):
                for n in rule.fields:
                    need(n, ("money",), where)
            elif isinstance(rule, SumEqualsRule):
                for n in [*rule.addends, rule.total]:
                    need(n, ("money",), where)
            elif isinstance(rule, CurrencyAllowedRule):
                need(rule.field, ("currency",), where)
            elif isinstance(rule, CurrencyConsistencyRule):
                need(rule.currency_field, ("currency",), where)
                for n in rule.amount_fields:
                    need(n, ("money",), where)
            elif isinstance(rule, DuplicateIdentityRule):
                for n in rule.fields:
                    need(n, ("party", "identifier", "currency", "text", "date"), where)
        if not self.matching.identity_fields:
            raise ValueError("matching.identity_fields must not be empty")
        for n in self.matching.identity_fields:
            need(n, ("party", "identifier", "currency", "text"), "matching.identity_fields")
        for c in self.matching.compare:
            need(c.field, None, "matching.compare")
            if c.field in self.matching.identity_fields:
                raise ValueError(f"field {c.field!r} is both an identity and a compare field")
        for n in self.summary_fields:
            need(n, None, "summary_fields")
        money_fields = [f for f in self.fields if f.type == "money"]
        if money_fields and not any(f.type == "currency" for f in self.fields):
            raise ValueError("money fields need a currency field")
        return self

    def model_post_init(self, __context: object) -> None:
        self._alias_cache = self.party_alias_table()

    @property
    def summary_columns(self) -> list[str]:
        if self.summary_fields:
            return list(self.summary_fields)
        cols: list[str] = []
        for wanted in ("party", "identifier", "date"):
            hit = next((f.name for f in self.fields if f.type == wanted), None)
            if hit:
                cols.append(hit)
        money = [f.name for f in self.fields if f.type == "money"]
        if money:
            cols.append(money[-1])
        return cols or [f.name for f in self.fields[:4]]

    @property
    def currency_field(self) -> str | None:
        for f in self.fields:
            if f.type == "currency":
                return f.name
        return None

    def summary(self) -> dict:
        """Plain description used by the API and the Import screen."""
        rules = []
        for r in self.validation_rules:
            item = r.model_dump(mode="json")
            rules.append(item)
        return {
            "id": self.id,
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "synthetic_note": self.synthetic_note,
            "roles": {k: v.model_dump() for k, v in self.roles.items()},
            "fields": [f.model_dump() for f in self.fields],
            "dates": self.dates.model_dump(),
            "currency": self.currency.model_dump(),
            "party_normalization": self.party_normalization.model_dump(),
            "validation_rules": rules,
            "matching": self.matching.model_dump(mode="json"),
            "pdf_layouts": self.pdf_layouts,
            "summary_columns": [{"name": n, "label": self.label(n)} for n in self.summary_columns],
        }


def load_template_file(path: Path) -> Template:
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    template = Template.model_validate(data)
    from .extraction.registry import PDF_EXTRACTORS  # local import avoids a cycle

    unknown = [layout for layout in template.pdf_layouts if layout not in PDF_EXTRACTORS]
    if unknown:
        raise ValueError(f"{path.name}: unknown PDF layouts {unknown}")
    return template


def template_dir() -> Path:
    """Folder of template JSON files. DRW_TEMPLATE_DIR overrides the shipped folder."""
    return Path(os.environ.get("DRW_TEMPLATE_DIR") or TEMPLATE_DIR)


def load_templates() -> dict[str, Template]:
    return _load_templates(str(template_dir().resolve()))


@lru_cache(maxsize=8)
def _load_templates(directory: str) -> dict[str, Template]:
    templates: dict[str, Template] = {}
    for path in sorted(Path(directory).glob("*.json")):
        t = load_template_file(path)
        if t.id in templates:
            raise ValueError(f"duplicate template id {t.id}")
        templates[t.id] = t
    return templates


def get_template(template_id: str) -> Template:
    templates = load_templates()
    if template_id not in templates:
        raise KeyError(template_id)
    return templates[template_id]
