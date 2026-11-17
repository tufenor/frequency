"""Country defaults for the first supported billing locales."""

from __future__ import annotations

import unicodedata


def preferencias_iniciais_academia(pais: str | None) -> tuple[str, str]:
    normalizado = unicodedata.normalize("NFKD", pais or "")
    normalizado = "".join(
        caractere for caractere in normalizado
        if not unicodedata.combining(caractere)
    )
    normalizado = " ".join(normalizado.casefold().split())
    if normalizado in {
        "bolivia",
        "bo",
        "estado plurinacional de bolivia",
    }:
        return "es-BO", "BOB"
    if normalizado in {"ar", "argentina", "cl", "chile", "co", "colombia", "ec", "ecuador", "es", "espana", "mx", "mexico", "pe", "peru", "py", "paraguay", "uy", "uruguay", "ve", "venezuela"}:
        return "es-BO", "USD"
    if normalizado in {"en", "us", "united states", "gb", "united kingdom", "ca", "canada", "au", "australia", "nz", "new zealand", "ie", "ireland"}:
        return "en-US", "USD"
    if normalizado in {"zh", "cn", "china", "sg", "singapore"}:
        return "zh-CN", "CNY"
    if normalizado in {"hi", "in", "india"}:
        return "hi-IN", "INR"
    return "pt-BR", "BRL"
