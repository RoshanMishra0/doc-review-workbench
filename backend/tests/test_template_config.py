import copy
import json

import pytest
from pydantic import ValidationError

from app.settings import TEMPLATE_DIR
from app.template_config import Template

BASE = json.loads((TEMPLATE_DIR / "supplier_invoice.json").read_text(encoding="utf-8"))


def variant(mutate):
    data = copy.deepcopy(BASE)
    mutate(data)
    return data


def test_shipped_template_is_valid():
    t = Template.model_validate(BASE)
    assert t.matching.identity_fields == ["supplier_name", "invoice_number", "currency"]


@pytest.mark.parametrize("mutate", [
    lambda d: d["validation_rules"].append({"id": "x", "type": "python_expression", "label": "x", "code": "1"}),
    lambda d: d["validation_rules"][0]["fields"].append("no_such_field"),
    lambda d: d["validation_rules"][3].update(tolerance="-0.01"),
    lambda d: d["validation_rules"][3].update(addends=["supplier_name"]),
    lambda d: d["matching"].update(identity_fields=["supplier_name", "nope"]),
    lambda d: d["matching"].update(identity_fields=[]),
    lambda d: d["fields"][1]["aliases"].append("vendor"),  # alias already used by supplier_name
    lambda d: d["currency"]["markers"].update({"$": "USD"}),
    lambda d: d["currency"].update(default="JPY"),
    lambda d: d["dates"].update(default_order="DDMMYY"),
    lambda d: d.update(unexpected_key=True),
])
def test_invalid_templates_are_rejected(mutate):
    with pytest.raises(ValidationError):
        Template.model_validate(variant(mutate))
