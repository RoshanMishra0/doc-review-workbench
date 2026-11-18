from datetime import date
from decimal import Decimal

import pytest

from app.normalization import (
    format_money,
    identifier_key,
    normalize_header,
    parse_date,
    parse_money,
)

MARKERS = {"₹": "INR", "RS.": "INR", "RS": "INR", "INR": "INR", "USD": "USD", "US$": "USD", "EUR": "EUR"}


class TestDates:
    def test_chosen_order_decides_numeric_dates(self):
        assert parse_date("03/04/2025", "DMY").value == date(2025, 4, 3)
        assert parse_date("03/04/2025", "MDY").value == date(2025, 3, 4)

    def test_unspecified_order_rejects_ambiguous_dates(self):
        result = parse_date("03/04/2025", "UNSPECIFIED")
        assert result.value is None and result.ambiguous
        assert "3 April 2025" in result.error and "4 March 2025" in result.error

    def test_unspecified_order_accepts_forced_readings(self):
        assert parse_date("25/03/2025", "UNSPECIFIED").value == date(2025, 3, 25)
        assert parse_date("03/25/2025", "UNSPECIFIED").value == date(2025, 3, 25)
        assert parse_date("07/07/2025", "UNSPECIFIED").value == date(2025, 7, 7)

    def test_value_that_does_not_fit_the_chosen_order_is_invalid(self):
        result = parse_date("03/25/2025", "DMY")
        assert result.value is None and "month 25" in result.error

    def test_invalid_calendar_date(self):
        result = parse_date("31/02/2025", "DMY")
        assert result.value is None and "no day 31" in result.error

    def test_iso_and_month_names_are_always_unambiguous(self):
        for order in ("DMY", "MDY", "UNSPECIFIED"):
            assert parse_date("2025-03-05", order).value == date(2025, 3, 5)
            assert parse_date("05 Mar 2025", order).value == date(2025, 3, 5)
            assert parse_date("March 5, 2025", order).value == date(2025, 3, 5)

    def test_two_digit_years_are_rejected(self):
        assert parse_date("05/03/25", "DMY").value is None
        assert parse_date("5 Mar 25", "DMY").value is None

    def test_ymd_order_rejects_day_first_text(self):
        assert parse_date("05/03/2025", "YMD").value is None
        assert parse_date("2025/03/05", "YMD").value == date(2025, 3, 5)

    def test_garbage(self):
        assert parse_date("next tuesday", "DMY").value is None
        assert parse_date("", "DMY").value is None


class TestMoney:
    def test_parses_into_decimal_not_float(self):
        result = parse_money("12,500.10", MARKERS)
        assert isinstance(result.value, Decimal) and result.value == Decimal("12500.10")

    def test_indian_grouping_and_markers(self):
        assert parse_money("₹1,25,000.50", MARKERS).value == Decimal("125000.50")
        r = parse_money("INR 1,100.00", MARKERS)
        assert r.value == Decimal("1100.00") and r.currency == "INR"
        assert parse_money("Rs. 500", MARKERS).currency == "INR"
        assert parse_money("1,200.00 USD", MARKERS).currency == "USD"

    def test_negatives(self):
        assert parse_money("(500.00)", MARKERS).value == Decimal("-500.00")
        assert parse_money("-500.00", MARKERS).value == Decimal("-500.00")
        assert parse_money("INR -500.00", MARKERS).value == Decimal("-500.00")

    @pytest.mark.parametrize("text", ["12.500,00", "1,2,3", "abc", "12 500", "$100", "1.2.3", "INRX 100"])
    def test_invalid_amounts(self, text):
        assert parse_money(text, MARKERS).value is None

    def test_decimal_arithmetic_is_exact(self):
        # 0.1 + 0.2 is not 0.3 in binary floating point; it must be here.
        a = parse_money("0.10", MARKERS).value
        b = parse_money("0.20", MARKERS).value
        assert a + b == Decimal("0.30")

    def test_formatting(self):
        sym = {"INR": "₹", "USD": "US$"}
        units = {"INR": 2, "USD": 2}
        assert format_money(Decimal("12500"), "INR", sym, units, {"INR": "indian"}) == "₹12,500.00"
        assert format_money(Decimal("1250000"), "INR", sym, units, {"INR": "indian"}) == "₹12,50,000.00"
        assert format_money(Decimal("1250000"), "USD", sym, units, {}) == "US$1,250,000.00"


class TestIdentifiersAndNames:
    def test_leading_zeros_are_significant(self):
        assert identifier_key("000457") == "000457"
        assert identifier_key("000457") != identifier_key("457")
        assert identifier_key(" inv-00123 ") == "INV-00123"

    def test_party_key_uses_documented_rules_only(self, template):
        assert template.party_key("Apex Industrial Components Pvt. Ltd.") == template.party_key(
            "Apex Industrial Components Private Limited")
        assert template.party_key("Tarnwood Packaging Co.") == template.party_key("TARNWOOD  PACKAGING CO")
        # Explicit alias from the template configuration
        assert template.party_key("Sablefin Electrical Works") == template.party_key("Sablefin Electricals")
        # No fuzzy matching: a typo stays different
        assert template.party_key("Kestrel Logistic Services") != template.party_key("Kestrel Logistics Services")

    def test_header_normalization(self):
        assert normalize_header("Invoice #") == "invoice no"
        assert normalize_header("Bill No.") == "bill no"
        assert normalize_header("Amount excl. tax") == "amount excl tax"
