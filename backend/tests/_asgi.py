"""Chamada ASGI mínima (sem httpx) para testar rotas FastAPI."""
import asyncio
import json


def chamar(app, metodo, caminho, corpo=None, cabecalhos=None, cliente=("127.0.0.1", 50000)):
    dados = b"" if corpo is None else json.dumps(corpo).encode("utf-8")
    hdrs = [(b"host", b"testserver")]
    if corpo is not None:
        hdrs += [(b"content-type", b"application/json"), (b"content-length", str(len(dados)).encode())]
    for k, v in (cabecalhos or {}).items():
        hdrs.append((k.lower().encode(), v.encode()))
    caminho, _, consulta = caminho.partition("?")
    escopo = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": metodo,
              "scheme": "http", "path": caminho, "raw_path": caminho.encode(), "query_string": consulta.encode(),
              "headers": hdrs, "client": cliente, "server": ("testserver", 80)}
    saida = {"status": None, "headers": {}, "body": b""}
    enviado = False

    async def receive():
        nonlocal enviado
        if not enviado:
            enviado = True
            return {"type": "http.request", "body": dados, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(msg):
        if msg["type"] == "http.response.start":
            saida["status"] = msg["status"]
            saida["headers"] = {k.decode().lower(): v.decode() for k, v in msg["headers"]}
        elif msg["type"] == "http.response.body":
            saida["body"] += msg.get("body", b"")

    asyncio.run(app(escopo, receive, send))
    corpo_json = None
    if saida["body"]:
        try:
            corpo_json = json.loads(saida["body"])
        except ValueError:
            corpo_json = saida["body"]
    return saida["status"], saida["headers"], corpo_json
