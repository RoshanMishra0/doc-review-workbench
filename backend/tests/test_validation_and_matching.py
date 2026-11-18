from decimal import Decimal

from app.matching import match_records
from app.validation import evaluate_batch

from .conftest import make_input


def run(template, inputs, links=None):
    evaluated = evaluate_batch(inputs, template)
    results, dropped = match_records(evaluated, template, links or {})
    return {e.id: e for e in evaluated}, results, dropped


def categories(ev):
    return sorted({c.category for c in ev.issues})


class TestValidation:
    def test_arithmetic_tolerance_boundary(self, template):
        # Template tolerance is 0.01: a 0.01 difference passes, 0.02 fails.
        within = make_input(1, net="100.00", tax="18.00", total="118.01")
        beyond = make_input(2, number="INV-2", net="100.00", tax="18.00", total="118.02")
        exact = make_input(3, number="INV-3", net="0.10", tax="0.20", total="0.30")
        ev, _, _ = run(template, [within, beyond, exact])
        assert "arithmetic" not in categories(ev[1])
        assert "arithmetic" in categories(ev[2])
        assert "arithmetic" not in categories(ev[3])
        msg = next(c.message for c in ev[2].issues if c.category == "arithmetic")
        assert "difference ₹0.02" in msg

    def test_amounts_are_decimal(self, template):
        ev, _, _ = run(template, [make_input(1)])
        assert isinstance(ev[1].typed("total_amount"), Decimal)

    def test_required_and_unreadable_values(self, template):
        rec = make_input(1, tax=None, date="31/02/2025", net="12.345")
        ev, _, _ = run(template, [rec])
        cats = categories(ev[1])
        assert {"missing_required", "invalid_date", "invalid_amount"} <= set(cats)
        assert ev[1].validation_status == "failed"
        # Arithmetic cannot be checked with a missing tax amount; it is reported as not checked, not passed.
        arith = [c for c in ev[1].checks if c.rule_id == "net_plus_tax_equals_total"]
        assert arith and arith[0].status == "not_checked"

    def test_negative_amount_not_allowed(self, template):
        ev, _, _ = run(template, [make_input(1, net="-100.00", tax="-18.00", total="-118.00")])
        assert "invalid_amount" in categories(ev[1])

    def test_currency_presence_and_consistency(self, template):
        missing = make_input(1, currency=None)
        unsupported = make_input(2, number="INV-2", currency="JPY")
        inconsistent = make_input(3, number="INV-3", currency="INR", total="USD 118.00")
        ev, _, _ = run(template, [missing, unsupported, inconsistent])
        assert "missing_required" in categories(ev[1])
        assert "currency" in categories(ev[2])
        assert "currency" in categories(ev[3])

    def test_duplicate_detection_uses_identity_fields(self, template):
        a = make_input(1, supplier="Quillmark Stationers", number="QS-0091")
        b = make_input(2, supplier="QUILLMARK STATIONERS", number="qs-0091")
        c = make_input(3, supplier="Quillmark Stationers", number="QS-0091", currency="USD")  # different currency
        d = make_input(4, supplier="Quillmark Stationers", number="QS-091")  # leading zero differs
        ev, _, _ = run(template, [a, b, c, d])
        assert "duplicate" in categories(ev[1]) and "duplicate" in categories(ev[2])
        assert "duplicate" not in categories(ev[3])
        assert "duplicate" not in categories(ev[4])

    def test_excluded_record_is_not_a_duplicate_partner(self, template):
        a = make_input(1)
        b = make_input(2, excluded=True)
        ev, _, _ = run(template, [a, b])
        assert "duplicate" not in categories(ev[1])


