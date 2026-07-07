import requests

invoice_text = """INVOICE
Invoice No: INV-2026-0041
Date: 15 March 2026
Vendor: TechParts Pvt Ltd
Bill To: IITM Procurement Dept

Items:
  USB-C Hub (x2) ............. Rs. 1,299.00
  HDMI Cable (x3) ............. Rs.   450.00
                                ----------
  Subtotal ...................  Rs. 2,199.00
  GST (18%) ..................  Rs.   395.82
                                ----------
  TOTAL ......................  Rs. 2,594.82
Currency: INR"""

res = requests.post(
    "http://localhost:8000/extract",
    json={"invoice_text": invoice_text}
)

print(res.status_code)
print(res.json())