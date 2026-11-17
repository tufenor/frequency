"""Captação regional de academias via OpenStreetMap/Overpass."""
from __future__ import annotations
import json
import urllib.parse
import urllib.request
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
TERMOS = ("sport=fitness", "leisure=fitness_centre", "leisure=sports_centre")
def construir_consulta_osm(latitude: float, longitude: float, raio_metros: int) -> str:
    raio = max(100, min(int(raio_metros), 50000))
    filtros = "".join(f"node(around:{raio},{latitude},{longitude})[{t}];way(around:{raio},{latitude},{longitude})[{t}];relation(around:{raio},{latitude},{longitude})[{t}];" for t in TERMOS)
    return f"[out:json][timeout:25];({filtros});out center tags;"
def consultar_osm(latitude: float, longitude: float, raio_metros: int, timeout: int = 35) -> list[dict]:
    payload = urllib.parse.urlencode({"data": construir_consulta_osm(latitude, longitude, raio_metros)}).encode()
    req = urllib.request.Request(OVERPASS_URL, data=payload, headers={"User-Agent": "Frequency/1.0 (lead research)"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode()).get("elements", [])
def geocodificar_regiao(pais: str, cidade: str = "", bairro: str = "", timeout: int = 20) -> tuple[float, float] | None:
    partes = [p.strip() for p in (bairro, cidade, pais) if p and p.strip()]
    if not partes:
        return None
    query = urllib.parse.urlencode({"q": ", ".join(partes), "format": "jsonv2", "limit": 1})
    req = urllib.request.Request(f"{NOMINATIM_URL}?{query}", headers={"User-Agent": "Frequency/1.0 (lead research)"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        resultados = json.loads(response.read().decode())
    if not resultados:
        return None
    return float(resultados[0]["lat"]), float(resultados[0]["lon"])

def lead_osm(elemento: dict, cidade: str, pais: str) -> dict:
    tags = elemento.get("tags") or {}; centro = elemento.get("center") or {}
    nome = (tags.get("name") or tags.get("brand") or "Academia sem nome").strip()
    endereco = " ".join(filter(None, [tags.get("addr:street"), tags.get("addr:housenumber"), tags.get("addr:suburb")]))
    telefone = tags.get("contact:phone") or tags.get("phone") or ""
    site = tags.get("contact:website") or tags.get("website") or tags.get("contact:instagram") or ""
    return {"nome": nome, "cidade": cidade, "endereco": endereco, "telefone": telefone, "site_instagram": site, "observacoes": f"OSM {pais}; id {elemento.get('type')}:{elemento.get('id')}; coordenadas {elemento.get('lat', centro.get('lat'))},{elemento.get('lon', centro.get('lon'))}", "origem": "osm", "osm_id": f"{elemento.get('type')}:{elemento.get('id')}"}
