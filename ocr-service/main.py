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
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from pydantic import BaseModel

app = FastAPI(title="Provider Follow-up Local OCR", version="1.0.0")

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000").replace("http://", "").replace("https://", "")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "invoices")
TESSERACT_LANGS = os.getenv("TESSERACT_LANGS", "fra+eng")
TESSERACT_CONFIG = "--oem 3 --psm 4 -c preserve_interword_spaces=1"

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
    filled = sum(1 for value in suggestions.model_dump().values() if value not in (None, ""))
    confidence = "HIGH" if filled >= 5 else "MEDIUM" if filled >= 3 else "LOW"
    return OcrResponse(rawText=raw_text, suggestions=suggestions, confidence=confidence)

def extract_text(data: bytes, filename: str, content_type: str) -> str:
    is_pdf = filename.lower().endswith(".pdf") or content_type == "application/pdf" or data[:4] == b"%PDF"
    try:
        images = convert_from_bytes(data, dpi=300) if is_pdf else [Image.open(io.BytesIO(data))]
        texts = []
        for image in images:
            prepared = prepare_image(image)
            text_candidates = [
                pytesseract.image_to_string(prepared, lang=TESSERACT_LANGS, config=TESSERACT_CONFIG),
                pytesseract.image_to_string(prepared, lang=TESSERACT_LANGS, config="--oem 3 --psm 6 -c preserve_interword_spaces=1"),
            ]
            if max(len(candidate.strip()) for candidate in text_candidates) < 25:
                text_candidates.append(pytesseract.image_to_string(prepared, lang=TESSERACT_LANGS, config="--oem 3 --psm 11"))
            texts.append(max(text_candidates, key=lambda candidate: (len(extract_labeled_lines(candidate)), len(candidate))))
        return "\n\n".join(texts)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"OCR extraction failed: {exc}") from exc

def prepare_image(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image).convert("L")
    max_width = 2200
    if image.width < max_width:
        ratio = max_width / image.width
        image = image.resize((max_width, int(image.height * ratio)), Image.Resampling.LANCZOS)
    image = ImageOps.autocontrast(image)
    image = ImageEnhance.Contrast(image).enhance(1.8)
    image = image.filter(ImageFilter.SHARPEN)
    return image.point(lambda pixel: 255 if pixel > 180 else 0)

def parse_suggestions(text: str) -> Suggestions:
    normalized_text = normalize_ocr_text(text)
    lines = [line.strip() for line in normalized_text.splitlines() if line.strip()]
    supplier = find_supplier(lines)
    invoice_number = find_invoice_number(normalized_text)
    invoice_date = parse_date(find_first(normalized_text, [
        r"(?:date\s*(?:de\s*)?(?:facture|invoice)?|invoice\s*date|issued\s*on|date\s*d['’]émission)\s*[:\-]?\s*([0-3]?\d[./\-][01]?\d[./\-]\d{2,4})",
        r"\b([0-3]?\d[./\-][01]?\d[./\-]\d{4})\b",
        r"\b(\d{4}-\d{2}-\d{2})\b",
    ]))
    currency = detect_currency(normalized_text)
    amount_ttc = find_amount(normalized_text, [
        r"(?:total\s*(?:ttc|t\.t\.c\.|incl\.?\s*tax)?|montant\s*ttc|net\s*à\s*payer|amount\s*due|balance\s*due|grand\s*total)\D{0,35}([0-9][0-9\s.,]*)(?:\s*(?:€|eur|usd|\$))?",
    ])
    amount_ht = find_amount(normalized_text, [
        r"(?:total\s*ht|montant\s*ht|sous\s*total|subtotal|hors\s*taxe|net\s*amount)\D{0,35}([0-9][0-9\s.,]*)",
    ])
    vat = find_amount(normalized_text, [r"(?:tva|vat|taxe|tax)\D{0,35}([0-9][0-9\s.,]*)"])
    return Suggestions(supplierName=supplier, invoiceNumber=invoice_number, invoiceDate=invoice_date,
                       amountHt=amount_ht, vatAmount=vat, amountTtc=amount_ttc, currency=currency)

def normalize_ocr_text(text: str) -> str:
    replacements = {"|": " ", "—": "-", "–": "-", "N°": "No", "n°": "No", "№": "No"}
    for source, target in replacements.items():
        text = text.replace(source, target)
    return re.sub(r"[ \t]+", " ", text)

