import io
import os
import re
from datetime import datetime
from decimal import Decimal
from typing import Optional

import pytesseract
from fastapi import FastAPI, HTTPException
from minio import Minio
from pdf2image import convert_from_bytes
from PIL import Image
from pydantic import BaseModel

app = FastAPI(title="Provider Follow-up Local OCR", version="1.0.0")

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000").replace("http://", "").replace("https://", "")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "invoices")
TESSERACT_LANGS = os.getenv("TESSERACT_LANGS", "fra+eng")

minio_client = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=MINIO_SECURE)

class OcrRequest(BaseModel):
    objectKey: str
    filename: Optional[str] = None
    contentType: Optional[str] = None

class Suggestions(BaseModel):
    supplierName: Optional[str] = None
    invoiceNumber: Optional[str] = None
    invoiceDate: Optional[str] = None
    amountHt: Optional[float] = None
    vatAmount: Optional[float] = None
    amountTtc: Optional[float] = None
    currency: Optional[str] = "EUR"

class OcrResponse(BaseModel):
    rawText: str
    suggestions: Suggestions
    confidence: str = "LOW"

@app.get("/health")
def health():
    return {"status": "ok", "langs": TESSERACT_LANGS}

@app.post("/ocr/extract", response_model=OcrResponse)
def extract(request: OcrRequest):
    try:
        response = minio_client.get_object(MINIO_BUCKET, request.objectKey)
        data = response.read()
        response.close()
        response.release_conn()
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Cannot read object from MinIO: {exc}") from exc

    raw_text = extract_text(data, request.filename or "", request.contentType or "")
    suggestions = parse_suggestions(raw_text)
    confidence = "MEDIUM" if raw_text.strip() and any([suggestions.invoiceNumber, suggestions.amountTtc, suggestions.invoiceDate]) else "LOW"
    return OcrResponse(rawText=raw_text, suggestions=suggestions, confidence=confidence)

def extract_text(data: bytes, filename: str, content_type: str) -> str:
    is_pdf = filename.lower().endswith(".pdf") or content_type == "application/pdf" or data[:4] == b"%PDF"
    try:
        if is_pdf:
            pages = convert_from_bytes(data, dpi=250)
            return "\n\n".join(pytesseract.image_to_string(page, lang=TESSERACT_LANGS) for page in pages)
        image = Image.open(io.BytesIO(data))
        return pytesseract.image_to_string(image, lang=TESSERACT_LANGS)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"OCR extraction failed: {exc}") from exc

def parse_suggestions(text: str) -> Suggestions:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    supplier = next((line for line in lines[:8] if not re.search(r"facture|invoice|date|total|tva|vat", line, re.I)), None)
    invoice_number = find_first(text, [
        r"(?:facture|invoice)\s*(?:n[°o.]?|number|#)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9_./\-]{2,})",
        r"(?:n[°o.]|number|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9_./\-]{2,})",
    ])
    invoice_date = parse_date(find_first(text, [
        r"(?:date\s*(?:facture|invoice)?|invoice\s*date)\s*[:\-]?\s*([0-3]?\d[./\-][01]?\d[./\-]\d{2,4})",
        r"\b([0-3]?\d[./\-][01]?\d[./\-]\d{4})\b",
        r"\b(\d{4}-\d{2}-\d{2})\b",
    ]))
    currency = "EUR" if re.search(r"€|\bEUR\b", text, re.I) else ("USD" if re.search(r"\$|\bUSD\b", text, re.I) else "EUR")
    amount_ttc = find_amount(text, [r"(?:total\s*(?:ttc|incl\.? tax)?|montant\s*ttc|net\s*à\s*payer|amount\s*due)\D{0,20}([0-9][0-9\s.,]*)"])
    amount_ht = find_amount(text, [r"(?:total\s*ht|montant\s*ht|subtotal|hors\s*taxe)\D{0,20}([0-9][0-9\s.,]*)"])
    vat = find_amount(text, [r"(?:tva|vat|tax)\D{0,20}([0-9][0-9\s.,]*)"])
    return Suggestions(supplierName=supplier, invoiceNumber=invoice_number, invoiceDate=invoice_date,
                       amountHt=amount_ht, vatAmount=vat, amountTtc=amount_ttc, currency=currency)

def find_first(text: str, patterns: list[str]) -> Optional[str]:
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.M)
        if match:
            return match.group(1).strip()
    return None

def find_amount(text: str, patterns: list[str]) -> Optional[float]:
    value = find_first(text, patterns)
    if value is None:
        return None
    normalized = value.replace(" ", "").replace("\u00a0", "")
    if "," in normalized and "." in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    else:
        normalized = normalized.replace(",", ".")
    normalized = re.sub(r"[^0-9.]", "", normalized)
    try:
        return float(Decimal(normalized))
    except Exception:
        return None

def parse_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None
