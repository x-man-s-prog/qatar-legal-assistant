# -*- coding: utf-8 -*-
"""
OCR Extractor for Scanned Legal PDFs
=====================================
Fallback when PyMuPDF returns 0 text from image-based PDFs.
Uses Tesseract with Arabic+English, with image preprocessing.
"""
import io, re, logging
from typing import Optional

log = logging.getLogger("ocr")

MIN_TEXT_THRESHOLD = 50  # If PyMuPDF returns fewer chars, treat as scanned


def is_scanned_pdf(pdf_text: str) -> bool:
    """Detect if a PDF extraction result indicates a scanned document."""
    if not pdf_text:
        return True
    clean = pdf_text.strip()
    if len(clean) < MIN_TEXT_THRESHOLD:
        return True
    # If mostly non-printable or replacement chars
    arabic_chars = len(re.findall(r"[\u0600-\u06FF]", clean))
    latin_chars = len(re.findall(r"[a-zA-Z]", clean))
    if (arabic_chars + latin_chars) < len(clean) * 0.1:
        return True
    return False


def ocr_pdf(pdf_bytes: bytes, dpi: int = 200) -> Optional[str]:
    """
    Extract text from scanned PDF using Tesseract OCR.
    Converts each page to image, preprocesses, then OCRs.
    """
    import fitz  # PyMuPDF for rendering
    import cv2
    import numpy as np
    import pytesseract
    from PIL import Image

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages_text = []

        max_pages = min(len(doc), 15)  # Cap at 15 pages for performance
        if len(doc) > max_pages:
            log.info("[OCR_START] PDF has %d pages, capping OCR at %d", len(doc), max_pages)

        for page_num in range(max_pages):
            log.info("[OCR_START] page %d/%d", page_num + 1, max_pages)

            # Render page to image at specified DPI
            page = doc[page_num]
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)

            # Convert to numpy array
            img_data = pix.tobytes("png")
            img_array = np.frombuffer(img_data, dtype=np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

            if img is None:
                log.warning("[OCR_FAIL] page %d: could not decode image", page_num + 1)
                continue

            # Preprocessing pipeline
            processed = _preprocess(img)

            # OCR with Tesseract (Arabic + English)
            pil_img = Image.fromarray(processed)
            text = pytesseract.image_to_string(
                pil_img,
                lang="ara+eng",
                config="--psm 6 --oem 3"  # Block of text mode + LSTM
            )

            if text.strip():
                cleaned = _clean_ocr_text(text)
                pages_text.append(cleaned)
                log.info("[OCR_SUCCESS] page %d: %d chars", page_num + 1, len(cleaned))
            else:
                log.warning("[OCR_FAIL] page %d: no text extracted", page_num + 1)

        doc.close()

        if pages_text:
            full = "\n\n".join(pages_text)
            log.info("[OCR_SUCCESS] total: %d pages, %d chars", len(pages_text), len(full))
            return full

        log.warning("[OCR_FAIL] no text from any page")
        return None

    except Exception as e:
        log.error("[OCR_FAIL] error: %s", e)
        return None


def _preprocess(img):
    """Preprocess image for better OCR accuracy."""
    import cv2

    # Convert to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Denoise
    denoised = cv2.fastNlMeansDenoising(gray, h=10)

    # Adaptive threshold (handles uneven lighting in scans)
    thresh = cv2.adaptiveThreshold(
        denoised, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=15, C=8
    )

    return thresh


def _clean_ocr_text(text: str) -> str:
    """Clean up common OCR artifacts."""
    # Remove null bytes
    text = text.replace("\x00", "")

    # Fix common Arabic OCR errors
    replacements = {
        "ﻻ": "لا",
        "ﷲ": "الله",
        "\u06cc": "\u064a",  # Farsi yeh → Arabic yeh
        "\u0643": "\u0643",  # Keep kaf
        "٫": ".",  # Arabic decimal → period
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    # Normalize Arabic forms
    text = re.sub(r"[\u0610-\u061A\u064B-\u065F\u0670]", "", text)  # Remove diacritics
    text = re.sub(r"[آأإ]", "ا", text)  # Normalize alef variants

    # Remove stray single characters and OCR noise
    text = re.sub(r"(?<=\s)[^\u0600-\u06FFa-zA-Z0-9\(\)\-\.]{1}(?=\s)", " ", text)

    # Normalize whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def extract_pdf_with_ocr_fallback(pdf_bytes: bytes) -> tuple[str, str]:
    """
    Try PyMuPDF first, fall back to OCR if scanned.
    Returns (text, method) where method is "pdf_text" or "ocr".
    """
    import fitz

    # Try PyMuPDF text extraction first
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages = []
        for i in range(len(doc)):
            t = doc[i].get_text("text")
            if t.strip():
                pages.append(t)
        doc.close()
        text = "\n\n".join(pages)

        if not is_scanned_pdf(text):
            log.info("[PDF_PARSE] text extraction: %d pages, %d chars", len(pages), len(text))
            return text, "pdf_text"
    except Exception as e:
        log.warning("[PDF_PARSE] text extraction failed: %s", e)

    # Fallback to OCR
    log.info("[OCR_START] falling back to OCR for scanned PDF")
    ocr_text = ocr_pdf(pdf_bytes)
    if ocr_text and len(ocr_text.strip()) >= MIN_TEXT_THRESHOLD:
        return ocr_text, "ocr"

    return "", "failed"
