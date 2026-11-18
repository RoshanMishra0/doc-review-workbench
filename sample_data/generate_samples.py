"""Generate the synthetic demo dataset.

All companies, people, addresses, tax IDs and amounts are fictional.
Run from the repository root with the backend virtual environment:

    backend/.venv/Scripts/python sample_data/generate_samples.py     (Windows)
    backend/.venv/bin/python sample_data/generate_samples.py         (macOS/Linux)

Outputs (committed to the repository):
    sample_data/harbor_lane/invoices/*.pdf
    sample_data/harbor_lane/purchase_register.xlsx
    sample_data/meridian/supplier_invoice_listing.csv
    sample_data/meridian/purchase_register.csv
    sample_data/manifest.json           which files each sample set loads, and their roles
    sample_data/expected_outcomes.json  what the pipeline should report (used by tests only)

The app never reads expected_outcomes.json. It exists so tests can check
that real extraction and matching produce the documented results.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from fpdf import FPDF
from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
FIXED_TIME = datetime(2025, 3, 31, 9, 0, 0, tzinfo=timezone.utc)
SYNTHETIC_FOOTER = "SYNTHETIC DOCUMENT - fictional company and data, generated for demonstration only."

BUYER_A = "Harbor Lane Supplies Pvt Ltd"
BUYER_A_ADDRESS = "14 Dockside Road, Kochi 682001 (fictional)"


def money(value: str) -> str:
    """Format a Decimal string with standard comma grouping for documents."""
    d = Decimal(value)
    return f"{d:,.2f}"


@dataclass
class Item:
    description: str
    qty: int
    rate: str

    @property
    def amount(self) -> Decimal:
        return Decimal(self.rate) * self.qty


@dataclass
class Invoice:
    file_name: str
    layout: str  # classic | modern | statement
    supplier: str
    supplier_address: str
    number: str
    date_text: str
    currency: str
    items: list[Item]
    net: str
    tax_label: str
    tax: str | None  # None = tax line missing from the document
    total: str
    expected_match: str
    expected_issues: list[str] = field(default_factory=list)
    scenario: str = ""


HARBOR_INVOICES: list[Invoice] = [
    Invoice("apex_INV-00123.pdf", "classic", "Apex Industrial Components Pvt. Ltd.",
            "Plot 22, Phase II Industrial Area, Coimbatore 641021 (fictional)",
            "INV-00123", "05/03/2025", "INR",
            [Item("Hydraulic hose assembly, 1/2 in", 20, "350.00"), Item("Pressure gauge 0-10 bar", 10, "300.00")],
            "10000.00", "Tax Amount (GST 18%)", "1800.00", "11800.00",
            "matched", [], "Clean match. Register spells the supplier 'Private Limited'; documented suffix normalization."),
    Invoice("bluecrest_BOS-2025-0042.pdf", "classic", "Bluecrest Office Solutions LLP",
            "7 Market Lane, Ernakulam 682011 (fictional)",
            "BOS/2025/0042", "07/03/2025", "INR",
            [Item("A4 copier paper, carton of 5 reams", 25, "170.00")],
            "4250.00", "Tax Amount (GST 18%)", "765.00", "5015.00",
            "matched", [], "Clean match."),
    Invoice("kestrel_000457.pdf", "modern", "Kestrel Logistics Services",
            "Warehouse 4, NH 544 Bypass, Thrissur 680005 (fictional)",
            "000457", "12 Mar 2025", "INR",
            [Item("Line haul Kochi - Coimbatore, 9 tonne", 2, "11000.00")],
            "22000.00", "Tax (GST 5%)", "1100.00", "23100.00",
            "matched", [], "Clean match. Invoice number is all digits with leading zeros."),
    Invoice("corvane_CS-7781.pdf", "modern", "Corvane Software Ltd",
            "Suite 9, 40 Harbour Street, Bristol BS1 (fictional)",
            "CS-7781", "12 Mar 2025", "USD",
            [Item("Annual licence, inventory module", 1, "1200.00")],
            "1200.00", "Tax (0%)", "0.00", "1200.00",
            "matched", [], "Clean match in USD."),
    Invoice("sablefin_SE-2025-118.pdf", "statement", "Sablefin Electricals",
            "18 Foundry Road, Aluva 683101 (fictional)",
            "SE-2025-118", "2025-03-14", "INR",
            [Item("LED panel 2x2 ft, 36 W", 24, "350.00")],
            "8400.00", "Tax", "1512.00", "9912.00",
            "matched", [], "Clean match through an explicit supplier alias (register says 'Sablefin Electrical Works')."),
    Invoice("quillmark_QS-0091.pdf", "classic", "Quillmark Stationers",
            "3 College Road, Kottayam 686001 (fictional)",
            "QS-0091", "10/03/2025", "INR",
            [Item("Ledger books, 200 pages", 50, "60.00")],
            "3000.00", "Tax Amount (GST 18%)", "540.00", "3540.00",
            "ambiguous", ["duplicate"], "Duplicate: the supplier sent the same invoice twice."),
    Invoice("quillmark_QS-0091_resent.pdf", "classic", "Quillmark Stationers",
            "3 College Road, Kottayam 686001 (fictional)",
            "QS-0091", "10/03/2025", "INR",
            [Item("Ledger books, 200 pages", 50, "60.00")],
            "3000.00", "Tax Amount (GST 18%)", "540.00", "3540.00",
            "ambiguous", ["duplicate"], "Duplicate copy of quillmark_QS-0091.pdf."),
    Invoice("tarnwood_TP-5520.pdf", "classic", "Tarnwood Packaging Co.",
            "Survey 118, Kalamassery 683104 (fictional)",
            "TP-5520", "11/03/2025", "INR",
            [Item("Corrugated boxes 5-ply, 18x12x12 in", 1000, "15.00")],
            "15000.00", "Tax Amount (GST 18%)", None, "17700.00",
            "invalid", ["missing_required"],
            "Missing required field: the tax line is absent. Correct tax to 2,700.00 and it matches."),
    Invoice("velanto_VFS-3307.pdf", "classic", "Velanto Facility Services",
            "22 Lake View Road, Kochi 682020 (fictional)",
            "VFS-3307", "31/02/2025", "INR",
            [Item("Housekeeping services, February", 1, "6000.00")],
            "6000.00", "Tax Amount (GST 18%)", "1080.00", "7080.00",
            "invalid", ["invalid_date"], "Invalid date: 31 February does not exist. The register says 28/02/2025."),
    Invoice("orchid_OLC-1450.pdf", "classic", "Orchid Lane Caterers",
            "5 Temple Street, Tripunithura 682301 (fictional)",
            "OLC-1450", "13/03/2025", "INR",
            [Item("Working lunch, 95 covers", 95, "100.00")],
            "9500.00", "Tax Amount (GST 5%)", "475.00", "10075.00",
            "matched", ["arithmetic"],
            "Arithmetic inconsistency: 9,500.00 + 475.00 is 9,975.00, not 10,075.00. The register repeats the same "
            "figures, so matching reports Matched while the arithmetic check still fails."),
    Invoice("apex_INV-00131.pdf", "classic", "Apex Industrial Components Pvt. Ltd.",
            "Plot 22, Phase II Industrial Area, Coimbatore 641021 (fictional)",
            "INV-00131", "18/03/2025", "INR",
            [Item("Solenoid valve 24 V DC", 13, "814.86")],
            "10593.18", "Tax Amount (GST 18%)", "1906.82", "12500.00",
            "mismatched", ["mismatch"], "Amount mismatch: invoice total 12,500.00, register total 12,050.00."),
    Invoice("bluecrest_BOS-2025-0057.pdf", "classic", "Bluecrest Office Solutions LLP",
            "7 Market Lane, Ernakulam 682011 (fictional)",
            "BOS/2025/0057", "20/03/2025", "INR",
            [Item("Toner cartridge, black", 6, "350.00")],
            "2100.00", "Tax Amount (GST 18%)", "378.00", "2478.00",
            "missing_from_reference", ["missing_from_reference"], "Invoice absent from the register."),
    Invoice("kestrel_000462.pdf", "modern", "Kestrel Logistics Services",
            "Warehouse 4, NH 544 Bypass, Thrissur 680005 (fictional)",
            "000462", "21 Mar 2025", "INR",
            [Item("Line haul Kochi - Coimbatore, 9 tonne", 2, "11000.00")],
            "22000.00", "Tax (GST 5%)", "1100.00", "23100.00",
            "missing_from_reference", ["missing_from_reference"],
            "Equal amounts, different invoices: same 23,100.00 as 000457 and as register row 000463, but no register "
            "row has invoice number 000462, so nothing is matched on amount."),
    Invoice("tarnwood_TP-5531.pdf", "classic", "Tarnwood Packaging Co.",
            "Survey 118, Kalamassery 683104 (fictional)",
            "TP-5531", "24/03/2025", "INR",
            [Item("Stretch film roll, 500 mm", 40, "120.00")],
            "4800.00", "Tax Amount (GST 18%)", "864.00", "5664.00",
            "ambiguous", ["ambiguous"], "Multiple possible matches: the register has TP-5531 twice."),
    Invoice("velanto_VFS-3312.pdf", "statement", "Velanto Facility Services",
            "22 Lake View Road, Kochi 682020 (fictional)",
            "VFS-3312", "2025-03-25", "INR",
            [Item("Pest control, quarterly visit", 1, "6500.00")],
            "6500.00", "Tax", "1170.00", "7670.00",
            "matched", [], "Clean match from the billing statement layout."),
]

HARBOR_REJECTED = [
    ("lumenridge_quotation_Q-219.pdf", "unsupported_layout",
     "Readable text, but a quotation layout that no parser supports."),
    ("scan_marlow_MSU-88120.pdf", "image_only",
     "Image-only scan with no text layer. OCR is not supported, so the register row MSU-88120 has no uploaded invoice."),
    ("invoice_damaged.pdf", "damaged", "Damaged file: PDF header followed by broken content."),
]

# Register rows: (vendor, bill no, bill date, currency, taxable, gst, total, entered by, remarks, expected)
HARBOR_REGISTER = [
    ("Apex Industrial Components Private Limited", "INV-00123", date(2025, 3, 5), "INR", "10000.00", "1800.00", "11800.00", "R. Menon", "", "matched"),
    ("Bluecrest Office Solutions LLP", "BOS/2025/0042", date(2025, 3, 7), "INR", "4250.00", "765.00", "5015.00", "R. Menon", "", "matched"),
    ("Kestrel Logistics Services", "000457", date(2025, 3, 12), "INR", "22000.00", "1100.00", "23100.00", "S. Iyer", "", "matched"),
    ("Corvane Software Ltd", "CS-7781", date(2025, 3, 12), "USD", "1200.00", "0.00", "1200.00", "S. Iyer", "Foreign currency", "matched"),
    ("Sablefin Electrical Works", "SE-2025-118", date(2025, 3, 14), "INR", "8400.00", "1512.00", "9912.00", "R. Menon", "", "matched"),
    ("Quillmark Stationers", "QS-0091", date(2025, 3, 10), "INR", "3000.00", "540.00", "3540.00", "R. Menon", "", "ambiguous"),
    ("Tarnwood Packaging Co.", "TP-5520", date(2025, 3, 11), "INR", "15000.00", "2700.00", "17700.00", "S. Iyer", "", "partner_invalid"),
    ("Velanto Facility Services", "VFS-3307", date(2025, 2, 28), "INR", "6000.00", "1080.00", "7080.00", "S. Iyer", "", "partner_invalid"),
    ("Orchid Lane Caterers", "OLC-1450", date(2025, 3, 13), "INR", "9500.00", "475.00", "10075.00", "R. Menon", "Staff event", "matched"),
    ("Apex Industrial Components Pvt Ltd", "INV-00131", date(2025, 3, 18), "INR", "10211.86", "1838.14", "12050.00", "R. Menon", "", "mismatched"),
    ("Kestrel Logistics Services", "000463", date(2025, 3, 22), "INR", "22000.00", "1100.00", "23100.00", "S. Iyer", "", "no_invoice"),
    ("Tarnwood Packaging Co", "TP-5531", date(2025, 3, 24), "INR", "4800.00", "864.00", "5664.00", "S. Iyer", "", "ambiguous"),
    ("Tarnwood Packaging Co.", "TP-5531", date(2025, 3, 25), "INR", "4800.00", "864.00", "5664.00", "R. Menon", "Entered twice?", "ambiguous"),
    ("Velanto Facility Services", "VFS-3312", date(2025, 3, 25), "INR", "6500.00", "1170.00", "7670.00", "R. Menon", "", "matched"),
    ("Marlow Street Utilities", "MSU-88120", date(2025, 3, 27), "INR", "3200.00", "576.00", "3776.00", "S. Iyer", "Scanned copy only", "no_invoice"),
]

# Meridian: invoice listing (CSV, all text) and register (CSV, US-style dates).
MERIDIAN_LISTING = [
    # supplier, inv no, inv date, ccy, net, tax, total, expected, issues
    ("Ferrowave Tools", "FT/24-25/0310", "03-03-2025", "INR", "18,450.00", "3,321.00", "21,771.00", "matched", []),
    ("Ferrowave Tools", "FT/24-25/0322", "10-03-2025", "INR", "6,200.00", "1,116.00", "7,316.00", "matched", []),
    ("Glenbrook Lubricants", "0004471", "05-03-2025", "INR", "12,000.00", "2,160.00", "14,160.00", "matched", []),
    ("Glenbrook Lubricants", "0004480", "12-03-2025", "INR", "9,800.00", "1,764.00", "11,564.00", "mismatched", ["mismatch"]),
    ("Pinecrest Safety Gear", "PSG-221", "14-03-2025", "INR", "4,500.00", "810.00", "5,310.00", "missing_from_reference", ["missing_from_reference"]),
    ("Rivermint Cleaning Co", "RC-0098", "17-03-2025", "", "3,600.00", "648.00", "4,248.00", "invalid", ["missing_required"]),
    ("Talon Fasteners", "TF-5501", "18-03-2025", "INR", "7,200.00", "1,296.00", "8,496.00", "matched", []),
    ("Ferrowave Tools", "FT/24-25/0331", "21-03-2025", "INR", "2,500.00", "450.00", "2,950.00", "matched", []),
]
MERIDIAN_REGISTER = [
    ("Ferrowave Tools Pvt Ltd", "FT/24-25/0310", "03/03/2025", "INR", "18450.00", "3321.00", "21771.00", "matched"),
    ("Ferrowave Tools Pvt Ltd", "FT/24-25/0322", "03/10/2025", "INR", "6200.00", "1116.00", "7316.00", "matched"),
    ("Glenbrook Lubricants", "0004471", "03/05/2025", "INR", "12000.00", "2160.00", "14160.00", "matched"),
    ("Glenbrook Lubricants", "0004480", "03/13/2025", "INR", "9800.00", "1764.00", "11564.00", "mismatched"),
    ("Rivermint Cleaning Co", "RC-0098", "03/17/2025", "INR", "3600.00", "648.00", "4248.00", "no_invoice"),
    ("Talon Fasteners", "TF-5501", "03/18/2025", "INR", "7200.00", "1296.00", "8496.00", "matched"),
    ("Ferrowave Tools Pvt Ltd", "FT/24-25/0331", "03/21/2025", "INR", "2500.00", "450.00", "2950.00", "matched"),
    ("Hollowbrook Freight Lines", "HF-7710", "03/24/2025", "INR", "11000.00", "550.00", "11550.00", "no_invoice"),
]


# ---------------------------------------------------------------- PDF writers

def new_pdf(title: str) -> FPDF:
    pdf = FPDF(format="A4", unit="mm")
    pdf.set_creation_date(FIXED_TIME)
    pdf.set_title(title)
    pdf.set_author("Synthetic data generator")
    pdf.set_creator("doc-review-workbench sample_data/generate_samples.py")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    return pdf


def footer(pdf: FPDF) -> None:
    pdf.set_auto_page_break(auto=False)
    pdf.set_y(-22)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, SYNTHETIC_FOOTER, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)


def line(pdf: FPDF, text: str, size: float = 10, style: str = "", align: str = "L", h: float = 6) -> None:
    pdf.set_font("Helvetica", style, size)
    pdf.cell(0, h, text, align=align, new_x="LMARGIN", new_y="NEXT")


def item_table(pdf: FPDF, items: list[Item], currency: str) -> None:
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(235, 238, 242)
    widths = (95, 20, 35, 40)
    for w, head in zip(widths, ("Description", "Qty", f"Rate ({currency})", f"Amount ({currency})")):
        pdf.cell(w, 7, head, border=1, fill=True, align="L" if head == "Description" else "R")
    pdf.ln()
    pdf.set_font("Helvetica", "", 9)
    for it in items:
        pdf.cell(widths[0], 7, it.description, border=1)
        pdf.cell(widths[1], 7, str(it.qty), border=1, align="R")
        pdf.cell(widths[2], 7, money(it.rate), border=1, align="R")
        pdf.cell(widths[3], 7, money(str(it.amount)), border=1, align="R")
        pdf.ln()
    pdf.ln(3)


def write_classic(inv: Invoice, path: Path) -> None:
    pdf = new_pdf(f"Tax invoice {inv.number}")
    line(pdf, inv.supplier, 15, "B", h=8)
    line(pdf, inv.supplier_address, 9)
    line(pdf, "Tax ID: SYN-TAX-0000 (synthetic)", 9)
    pdf.ln(4)
    line(pdf, "TAX INVOICE", 13, "B", align="C", h=8)
    pdf.ln(2)
    line(pdf, f"Invoice No: {inv.number}")
    line(pdf, f"Invoice Date: {inv.date_text}")
    line(pdf, f"Currency: {inv.currency}")
    line(pdf, f"Bill To: {BUYER_A}, {BUYER_A_ADDRESS}", 9)
    item_table(pdf, inv.items, inv.currency)
    line(pdf, f"Net Amount: {money(inv.net)}", align="R")
    if inv.tax is not None:
        line(pdf, f"{inv.tax_label}: {money(inv.tax)}", align="R")
    line(pdf, f"Total Amount: {money(inv.total)}", 11, "B", align="R")
    pdf.ln(6)
    line(pdf, "Payment terms: 30 days from invoice date.", 9)
    footer(pdf)
    pdf.output(str(path))


def write_modern(inv: Invoice, path: Path) -> None:
    pdf = new_pdf(f"Invoice {inv.number}")
    line(pdf, "INVOICE", 22, "B", h=11)
    pdf.ln(1)
    line(pdf, f"From: {inv.supplier}", 11, "B")
    line(pdf, inv.supplier_address, 9)
    pdf.ln(3)
    line(pdf, f"Invoice # {inv.number}")
    line(pdf, f"Issued: {inv.date_text}")
    line(pdf, f"Billed to: {BUYER_A}", 9)
    item_table(pdf, inv.items, inv.currency)
    rows = [("Subtotal", inv.net), (inv.tax_label, inv.tax), ("Amount due", inv.total)]
    for label, value in rows:
        if value is None:
            continue
        pdf.set_font("Helvetica", "B" if label == "Amount due" else "", 10)
        pdf.cell(110, 7, "")
        pdf.cell(40, 7, label)
        pdf.cell(40, 7, f"{inv.currency} {money(value)}", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    line(pdf, "Thank you for your business.", 9)
    footer(pdf)
    pdf.output(str(path))


def write_statement(inv: Invoice, path: Path) -> None:
    pdf = new_pdf(f"Billing statement {inv.number}")
    line(pdf, "BILLING STATEMENT", 16, "B", h=9)
    line(pdf, f"Prepared for {BUYER_A}", 9)
    pdf.ln(4)
    rows = [
        ("Supplier", inv.supplier),
        ("Document ref", inv.number),
        ("Statement date", inv.date_text),
        ("Currency", inv.currency),
        ("Amount before tax", money(inv.net)),
        ("Tax", money(inv.tax) if inv.tax is not None else None),
        ("Amount payable", money(inv.total)),
    ]
    for label, value in rows:
        if value is None:
            continue
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(50, 8, f"{label}:", border="B")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 8, value, border="B", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    line(pdf, "Services:", 9, "B")
    for it in inv.items:
        line(pdf, f"- {it.description} x {it.qty}", 9)
    footer(pdf)
    pdf.output(str(path))


def write_quotation(path: Path) -> None:
    pdf = new_pdf("Quotation Q-219")
    line(pdf, "Lumen Ridge Traders", 15, "B", h=8)
    line(pdf, "41 Canal Road, Alappuzha 688001 (fictional)", 9)
    pdf.ln(4)
    line(pdf, "QUOTATION", 13, "B", align="C", h=8)
    line(pdf, "Quote No: Q-219")
    line(pdf, "Valid until: 30/04/2025")
    line(pdf, f"Prepared for: {BUYER_A}", 9)
    item_table(pdf, [Item("Safety signage set", 10, "450.00")], "INR")
    line(pdf, "Estimated value: INR 4,500.00 plus applicable tax", align="R")
    footer(pdf)
    pdf.output(str(path))


def write_image_only(path: Path) -> None:
    img = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(img)
    try:
        big = ImageFont.load_default(size=44)
        normal = ImageFont.load_default(size=30)
    except TypeError:  # very old Pillow
        big = normal = ImageFont.load_default()
    y = 120
    for text, font in [
        ("Marlow Street Utilities", big), ("TAX INVOICE", big), ("", normal),
        ("Invoice No: MSU-88120", normal), ("Invoice Date: 27/03/2025", normal), ("Currency: INR", normal),
        ("", normal), ("Net Amount: 3,200.00", normal), ("Tax Amount (GST 18%): 576.00", normal),
        ("Total Amount: 3,776.00", normal), ("", normal), (SYNTHETIC_FOOTER, normal),
    ]:
        draw.text((100, y), text, fill="black", font=font)
        y += 70
    pdf = new_pdf("Scanned invoice")
    pdf.image(img, x=0, y=0, w=210)
    pdf.output(str(path))


def write_damaged(path: Path, template: Path) -> None:
    good = template.read_bytes()
    junk = bytes((i * 37 + 11) % 256 for i in range(900))
    path.write_bytes(good[:180] + junk)


# ---------------------------------------------------------------- spreadsheets

def write_harbor_register(path: Path) -> list[dict]:
    wb = Workbook()
    readme = wb.active
    readme.title = "Read me"
    readme["A1"] = "SYNTHETIC purchase register for Harbor Lane Supplies Pvt Ltd (fictional company)."
    readme["A2"] = "Generated by sample_data/generate_samples.py for demonstrations. Not real data."
    readme["A3"] = "The register is on the sheet 'Register 2025-03'."
    ws = wb.create_sheet("Register 2025-03")
    ws["A1"] = "Purchase register - March 2025 (SYNTHETIC)"
    headers = ["Vendor Name", "Bill No.", "Bill Date", "Currency", "Taxable Value", "GST Amount",
               "Bill Total", "Entered By", "Remarks"]
    ws.append([])
    ws.append(headers)
    expected = []
    for row in HARBOR_REGISTER:
        vendor, bill_no, bill_date, ccy, taxable, gst, total, entered, remarks, outcome = row
        ws.append([vendor, bill_no, bill_date, ccy, Decimal(taxable), Decimal(gst), Decimal(total), entered,
                   remarks or None])
        r = ws.max_row
        ws.cell(r, 2).number_format = "@"  # invoice numbers stored as text
        ws.cell(r, 3).number_format = "DD-MMM-YYYY"
        for c in (5, 6, 7):
            ws.cell(r, c).number_format = "#,##0.00"
        expected.append({"row": r, "invoice_number": bill_no, "supplier": vendor, "expected_match": outcome})
    widths = [42, 16, 14, 10, 15, 13, 13, 12, 18]
    for idx, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + idx)].width = w
    wb.properties.creator = "Synthetic data generator"
    wb.properties.created = FIXED_TIME.replace(tzinfo=None)
    wb.properties.modified = FIXED_TIME.replace(tzinfo=None)
    wb.save(path)
    return expected


def write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8")


# ---------------------------------------------------------------- main

def main() -> None:
    harbor = ROOT / "harbor_lane"
    invoices_dir = harbor / "invoices"
    invoices_dir.mkdir(parents=True, exist_ok=True)
    for old in invoices_dir.glob("*.pdf"):
        old.unlink()

    writers = {"classic": write_classic, "modern": write_modern, "statement": write_statement}
    for inv in HARBOR_INVOICES:
        writers[inv.layout](inv, invoices_dir / inv.file_name)
    write_quotation(invoices_dir / HARBOR_REJECTED[0][0])
    write_image_only(invoices_dir / HARBOR_REJECTED[1][0])
    write_damaged(invoices_dir / HARBOR_REJECTED[2][0], invoices_dir / HARBOR_INVOICES[0].file_name)
    register_expected = write_harbor_register(harbor / "purchase_register.xlsx")

    meridian = ROOT / "meridian"
    meridian.mkdir(parents=True, exist_ok=True)
    write_csv(meridian / "supplier_invoice_listing.csv",
              ["Supplier", "Inv No", "Inv Date", "Ccy", "Amount excl. tax", "Tax", "Amount incl. tax"],
              [list(r[:7]) for r in MERIDIAN_LISTING])
    write_csv(meridian / "purchase_register.csv",
              ["Party", "Supplier Invoice Ref", "Supplier Invoice Date", "Curr.", "Basic Value", "Tax Value",
               "Doc Total"],
              [list(r[:7]) for r in MERIDIAN_REGISTER])

    harbor_files = [{"role": "invoice", "path": f"harbor_lane/invoices/{inv.file_name}"} for inv in HARBOR_INVOICES]
    harbor_files += [{"role": "invoice", "path": f"harbor_lane/invoices/{name}"} for name, _, _ in HARBOR_REJECTED]
    harbor_files.append({"role": "reference", "path": "harbor_lane/purchase_register.xlsx"})
    manifest = {
        "note": "Synthetic demo data. All companies and figures are fictional.",
        "samples": [
            {
                "id": "harbor_lane",
                "name": "Harbor Lane Supplies (fictional)",
                "template_id": "supplier_invoice",
                "description": "18 supplier invoice PDFs in three layouts (including a duplicate, an unsupported "
                               "layout, an image-only scan and a damaged file) and an XLSX purchase register "
                               "with a notes sheet and a title row.",
                "files": harbor_files,
            },
            {
                "id": "meridian",
                "name": "Meridian Workshop Services (fictional)",
                "template_id": "supplier_invoice",
                "description": "A CSV invoice listing and a CSV purchase register with different column headings. "
                               "The register uses month-first dates and two headings that are not in the aliases, "
                               "so it stops at column mapping.",
                "files": [
                    {"role": "invoice", "path": "meridian/supplier_invoice_listing.csv"},
                    {"role": "reference", "path": "meridian/purchase_register.csv"},
                ],
            },
        ],
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    expected = {
        "note": "Expected pipeline results for the synthetic data. Used by tests only; the app never reads this.",
        "harbor_lane": {
            "invoices": {
                inv.file_name: {"expected_match": inv.expected_match, "expected_issues": inv.expected_issues,
                                "scenario": inv.scenario}
                for inv in HARBOR_INVOICES
            },
            "rejected_files": {name: {"reason": reason, "scenario": text} for name, reason, text in HARBOR_REJECTED},
            "register_rows": register_expected,
        },
        "meridian": {
            "invoices": [
                {"row": i + 2, "invoice_number": r[1], "expected_match": r[7], "expected_issues": r[8]}
                for i, r in enumerate(MERIDIAN_LISTING)
            ],
            "register_rows": [
                {"row": i + 2, "invoice_number": r[1], "expected_match": r[7]}
                for i, r in enumerate(MERIDIAN_REGISTER)
            ],
            "register_mapping": {
                "supplier_name": "Party", "invoice_number": "Supplier Invoice Ref",
                "invoice_date": "Supplier Invoice Date", "currency": "Curr.", "net_amount": "Basic Value",
                "tax_amount": "Tax Value", "total_amount": "Doc Total",
            },
            "register_date_order": "MDY",
        },
    }
    (ROOT / "expected_outcomes.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(HARBOR_INVOICES) + len(HARBOR_REJECTED)} PDFs, 1 XLSX and 2 CSV files under {ROOT}")


if __name__ == "__main__":
    main()
