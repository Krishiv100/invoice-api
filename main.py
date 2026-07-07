import re
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


def money_values_from_line(line):
    # Remove percentage parts like (18%) so tax rate is not captured as amount
    line = re.sub(r"\(?\s*\d+(?:\.\d+)?\s*%\s*\)?", " ", line)

    pattern = r"(?:Rs\.?|INR|USD|EUR|GBP|\$|₹|€|£)?\s*([\d,]+(?:\.\d+)?)"
    values = re.findall(pattern, line, flags=re.I)

    return [parse_money(v) for v in values if parse_money(v) is not None]


def find_money_after_label(text, labels):
    for line in text.splitlines():
        line_clean = line.strip()

        for label in labels:
            if re.search(label, line_clean, flags=re.I):
                values = money_values_from_line(line_clean)
                if values:
                    return values[-1]

    return None


def extract_invoice_no(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    patterns = [
        r"\bInvoice\s*(?:No\.?|Number|#|ID)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\/\-_]+)",
        r"\bInv\s*(?:No\.?|Number|#|ID)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\/\-_]+)",
        r"\bBill\s*(?:No\.?|Number|#|ID)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\/\-_]+)",
        r"\bReceipt\s*(?:No\.?|Number|#|ID)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\/\-_]+)",
        r"\bRef(?:erence)?\s*[:\-]\s*([A-Z0-9][A-Z0-9\/\-_]+)",
        r"\bOrder\s*(?:No\.?|Number|#|ID)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\/\-_]+)",
    ]

    for line in lines:
        for pattern in patterns:
            match = re.search(pattern, line, flags=re.I)
            if match:
                return match.group(1).strip().rstrip(".,;")

    code_patterns = [
        r"\b[A-Z]{2,8}-\d{3,10}\b",
        r"\b[A-Z]{2,8}/\d{4}/\d{2,10}\b",
        r"\bINV-\d{4}-\d{3,10}\b",
    ]

    for pattern in code_patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return match.group(0).strip()

    return None


def extract_date(text):
    patterns = [
        r"(?:Date|Issued|Invoice Date|Bill Date)\s*[:\-]?\s*([0-9]{4}-[0-9]{2}-[0-9]{2})",
        r"(?:Date|Issued|Invoice Date|Bill Date)\s*[:\-]?\s*([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})",
        r"(?:Date|Issued|Invoice Date|Bill Date)\s*[:\-]?\s*([A-Za-z]+\s+[0-9]{1,2},?\s+[0-9]{4})",
        r"(?:Date|Issued|Invoice Date|Bill Date)\s*[:\-]?\s*([0-9]{1,2}[\/\-][0-9]{1,2}[\/\-][0-9]{2,4})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            try:
                dt = date_parser.parse(match.group(1), dayfirst=True)
                return dt.strftime("%Y-%m-%d")
            except Exception:
                pass

    return None


def extract_vendor(text):
    patterns = [
        r"Vendor\s*[:\-]\s*(.+)",
        r"Supplier\s*[:\-]\s*(.+)",
        r"Seller\s*[:\-]\s*(.+)",
        r"Merchant\s*[:\-]\s*(.+)",
        r"From\s*[:\-]\s*(.+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            vendor = match.group(1).strip()
            vendor = re.split(r"\n|Bill To|Client|Customer", vendor, flags=re.I)[0].strip()
            return vendor.rstrip(".,;")

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    for line in lines[:5]:
        if re.fullmatch(r"invoice|tax invoice|bill|receipt", line, flags=re.I):
            continue

        cleaned = re.sub(r"\s*[—-]\s*(Tax\s*)?Invoice.*", "", line, flags=re.I).strip()

        if cleaned and not re.search(r"date|invoice no|ref|bill to|client", cleaned, flags=re.I):
            return cleaned.rstrip(".,;")

    return None


def extract_currency(text):
    match = re.search(r"Currency\s*[:\-]\s*([A-Z]{3})", text, flags=re.I)
    if match:
        return match.group(1).upper()

    if re.search(r"\bINR\b|Rs\.?|₹", text, flags=re.I):
        return "INR"
    if re.search(r"\bUSD\b|\$", text, flags=re.I):
        return "USD"
    if re.search(r"\bEUR\b|€", text, flags=re.I):
        return "EUR"
    if re.search(r"\bGBP\b|£", text, flags=re.I):
        return "GBP"

    return None


def extract_tax(text):
    cgst = find_money_after_label(text, [r"\bCGST\b"])
    sgst = find_money_after_label(text, [r"\bSGST\b"])

    if cgst is not None or sgst is not None:
        return round((cgst or 0) + (sgst or 0), 2)

    labels = [
        r"\bIGST\b",
        r"\bGST\b",
        r"\bVAT\b",
        r"Tax\s*amount",
        r"Sales\s*Tax",
        r"\bTax\b",
    ]

    return find_money_after_label(text, labels)


def extract_total(text):
    labels = [
        r"Grand\s*Total",
        r"Total\s*Due",
        r"Amount\s*Due",
        r"Invoice\s*Total",
        r"Final\s*Amount",
        r"Total\s*Amount",
        r"\bTOTAL\b",
    ]

    return find_money_after_label(text, labels)


def extract_amount(text):
    labels = [
        r"Sub\s*total",
        r"Sub-total",
        r"Subtotal",
        r"Amount\s*before\s*tax",
        r"Pre[-\s]*tax\s*amount",
        r"Pre[-\s]*tax\s*total",
        r"Before\s*tax",
        r"Taxable\s*amount",
        r"Taxable\s*value",
        r"Taxable\s*total",
        r"Net\s*amount",
        r"Net\s*total",
        r"Base\s*amount",
        r"Basic\s*amount",
        r"Items?\s*total",
        r"Goods\s*total",
        r"Services?\s*total",
        r"Charges\s*before\s*tax",
    ]

    amount = find_money_after_label(text, labels)
    if amount is not None:
        return amount

    total = extract_total(text)
    tax = extract_tax(text)

    if total is not None and tax is not None:
        return round(total - tax, 2)

    return None


@app.get("/")
def root():
    return {"status": "ok", "message": "Invoice extraction API is running"}


@app.post("/extract")
def extract_invoice(req: InvoiceRequest):
    try:
        text = req.invoice_text or ""

        return {
            "invoice_no": extract_invoice_no(text),
            "date": extract_date(text),
            "vendor": extract_vendor(text),
            "amount": extract_amount(text),
            "tax": extract_tax(text),
            "currency": extract_currency(text),
        }

    except Exception:
        return {
            "invoice_no": None,
            "date": None,
            "vendor": None,
            "amount": None,
            "tax": None,
            "currency": None,
        }