class TestMatching:
    def test_clean_match(self, template):
        _, res, _ = run(template, [make_input(1), make_input(2, role="reference", supplier="ACME TRADERS LTD")])
        assert res[1].status == "matched" and res[1].partner_id == 2
        assert res[2].status == "matched" and res[2].partner_id == 1

    def test_same_amount_different_invoice_is_never_matched(self, template):
        inv = make_input(1, number="000462", total="23100.00", net="22000.00", tax="1100.00")
        ref = make_input(2, role="reference", number="000463", total="23100.00", net="22000.00", tax="1100.00")
        _, res, _ = run(template, [inv, ref])
        assert res[1].status == "missing_from_reference"
        assert res[2].status == "no_invoice"
        assert res[1].partner_id is None and res[2].partner_id is None

    def test_amount_mismatch_is_explained(self, template):
        inv = make_input(1, net="10593.18", tax="1906.82", total="12500.00")
        ref = make_input(2, role="reference", net="10211.86", tax="1838.14", total="12050.00")
        _, res, _ = run(template, [inv, ref])
        assert res[1].status == "mismatched"
        text = " ".join(res[1].explanation)
        assert "Invoice total amount is ₹12,500.00; purchase register total amount is ₹12,050.00" in text

    def test_match_tolerance_boundary(self, template):
        inv = make_input(1, total="118.01")
        ref = make_input(2, role="reference", total="118.00")
        inv2 = make_input(3, number="INV-2", total="118.02")
        ref2 = make_input(4, role="reference", number="INV-2", total="118.00")
        _, res, _ = run(template, [inv, ref, inv2, ref2])
        assert res[1].status == "matched"
        assert any("within the tolerance" in e for e in res[1].explanation)
        assert res[3].status == "mismatched"

    def test_multiple_reference_candidates_stay_ambiguous(self, template):
        inv = make_input(1)
        r1 = make_input(2, role="reference")
        r2 = make_input(3, role="reference", date="06/03/2025")
        _, res, _ = run(template, [inv, r1, r2])
        assert res[1].status == "ambiguous" and set(res[1].candidates) == {2, 3}
        assert res[2].status == res[3].status == "ambiguous"

    def test_duplicate_invoices_do_not_share_one_reference_row(self, template):
        a, b = make_input(1), make_input(2)
        ref = make_input(3, role="reference")
        _, res, _ = run(template, [a, b, ref])
        assert res[1].status == res[2].status == "ambiguous"
        assert res[3].status == "ambiguous"
        assert res[1].partner_id is None and res[2].partner_id is None

    def test_manual_link_resolves_ambiguity_and_row_is_not_reused(self, template):
        inv = make_input(1)
        r1 = make_input(2, role="reference")
        r2 = make_input(3, role="reference")
        _, res, dropped = run(template, [inv, r1, r2], links={1: 2})
        assert not dropped
        assert res[1].status == "matched" and res[1].partner_id == 2 and res[1].method == "manual_link"
        assert res[3].status == "no_invoice"

    def test_link_dropped_when_identity_changes(self, template):
        inv = make_input(1, number="INV-9")
        ref = make_input(2, role="reference", number="INV-1")
        _, res, dropped = run(template, [inv, ref], links={1: 2})
        assert dropped and res[1].status == "missing_from_reference"

    def test_unmatched_on_both_sides(self, template):
        _, res, _ = run(template, [make_input(1, number="A-1"), make_input(2, role="reference", number="B-2")])
        assert res[1].status == "missing_from_reference"
        assert res[2].status == "no_invoice"

    def test_no_fuzzy_supplier_matching_but_hint_given(self, template):
        inv = make_input(1, supplier="Kestrel Logistic Services")
        ref = make_input(2, role="reference", supplier="Kestrel Logistics Services")
        _, res, _ = run(template, [inv, ref])
        assert res[1].status == "missing_from_reference"
        assert res[1].hints and "supplier name" in res[1].hints[0]

    def test_currency_must_agree(self, template):
        inv = make_input(1, currency="USD")
        ref = make_input(2, role="reference", currency="INR")
        _, res, _ = run(template, [inv, ref])
        assert res[1].status == "missing_from_reference"
        assert any("currency" in h for h in res[1].hints)

    def test_invalid_identity_needs_correction(self, template):
        inv = make_input(1, currency=None)
        ref = make_input(2, role="reference")
        _, res, _ = run(template, [inv, ref])
        assert res[1].status == "invalid"
        assert res[2].status == "no_invoice"
        assert res[1].hints  # points at the register row that agrees on supplier and number

    def test_invalid_compare_field_blocks_match(self, template):
        inv = make_input(1, tax=None)
        ref = make_input(2, role="reference")
        _, res, _ = run(template, [inv, ref])
        assert res[1].status == "invalid" and res[2].status == "partner_invalid"

    def test_no_reference_rows(self, template):
        _, res, _ = run(template, [make_input(1)])
        assert res[1].status == "not_compared" and res[1].no_reference_rows

    def test_date_mismatch(self, template):
        _, res, _ = run(template, [make_input(1, date="12/03/2025"),
                                   make_input(2, role="reference", date="13/03/2025")])
        assert res[1].status == "mismatched"
        assert "12 Mar 2025" in " ".join(res[1].explanation)
