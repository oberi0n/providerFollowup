import io
import json
import os
import re
from datetime import datetime
from decimal import Decimal
from typing import Optional

import pytesseract
import requests
from fastapi import FastAPI, HTTPException
from minio import Minio
from pdf2image import convert_from_bytes
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from pydantic import BaseModel

app = FastAPI(title="Provider Follow-up OCR.space OCR", version="1.0.0")

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000").replace("http://", "").replace("https://", "")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "invoices")
OCR_SPACE_API_KEY = os.getenv("OCR_SPACE_API_KEY", "")
OCR_SPACE_URL = os.getenv("OCR_SPACE_URL", "https://api.ocr.space/parse/image")
OCR_SPACE_LANGUAGES = [lang.strip() for lang in os.getenv("OCR_SPACE_LANGUAGES", "fre,eng").split(",") if lang.strip()]
OCR_SPACE_ENGINE = os.getenv("OCR_SPACE_ENGINE", "2")
TESSERACT_LANGS = os.getenv("TESSERACT_LANGS", "fra+eng")
TESSERACT_CONFIG = "--oem 3 --psm 4 -c preserve_interword_spaces=1"
OCR_AI_ENABLED = os.getenv("OCR_AI_ENABLED", "true").lower() == "true"
OCR_AI_PROVIDER = os.getenv("OCR_AI_PROVIDER", "ollama").lower()
OCR_AI_URL = os.getenv("OCR_AI_URL", "http://localhost:11434/api/generate")
OCR_AI_MODEL = os.getenv("OCR_AI_MODEL", "llama3.2:3b")
OCR_AI_TIMEOUT = int(os.getenv("OCR_AI_TIMEOUT", "45"))
OCR_AI_MAX_CHARS = int(os.getenv("OCR_AI_MAX_CHARS", "6000"))
OCR_AI_NUM_CTX = int(os.getenv("OCR_AI_NUM_CTX", "2048"))
OCR_AI_NUM_PREDICT = int(os.getenv("OCR_AI_NUM_PREDICT", "256"))

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
    return {
        "status": "ok",
        "engine": "ocr.space",
        "ocrSpaceUrl": OCR_SPACE_URL,
        "ocrSpaceLanguages": OCR_SPACE_LANGUAGES,
        "fallback": "tesseract-local",
        "apiKeyConfigured": bool(OCR_SPACE_API_KEY),
        "aiInterpretationEnabled": OCR_AI_ENABLED,
        "aiProvider": OCR_AI_PROVIDER if OCR_AI_ENABLED else None,
        "aiModel": OCR_AI_MODEL if OCR_AI_ENABLED else None,
    }

@app.post("/ocr/extract", response_model=OcrResponse)
def extract(request: OcrRequest):
    try:
        response = minio_client.get_object(MINIO_BUCKET, request.objectKey)
        data = response.read()
        response.close()
        response.release_conn()
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Cannot read object from MinIO: {exc}") from exc

    filename = request.filename or "invoice-file"
    content_type = request.contentType or guess_content_type(filename, data)
    raw_text = extract_text(data, filename, content_type)
    suggestions = interpret_suggestions(raw_text)
    filled = sum(1 for value in suggestions.model_dump().values() if value not in (None, ""))
    confidence = "HIGH" if filled >= 5 else "MEDIUM" if filled >= 3 else "LOW"
    return OcrResponse(rawText=raw_text, suggestions=suggestions, confidence=confidence)


def interpret_suggestions(text: str) -> Suggestions:
    regex_suggestions = parse_suggestions(text)
    if not OCR_AI_ENABLED or OCR_AI_PROVIDER != "ollama" or not text.strip():
        return regex_suggestions

    ai_suggestions = interpret_with_ollama(text, regex_suggestions)
    if ai_suggestions is None:
        return regex_suggestions
    return merge_suggestions(ai_suggestions, regex_suggestions)

def interpret_with_ollama(text: str, regex_suggestions: Suggestions) -> Optional[Suggestions]:
    prompt = build_ai_prompt(text, regex_suggestions)
    try:
        response = requests.post(
            OCR_AI_URL,
            json={
                "model": OCR_AI_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.0, "num_ctx": OCR_AI_NUM_CTX, "num_predict": OCR_AI_NUM_PREDICT},
            },
            timeout=OCR_AI_TIMEOUT,
        )
        response.raise_for_status()
        ollama_payload = response.json()
        return suggestions_from_ai_payload(extract_json_object(ollama_payload.get("response", "")))
    except Exception:
        # AI interpretation is an optional improvement layer. OCR must remain usable with deterministic regex parsing.
        return None

