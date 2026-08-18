"""Getting text out of datasheets, nameplate photos and conformity statements.

Everything here degrades rather than crashes. A missing OCR engine, an encrypted
PDF or a graphic-only brochure produces a clear message and an empty extraction,
because the fallback is always "a person reads it and types what it says" — which
is fine, as long as the tool says so instead of silently proposing Unknown as if
it had looked.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

PDF_SUFFIXES = {".pdf"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".heic"}

#: Below this much text, a PDF is almost certainly scanned images.
SCANNED_THRESHOLD = 40

OCR_MISSING_MESSAGE = (
    "Tesseract is not installed, so this file could not be read automatically. "
    "Install it (macOS: brew install tesseract · Debian/Ubuntu: apt install tesseract-ocr) "
    "and run the intake again, or read the markings off the document and enter them by hand."
)


@dataclass
class Extraction:
    text: str = ""
    method: str = "none"          # pdf-text | ocr | pdf-text+ocr | none
    pages: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.text.strip()


def sha256(path: Path) -> str:
    """Content hash of a stored file, recorded so a later revision is detectable."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(131072), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ocr_available() -> tuple[bool, str]:
    """(usable, why not). Checks the Python binding AND the tesseract binary."""
    try:
        import pytesseract
    except ImportError:
        return False, "pytesseract is not installed"
    try:
        pytesseract.get_tesseract_version()
    except Exception:
        return False, OCR_MISSING_MESSAGE
    return True, ""


def _ocr_image(path: Path) -> tuple[str, list[str]]:
    usable, why = ocr_available()
    if not usable:
        return "", [why]
    try:
        import pytesseract
        from PIL import Image
        with Image.open(path) as image:
            # Dutch alongside English: plenty of nameplates and DoCs are Dutch.
            return pytesseract.image_to_string(image, lang="eng+nld"), []
    except Exception as exc:                        # pragma: no cover - engine specific
        try:
            import pytesseract
            from PIL import Image
            with Image.open(path) as image:
                return pytesseract.image_to_string(image), [f"OCR fell back to English only: {exc}"]
        except Exception as inner:
            return "", [f"OCR failed: {inner}"]


def extract(path: str | Path) -> Extraction:
    """Read a document's text, whatever it is."""
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix in IMAGE_SUFFIXES:
        text, warnings = _ocr_image(path)
        return Extraction(text=text, method="ocr" if text.strip() else "none",
                          pages=1, warnings=warnings)

    if suffix in PDF_SUFFIXES:
        return _extract_pdf(path)

    if suffix in {".txt", ".md"}:
        return Extraction(text=path.read_text(encoding="utf-8", errors="replace"),
                          method="pdf-text", pages=1)

    return Extraction(warnings=[f"No extractor for {suffix or 'this file type'}; "
                                f"the file is stored but its text was not read."])


def _extract_pdf(path: Path) -> Extraction:
    try:
        import pdfplumber
    except ImportError:
        return Extraction(warnings=["pdfplumber is not installed — run pip install -r requirements.txt"])

    warnings: list[str] = []
    parts: list[str] = []
    pages = 0
    try:
        with pdfplumber.open(path) as pdf:
            pages = len(pdf.pages)
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
    except Exception as exc:
        return Extraction(warnings=[f"Could not read this PDF ({exc}). "
                                    f"It may be encrypted or damaged."])

    text = "\n".join(parts).strip()
    if len(text) >= SCANNED_THRESHOLD:
        return Extraction(text=text, method="pdf-text", pages=pages, warnings=warnings)

    # Little or no embedded text: a scanned or graphic-only document.
    warnings.append(
        f"This PDF has almost no selectable text ({len(text)} characters over {pages} page(s)) "
        f"— it is probably scanned or graphic-only.")
    usable, why = ocr_available()
    if not usable:
        warnings.append(why)
        return Extraction(text=text, method="none", pages=pages, warnings=warnings)

    ocr_parts: list[str] = []
    try:
        import pytesseract
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                image = page.to_image(resolution=200).original
                ocr_parts.append(pytesseract.image_to_string(image, lang="eng+nld"))
    except Exception as exc:                        # pragma: no cover - engine specific
        warnings.append(f"Could not OCR the pages ({exc}). Read the document by hand.")
        return Extraction(text=text, method="none", pages=pages, warnings=warnings)

    combined = "\n".join([text, *ocr_parts]).strip()
    return Extraction(text=combined, method="pdf-text+ocr" if text else "ocr",
                      pages=pages, warnings=warnings)
