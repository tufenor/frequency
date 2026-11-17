"""Integração opcional com Apify Google Maps Scraper."""
from __future__ import annotations
import json, os, urllib.parse, urllib.request

API_BASE = "https://api.apify.com/v2"
ACTOR = "compass~crawler-google-places"

def buscar_apify(termos: list[str], local: str, limite: int = 1000, timeout: int = 120) -> list[dict]:
    token = os.getenv("APIFY_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("APIFY_API_TOKEN ausente")
    entrada = {
        "searchStringsArray": termos,
        "locationQuery": local,
        "maxCrawledPlacesPerSearch": max(1, min(limite, 1000)),
        "language": "es",
        "website": "allPlaces",
        "scrapeContacts": True,
        "scrapePlaceDetailPage": True,
    }
    query = urllib.parse.urlencode({"token": token, "waitForFinish": 120})
    req = urllib.request.Request(f"{API_BASE}/acts/{ACTOR}/runs?{query}", data=json.dumps(entrada).encode(), headers={"Content-Type": "application/json", "User-Agent": "Frequency/1.0"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        run = json.loads(response.read().decode())
    dataset_id = run.get("data", {}).get("defaultDatasetId")
    if not dataset_id:
        raise RuntimeError("Apify não retornou dataset")
    with urllib.request.urlopen(f"{API_BASE}/datasets/{dataset_id}/items?token={urllib.parse.quote(token)}&clean=true", timeout=timeout) as response:
        return json.loads(response.read().decode())

def lead_apify(item: dict, pais: str, cidade: str) -> dict:
    emails = item.get("emails") or item.get("email") or ""
    if isinstance(emails, list):
        emails = next((str(value).strip() for value in emails if value), "")
    elif isinstance(emails, dict):
        emails = next((str(value).strip() for value in emails.values() if value), "")
    return {"nome": item.get("title") or item.get("name") or "Academia sem nome", "cidade": item.get("city") or cidade, "endereco": item.get("address") or item.get("street") or "", "telefone": item.get("phone") or item.get("phoneUnformatted") or "", "email": emails, "site_instagram": item.get("website") or item.get("url") or "", "avaliacao": item.get("totalScore") or item.get("rating"), "observacoes": f"Apify Google Maps; {pais}" , "origem": "apify", "osm_id": None}
