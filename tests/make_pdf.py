"""Builds minimal, real PDFs for the intake tests — no extra dependency needed."""

from pathlib import Path


def make_pdf(path: Path, lines: list[str]) -> Path:
    escaped = []
    for line in lines:
        line = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        escaped.append(f"({line}) Tj T*\n")
    content = "BT /F1 11 Tf 40 780 Td 14 TL\n" + "".join(escaped) + "ET"

    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    body, offsets = "%PDF-1.4\n", []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(body))
        body += f"{index} 0 obj\n{obj}\nendobj\n"
    xref = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    body += "".join(f"{offset:010d} 00000 n \n" for offset in offsets)
    body += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body.encode("latin-1"))
    return path


FULL_MARKINGS = [
    "Alfen Eve Single Pro-line - technical datasheet",
    "The wallbox is CE marked in accordance with applicable EU directives.",
    "The integrated kWh meter bears M 26 0122 and is certified to MI-003,",
    "accuracy Class B in accordance with EN 50470-3.",
]

CE_ONLY = [
    "Generic Wallbox - technical datasheet",
    "The product is CE marked and complies with the Low Voltage Directive",
    "and the EMC Directive. Rated 22 kW, Type 2 socket.",
]