def build_ai_prompt(text: str, regex_suggestions: Suggestions) -> str:
    return f"""Tu es un parseur de factures fournisseur français/anglais.
Retourne strictement un objet JSON valide, sans Markdown ni commentaire.
Utilise uniquement le texte OCR fourni. Si une valeur est incertaine ou absente, mets null.
Le fournisseur est l'émetteur de la facture, pas le client ni l'adresse de facturation.
Le numéro de facture doit être l'identifiant de la facture, pas une date, un SIRET, un IBAN ou un numéro client.
Les dates doivent être au format YYYY-MM-DD. Les montants doivent être des nombres avec un point décimal.
Champs attendus: supplierName, invoiceNumber, invoiceDate, amountHt, vatAmount, amountTtc, currency.

Indices regex existants, à corriger si le texte OCR indique mieux:
{json.dumps(regex_suggestions.model_dump(), ensure_ascii=False)}

Texte OCR:
{text[:OCR_AI_MAX_CHARS]}
"""

def extract_json_object(value: str) -> dict:
    start = value.find("{")
    end = value.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in AI response")
    payload = json.loads(value[start:end + 1])
    if not isinstance(payload, dict):
        raise ValueError("AI response is not a JSON object")
    return payload

def suggestions_from_ai_payload(payload: dict) -> Suggestions:
    return Suggestions(
        supplierName=normalize_optional_string(payload.get("supplierName")),
        invoiceNumber=normalize_optional_string(payload.get("invoiceNumber")),
        invoiceDate=normalize_ai_date(payload.get("invoiceDate")),
        amountHt=coerce_amount(payload.get("amountHt")),
        vatAmount=coerce_amount(payload.get("vatAmount")),
        amountTtc=coerce_amount(payload.get("amountTtc")),
        currency=normalize_currency(payload.get("currency")),
    )

def merge_suggestions(ai_suggestions: Suggestions, fallback: Suggestions) -> Suggestions:
    ai = ai_suggestions.model_dump()
    regex = fallback.model_dump()
    merged = {}
    for key, regex_value in regex.items():
        ai_value = ai.get(key)
        merged[key] = ai_value if ai_value not in (None, "") else regex_value
    if not merged.get("currency"):
        merged["currency"] = "EUR"
    return Suggestions(**merged)

def normalize_optional_string(value) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip().strip('"\'`')
    return cleaned[:120] if cleaned else None

def normalize_ai_date(value) -> Optional[str]:
    value = normalize_optional_string(value)
    if not value:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    return parse_date(value)

def coerce_amount(value) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return parse_amount_string(str(value))

def normalize_currency(value) -> Optional[str]:
    value = normalize_optional_string(value)
    if not value:
        return "EUR"
    upper = value.upper()
    if upper in {"€", "EURO", "EUROS"}:
        return "EUR"
    return upper[:3]


def extract_text(data: bytes, filename: str, content_type: str) -> str:
    ocr_space_text = extract_text_with_ocr_space(data, filename, content_type)
    if ocr_space_text.strip():
        return ocr_space_text
    return extract_text_with_tesseract(data, filename, content_type)

def extract_text_with_ocr_space(data: bytes, filename: str, content_type: str) -> str:
    if not OCR_SPACE_API_KEY:
        return ""

    candidates = []
    errors = []
    languages = OCR_SPACE_LANGUAGES or ["eng"]
    upload_variants = build_ocr_space_upload_variants(data, filename, content_type)
    for language in languages:
        for variant_name, variant_data, variant_content_type in upload_variants:
            for is_table in ("true", "false"):
                try:
                    response = requests.post(
                        OCR_SPACE_URL,
                        headers={"apikey": OCR_SPACE_API_KEY},
                        data={
                            "language": language,
                            "isOverlayRequired": "false",
                            "OCREngine": OCR_SPACE_ENGINE,
                            "scale": "true",
                            "detectOrientation": "true",
                            "isTable": is_table,
                        },
                        files={"file": (variant_name, variant_data, variant_content_type)},
                        timeout=90,
                    )
                    response.raise_for_status()
                    payload = response.json()
                    if payload.get("IsErroredOnProcessing"):
                        errors.append(str(payload.get("ErrorMessage") or payload.get("ErrorDetails") or "OCR.space processing error"))
                        continue
                    parsed_text = "\n".join(result.get("ParsedText", "") for result in payload.get("ParsedResults", []) if result.get("ParsedText"))
                    if parsed_text.strip():
                        candidates.append(parsed_text)
                except Exception as exc:
                    errors.append(str(exc))

    if candidates:
        return max(candidates, key=score_ocr_text)
    if errors:
        # Keep the endpoint usable if OCR.space has a temporary issue: local Tesseract remains a fallback.
        return ""
    return ""

def build_ocr_space_upload_variants(data: bytes, filename: str, content_type: str) -> list[tuple[str, bytes, str]]:
    variants = [(filename, data, content_type)]
    is_pdf = filename.lower().endswith(".pdf") or content_type == "application/pdf" or data[:4] == b"%PDF"
    if is_pdf:
        return variants
    try:
        image = Image.open(io.BytesIO(data))
        prepared = prepare_image(image)
        buffer = io.BytesIO()
        prepared.save(buffer, format="PNG")
        variants.append((f"{filename.rsplit('.', 1)[0]}-enhanced.png", buffer.getvalue(), "image/png"))
    except Exception:
        pass
    return variants

