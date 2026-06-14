"""In-memory PDF extraction using pdfplumber, with Claude AI OCR and field parsing."""
from __future__ import annotations
import base64
import io
import pdfplumber
import config


def extract_text(pdf_bytes: bytes) -> str:
    """Extract all text from a PDF. Falls back to Claude vision OCR for scanned PDFs."""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    text = "\n".join(pages)
    if text.strip():
        return text

    # Scanned PDF — use Claude vision to OCR each page
    return _claude_ocr(pdf_bytes)


def _claude_ocr(pdf_bytes: bytes) -> str:
    """Render PDF pages as images and send to Claude for OCR."""
    import fitz  # PyMuPDF
    import anthropic

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_texts = []

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    for page in doc:
        # Render at 200 DPI
        mat = fitz.Matrix(200 / 72, 200 / 72)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        img_b64 = base64.standard_b64encode(img_bytes).decode()

        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": img_b64},
                    },
                    {
                        "type": "text",
                        "text": (
                            "This is a scanned medical referral letter. "
                            "Transcribe ALL text exactly as it appears, preserving layout. "
                            "Include every field label and value. Output plain text only."
                        ),
                    },
                ],
            }],
        )
        page_texts.append(resp.content[0].text)

    return "\n".join(page_texts)


def parse_fields(text: str) -> dict[str, str]:
    """Use Claude to intelligently extract clinical fields from any referral letter format."""
    import anthropic

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    prompt = f"""Extract the following fields from this medical referral letter.
Return ONLY a JSON object with exactly these keys. Use empty string "" if a field is not found.

Fields to extract:
- patient_name: Full name of the patient
- patient_dob: Patient date of birth (as written in the document)
- medicare_number: Medicare card number (format: 4 digits space 5 digits space 1 digit)
- irn: Individual Reference Number (the single digit after the Medicare number, or labelled IRN)
- condition: The medical condition, diagnosis, or reason for referral
- referral_date: The date of the referral letter
- doctor_name: The referring doctor's full name
- doctor_provider_no: The referring doctor's provider number
- doctor_email: The referring doctor's email address

Referral letter text:
{text}

Return only valid JSON, no explanation."""

    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = resp.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    import json
    fields = json.loads(raw)

    # Ensure all expected keys exist
    defaults = {
        "patient_name": "", "patient_dob": "", "medicare_number": "",
        "irn": "", "condition": "", "referral_date": "",
        "doctor_name": "", "doctor_provider_no": "", "doctor_email": "",
    }
    defaults.update({k: v for k, v in fields.items() if k in defaults})
    return defaults
