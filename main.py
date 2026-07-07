import re
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dateutil import parser as date_parser


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class InvoiceRequest(BaseModel):
    invoice_text: str


def parse_money(value):
    if value is None:
        return None

    value = str(value)
    value = value.replace(",", "")
    value = re.sub(r"(Rs\.?|INR|USD|EUR|GBP|\$|₹|€|£)", "", value, flags=re.I)
    value = value.strip()

    match = re.search(r"-?\d+(?:\.\d+)?", value)
    if not match:
        return None

    return float(match.group())


def find_money_after_label(text, labels):
    money_pattern = r"(?:Rs\.?|INR|USD|EUR|GBP|\$|₹|€|£)?\s*([\d,]+(?:\.\d+)?)"

    for line in text.splitlines():
        line_clean = line.strip()

        for label in labels:
            if re.search(label, line_clean, flags=re.I):
                # Find money value anywhere after label on same line
                matches = re.findall(money_pattern, line_clean, flags=re.I)
                if matches:
                    return parse_money(matches[-1])

    return None


def extract_invoice_no(text):
    patterns = [
        r"Invoice\s*(?:No|Number|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\/\-_]+)",
        r"Inv\s*(?:No|#)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\/\-_]+)",
        r"Bill\s*(?:No|Number|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\/\-_]+)",
        r"Ref\s*[:\-]?\s*([A-Z0-9][A-Z0-9\/\-_]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return match.group(1).strip()

    return None


def extract_date(text):
    date_patterns = [
        r"(?:Date|Issued|Invoice Date|Bill Date)\s*[:\-]?\s*([0-9]{4}-[0-9]{2}-[0-9]{2})",
        r"(?:Date|Issued|Invoice Date|Bill Date)\s*[:\-]?\s*([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})",
        r"(?:Date|Issued|Invoice Date|Bill Date)\s*[:\-]?\s*([A-Za-z]+\s+[0-9]{1,2},?\s+[0-9]{4})",
        r"(?:Date|Issued|Invoice Date|Bill Date)\s*[:\-]?\s*([0-9]{1,2}[\/\-][0-9]{1,2}[\/\-][0-9]{2,4})",
    ]

    for pattern in date_patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            raw_date = match.group(1).strip()
            try:
                dt = date_parser.parse(raw_date, dayfirst=True)
                return dt.strftime("%Y-%m-%d")
            except Exception:
                pass

    return None


def extract_vendor(text):
    patterns = [
        r"Vendor\s*[:\-]\s*(.+)",
        r"Supplier\s*[:\-]\s*(.+)",
        r"Seller\s*[:\-]\s*(.+)",
        r"From\s*[:\-]\s*(.+)",
        r"Merchant\s*[:\-]\s*(.+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            vendor = match.group(1).strip()
            vendor = re.split(r"\n|Bill To|Client|Customer", vendor, flags=re.I)[0].strip()
            return vendor

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:5]:
        if re.search(r"invoice|tax invoice|bill|receipt", line, flags=re.I):
            cleaned = re.sub(r"[-—]\s*(Tax\s*)?Invoice.*", "", line, flags=re.I).strip()
            if cleaned and not re.fullmatch(r"invoice", cleaned, flags=re.I):
                return cleaned
        elif not re.search(r"date|invoice no|ref|bill to|client", line, flags=re.I):
            return line

    return None


def extract_currency(text):
    match = re.search(r"Currency\s*[:\-]\s*([A-Z]{3})", text, flags=re.I)
    if match:
        return match.group(1).upper()

    if re.search(r"\bINR\b|Rs\.?|₹", text, flags=re.I):
        return "INR"
    if "$" in text or re.search(r"\bUSD\b", text, flags=re.I):
        return "USD"
    if "€" in text or re.search(r"\bEUR\b", text, flags=re.I):
        return "EUR"
    if "£" in text or re.search(r"\bGBP\b", text, flags=re.I):
        return "GBP"

    return None


def extract_amount(text):
    labels = [
        r"Sub\s*total",
        r"Subtotal",
        r"Amount\s*before\s*tax",
        r"Taxable\s*value",
        r"Net\s*amount",
        r"Base\s*amount",
    ]
    return find_money_after_label(text, labels)


def extract_tax(text):
    # First handle CGST + SGST style
    cgst = find_money_after_label(text, [r"CGST"])
    sgst = find_money_after_label(text, [r"SGST"])

    if cgst is not None or sgst is not None:
        return round((cgst or 0) + (sgst or 0), 2)

    labels = [
        r"IGST",
        r"GST",
        r"VAT",
        r"Tax",
        r"Sales\s*Tax",
    ]
    return find_money_after_label(text, labels)


@app.get("/")
def root():
    return {"status": "ok", "message": "Invoice extraction API is running"}


@app.post("/extract")
def extract_invoice(req: InvoiceRequest):
    text = req.invoice_text or ""

    return {
        "invoice_no": extract_invoice_no(text),
        "date": extract_date(text),
        "vendor": extract_vendor(text),
        "amount": extract_amount(text),
        "tax": extract_tax(text),
        "currency": extract_currency(text),
    }