def find_supplier(lines: list[str]) -> Optional[str]:
    company_markers = re.compile(r"\b(sa|sas|sarl|eurl|gmbh|ltd|limited|inc|corp|llc|bv|ag|spa|srl|group|groupe)\b", re.I)
    candidates = []
    for index, line in enumerate(lines[:20]):
        cleaned = clean_supplier_line(line)
        if not is_supplier_candidate(cleaned):
            continue
        score = 80 - (index * 4)
        if company_markers.search(cleaned):
            score += 45
        if index <= 4:
            score += 20
        if re.search(r"^[A-ZÀ-Ý0-9 &'.,-]{3,}$", cleaned):
            score += 15
        if re.search(r"\d", cleaned):
            score -= 20
        candidates.append((score, cleaned))
    strong_candidates = [candidate for candidate in candidates if candidate[0] >= 60]
    if not strong_candidates:
        return None
    return sorted(strong_candidates, key=lambda item: item[0], reverse=True)[0][1][:120]

def is_supplier_candidate(value: str) -> bool:
    if len(value) < 3 or len(value) > 120:
        return False
    noise = re.compile(
        r"facture|invoice|avoir|credit note|devis|quote|receipt|reçu|date|due|échéance|total|tva|vat|tax|montant|amount|client|customer|bill to|ship to|sold to|fournisseur|supplier|vendeur|num(?:é|e)ro|number|iban|bic|siret|siren|r\.c\.s|rcs|capital|page",
        re.I,
    )
    if noise.search(value):
        return False
    if re.fullmatch(r"[0-9\W]+", value):
        return False
    if re.search(r"@|www\.|https?://|\+?\d[\d .-]{7,}|\b\d{5}\b|rue|street|avenue|boulevard|road|phone|tel\b", value, re.I):
        return False
    return bool(re.search(r"[A-Za-zÀ-ÿ]{3,}", value))

def extract_labeled_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if re.search(r"facture|invoice|inv\.?|num(?:é|e)ro|number|total|tva|vat", line, re.I)]

def clean_supplier_line(line: str) -> str:
    line = re.sub(r"^(from|supplier|vendeur|fournisseur|émetteur)\s*[:\-]\s*", "", line.strip(), flags=re.I)
    line = re.sub(r"\s{2,}", " ", line)
    return line.strip(" -,:;")

def find_invoice_number(text: str) -> Optional[str]:
    for line in text.splitlines():
        if not re.search(r"facture|invoice|inv\.?|num(?:é|e)ro|number|no\b|n[o°.]|#", line, re.I):
            continue
        if re.search(r"date|due|échéance|total|amount|montant|tva|vat", line, re.I):
            # A mixed line can still contain an invoice number before the date/amount; keep parsing but lower false positives by using strict patterns.
            pass
        for pattern in (
            r"(?:facture|invoice|inv\.?|document)\s*(?:no|n[o°.]?|number|num(?:é|e)ro|#)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9_./\-]{2,})",
            r"(?:no|n[o°.]?|number|num(?:é|e)ro|#)\s*(?:facture|invoice)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9_./\-]{2,})",
            r"\b((?:INV|FAC|FACT|FA)[\s\-_:]*[A-Z0-9][A-Z0-9./\-]{2,})\b",
        ):
            match = re.search(pattern, line, re.I)
            if match:
                value = clean_invoice_number(match.group(1))
                if is_invoice_number_candidate(value):
                    return value
    fallback = re.search(r"\b((?:INV|FAC|FACT|FA)[-_./ ]?\d{3,}[-_/A-Z0-9]*)\b", text, re.I)
    if fallback:
        value = clean_invoice_number(fallback.group(1))
        if is_invoice_number_candidate(value):
            return value
    return None

def clean_invoice_number(value: str) -> str:
    value = re.sub(r"^(no|n[o°.]?|number|num(?:é|e)ro|invoice|facture|inv\.?)\s*[:\-]?\s*", "", value.strip(), flags=re.I)
    return value.strip().strip(".,;:").replace(" ", "-")

def is_invoice_number_candidate(value: str) -> bool:
    if not value or len(value) < 3 or len(value) > 40:
        return False
    if not re.search(r"\d", value):
        return False
    if re.fullmatch(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", value) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    if re.search(r"total|date|due|amount|montant|tva|vat", value, re.I):
        return False
    return bool(re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]*", value, re.I))

def detect_currency(text: str) -> str:
    if re.search(r"\$|\bUSD\b", text, re.I):
        return "USD"
    if re.search(r"£|\bGBP\b", text, re.I):
        return "GBP"
    return "EUR"

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
