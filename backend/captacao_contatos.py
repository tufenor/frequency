"""Enriquecimento independente de contatos comerciais em sites públicos."""
from __future__ import annotations

import re
import urllib.parse
import urllib.request

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:\+\d{1,3}[\s().-]*)?(?:\d[\s().-]*){8,15}")
MAX_BYTES = 700_000


def _url_candidates(url: str) -> list[str]:
    value = (url or "").strip()
    if not value or "google.com/maps" in value.lower():
        return []
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    parsed = urllib.parse.urlsplit(value)
    base = f"{parsed.scheme}://{parsed.netloc}"
    return [value, urllib.parse.urljoin(base, "/contato"), urllib.parse.urljoin(base, "/contact"), urllib.parse.urljoin(base, "/contacto")]


def buscar_contatos_publicos(url: str, timeout: int = 3) -> dict[str, str]:
    emails: list[str] = []
    phones: list[str] = []
    for candidate in _url_candidates(url):
        try:
            request = urllib.request.Request(candidate, headers={"User-Agent": "FrequencyContactBot/1.0 (+https://frequencygym.tech)"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                html = response.read(MAX_BYTES).decode("utf-8", errors="ignore")
            emails.extend(EMAIL_RE.findall(html))
            for value in re.findall(r"(?:wa\.me/|whatsapp[^\"']*?phone=)(\+?\d{8,15})", html, re.I):
                phones.append(value)
            for value in PHONE_RE.findall(re.sub(r"<[^>]+>", " ", html)):
                digits = re.sub(r"\D", "", value)
                if 8 <= len(digits) <= 15:
                    phones.append(value.strip())
        except (OSError, ValueError, UnicodeError):
            continue
    email = next((x.lower() for x in emails if not x.lower().endswith((".png", ".jpg"))), "")
    phone = next((x for x in phones if len(re.sub(r"\D", "", x)) >= 8), "")
    return {"email": email, "telefone": phone}
