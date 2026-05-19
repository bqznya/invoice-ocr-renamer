from __future__ import annotations

from dataclasses import dataclass
import re


SHORT_CODE_RE = r"[А-ЯЁA-Z]{1,3}\d{2,4}[А-ЯЁA-Z]{0,3}"
LONG_ID_RE = r"201000\d{4,}"


@dataclass(frozen=True)
class InvoiceItem:
    short_code: str
    long_id: str
    weight: str
    total: str
    source_line: str


def normalize_ocr_text(text: str) -> str:
    replacements = {
        "\u00a0": " ",
        "—": "-",
        "–": "-",
        "`": "",
        "‘": "",
        "’": "",
        "|": " ",
        "[": " ",
        "]": " ",
        "{": " ",
        "}": " ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return re.sub(r"[ \t]+", " ", text.upper())


def normalize_decimal(value: str) -> str:
    return value.replace(" ", "").replace(",", ".")


def normalize_money(value: str) -> str:
    value = value.replace(" ", "").replace(",", ".")
    if value.endswith(".00"):
        value = value[:-3]
    return value


def parse_invoice_text(text: str) -> list[InvoiceItem]:
    text = normalize_ocr_text(text)
    items: list[InvoiceItem] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        item = parse_invoice_line(line)
        if item is not None:
            items.append(item)

    return items


def parse_invoice_line(line: str) -> InvoiceItem | None:
    normalized = normalize_ocr_text(line)
    product_match = _find_product_match(normalized)
    if product_match is None:
        return None

    short_code, long_id = product_match.group("short"), product_match.group("long")
    tail = normalized[product_match.end() :]
    tail = re.split(r"\bВСЕГО\b|\bИТОГО\b", tail, maxsplit=1)[0]

    weight = _extract_weight(tail)
    total = _extract_total(tail)

    return InvoiceItem(
        short_code=short_code,
        long_id=long_id,
        weight=weight,
        total=total,
        source_line=line,
    )


def _find_product_match(line: str) -> re.Match[str] | None:
    patterns = (
        rf"(?P<short>{SHORT_CODE_RE})\s*\(\s*(?P<long>{LONG_ID_RE})\s*\)",
        rf"(?P<short>{SHORT_CODE_RE})\s+(?P<long>{LONG_ID_RE})",
        rf"(?P<short>{SHORT_CODE_RE})\s*[^0-9А-ЯЁA-Z]{{0,6}}\s*(?P<long>{LONG_ID_RE})",
    )

    matches: list[re.Match[str]] = []
    for pattern in patterns:
        matches.extend(re.finditer(pattern, line))

    if not matches:
        return None

    return max(matches, key=lambda match: match.start())


def _extract_weight(text_after_id: str) -> str:
    for decimal_match in re.finditer(r"(?<!\d)(\d{1,3}[,.]\d{1,3})(?!\d)", text_after_id):
        value = decimal_match.group(1)
        integer_part = re.split(r"[,.]", value, maxsplit=1)[0]
        if len(integer_part) > 2:
            continue
        normalized = normalize_decimal(value)
        try:
            if 0 < float(normalized) < 100:
                return normalized
        except ValueError:
            continue
    return ""


def _extract_total(text_after_id: str) -> str:
    money_matches = re.findall(r"(?<!\d)(\d{1,3}(?:\s\d{3})+|\d{4,})(?:[,.]\d{2})?(?!\d)", text_after_id)
    if money_matches:
        normalized = [normalize_money(match) for match in money_matches]
        reliable = [value for value in normalized if value.isdigit() and int(value) >= 1000]
        return reliable[-1] if reliable else normalized[-1]

    integer_matches = re.findall(r"(?<!\d)(\d{3,})(?!\d)", text_after_id)
    return integer_matches[-1] if integer_matches else ""