def extract_text_with_tesseract(data: bytes, filename: str, content_type: str) -> str:
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
            texts.append(max(text_candidates, key=score_ocr_text))
        return "\n\n".join(texts)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"OCR extraction failed: {exc}") from exc

def score_ocr_text(text: str) -> tuple[int, int, int]:
    suggestions = parse_suggestions(text) if text.strip() else Suggestions()
    filled_fields = sum(1 for value in suggestions.model_dump().values() if value not in (None, ""))
    return (filled_fields * 25 + len(extract_labeled_lines(text)) * 5, len(text), -text.count("�"))

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
    amount_ttc = find_labeled_amount(normalized_text, r"total\s*(?:ttc|t\.t\.c\.|incl\.?\s*tax)?|montant\s*ttc|net\s*à\s*payer|amount\s*due|balance\s*due|grand\s*total|total\s*due")
    amount_ht = find_labeled_amount(normalized_text, r"total\s*ht|montant\s*ht|sous\s*total|subtotal|hors\s*taxe|net\s*amount|amount\s*before\s*tax")
    vat = find_labeled_amount(normalized_text, r"\btva\b|\bvat\b|taxe|\btax\b")
    if amount_ttc is None:
        amount_ttc = find_largest_document_amount(normalized_text)
    return Suggestions(supplierName=supplier, invoiceNumber=invoice_number, invoiceDate=invoice_date,
                       amountHt=amount_ht, vatAmount=vat, amountTtc=amount_ttc, currency=currency)

def normalize_ocr_text(text: str) -> str:
    replacements = {"|": " ", "—": "-", "–": "-", "N°": "No", "n°": "No", "№": "No"}
    for source, target in replacements.items():
        text = text.replace(source, target)
    return re.sub(r"[ \t]+", " ", text)

def find_explicit_supplier(lines: list[str]) -> Optional[str]:
    for index, line in enumerate(lines[:30]):
        match = re.search(r"(?:fournisseur|supplier|vendor|seller|from|émetteur)\s*[:\-]\s*(.+)", line, re.I)
        if match:
            candidate = clean_supplier_line(match.group(1))
            if is_supplier_candidate(candidate):
                return candidate[:120]
            for next_line in lines[index + 1:index + 4]:
                candidate = clean_supplier_line(next_line)
                if is_supplier_candidate(candidate):
                    return candidate[:120]
    return None

def find_supplier(lines: list[str]) -> Optional[str]:
    explicit_supplier = find_explicit_supplier(lines)
    if explicit_supplier:
        return explicit_supplier
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

AMOUNT_RE = re.compile(r"(?<!\d)(?:\d{1,3}(?:[ .\u00a0]\d{3})+|\d+)(?:[,.]\d{2})(?!\d)")

def find_labeled_amount(text: str, label_pattern: str) -> Optional[float]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    label_re = re.compile(label_pattern, re.I)
    for index, line in enumerate(lines):
        if not label_re.search(line):
            continue
        window = " ".join(lines[index:index + 2])
        amounts = extract_amounts(window)
        if amounts:
            # Invoice rows often contain rate, VAT and total on one line; the payable value is usually the last amount.
            return amounts[-1]
    return None

def find_largest_document_amount(text: str) -> Optional[float]:
    amounts = extract_amounts(text)
    if not amounts:
        return None
    return max(amounts)

def extract_amounts(text: str) -> list[float]:
    amounts = []
    for match in AMOUNT_RE.finditer(text):
        before = text[max(0, match.start() - 8):match.start()]
        after = text[match.end():match.end() + 3]
        if "%" in after or re.search(r"\b(?:tva|vat|tax)\s*$", before, re.I) and "%" in text[match.end():match.end() + 8]:
            continue
        parsed = parse_amount_string(match.group(0))
        if parsed is not None:
            amounts.append(parsed)
    return amounts

def parse_amount_string(value: str) -> Optional[float]:
    normalized = value.replace(" ", "").replace("\u00a0", "")
    if "," in normalized and "." in normalized:
        # The right-most separator is usually decimal; handle both 1,234.56 and 1.234,56.
        if normalized.rfind(".") > normalized.rfind(","):
            normalized = normalized.replace(",", "")
        else:
            normalized = normalized.replace(".", "").replace(",", ".")
    else:
        normalized = normalized.replace(",", ".")
    normalized = re.sub(r"[^0-9.]", "", normalized)
    try:
        return float(Decimal(normalized))
    except Exception:
        return None

def find_amount(text: str, patterns: list[str]) -> Optional[float]:
    for pattern in patterns:
        value = find_first(text, [pattern])
        if value is not None:
            parsed = parse_amount_string(value)
            if parsed is not None:
                return parsed
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

def guess_content_type(filename: str, data: bytes) -> str:
    lower_name = filename.lower()
    if lower_name.endswith(".pdf") or data[:4] == b"%PDF":
        return "application/pdf"
    if lower_name.endswith(".png") or data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if lower_name.endswith(".jpg") or lower_name.endswith(".jpeg") or data[:2] == b"\xff\xd8":
        return "image/jpeg"
    return "application/octet-stream"
