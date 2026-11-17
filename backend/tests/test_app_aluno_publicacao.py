import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from backend.tests import _path  # noqa: F401
from backend.tests._asgi import chamar
import app_aluno_publicacao as pub


class _Base(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        self.tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self.tmp.name)
        (self.raiz / "app").mkdir()
        (self.raiz / "ota").mkdir()
        (self.raiz / "web").mkdir()
        os.environ["FREQUENCY_APP_ALUNO_DIR"] = str(self.raiz / "app")
        os.environ["FREQUENCY_OTA_DIR"] = str(self.raiz / "ota")
        os.environ["FREQUENCY_APP_ALUNO_WEB_DIR"] = str(self.raiz / "web")
        os.environ["FREQUENCY_PUBLIC_URL"] = "https://exemplo.test"
        self.app = FastAPI()
        self.app.include_router(pub.router)

    def tearDown(self):
        for k in ("FREQUENCY_APP_ALUNO_DIR", "FREQUENCY_OTA_DIR", "FREQUENCY_APP_ALUNO_WEB_DIR", "FREQUENCY_PUBLIC_URL"):
            os.environ.pop(k, None)
        self.tmp.cleanup()

    def _exportar(self, runtime="0.4.0", bundle=b"console.log(1)"):
        ota = self.raiz / "ota"
        (ota / "_expo/static/js/android").mkdir(parents=True, exist_ok=True)
        (ota / "assets").mkdir(exist_ok=True)
        (ota / "_expo/static/js/android/index-abc.hbc").write_bytes(bundle)
        (ota / "assets/logo").write_bytes(b"\x89PNGfake")
        (ota / "metadata.json").write_text(json.dumps({"version": 0, "bundler": "metro", "fileMetadata": {"android": {
            "bundle": "_expo/static/js/android/index-abc.hbc", "assets": [{"path": "assets/logo", "ext": "png"}]}}}))
        (ota / "ota.json").write_text(json.dumps({"runtimeVersion": runtime}))

    def _get(self, caminho, cab=None):
        return chamar(self.app, "GET", caminho, None, cab or {})


class AtualizadorTests(_Base):
    def test_portal_web_do_aluno_e_servico_com_segura(self):
        (self.raiz / "web/index.html").write_text("<main>Frequency aluno</main>")
        (self.raiz / "web/_expo").mkdir()
        (self.raiz / "web/_expo/app.js").write_text("console.log('ok')")
        self.assertEqual(self._get("/app-aluno/")[0], 307)
        s, h, c = self._get("/app-aluno/web/")
        self.assertEqual((s, h["content-type"]), (200, "text/html; charset=utf-8"))
        self.assertIn(b"Frequency aluno", c if isinstance(c, bytes) else c.encode())
        self.assertEqual(self._get("/app-aluno/web/_expo/app.js")[0], 200)
        self.assertEqual(self._get("/app-aluno/web/../index.html")[0], 404)

    def test_versao_json_publicada(self):
        dados = {"versao": "0.4.0", "versao_minima": "0.3.0", "url": "https://x/app-aluno/frequency-0.4.0.apk", "sha256": "a" * 64}
        (self.raiz / "app/versao.json").write_text(json.dumps(dados))
        s, h, c = self._get("/app-aluno/versao.json")
        self.assertEqual((s, c["versao"]), (200, "0.4.0"))
        self.assertEqual(h["cache-control"], "no-cache")

    def test_sem_versao_publicada_404_e_json_quebrado_404(self):
        self.assertEqual(self._get("/app-aluno/versao.json")[0], 404)
        (self.raiz / "app/versao.json").write_text("{nao é json")
        self.assertEqual(self._get("/app-aluno/versao.json")[0], 404)
        (self.raiz / "app/versao.json").write_text('{"versao": "1.0.0"}')
        self.assertEqual(self._get("/app-aluno/versao.json")[0], 404)

    def test_so_serve_apk_com_nome_estrito(self):
        (self.raiz / "app/frequency-0.4.0.apk").write_bytes(b"PKfake")
        (self.raiz / "app/segredo.txt").write_text("x")
        s, h, _ = chamar(self.app, "GET", "/app-aluno/frequency-0.4.0.apk")
        self.assertEqual(s, 200)
        self.assertEqual(h["content-type"], "application/vnd.android.package-archive")
        for ruim in ("segredo.txt", "frequency-0.4.apk", "..%2Fsegredo.txt", "frequency-0.4.0.apk.txt", "frequency-9.9.9.apk"):
            self.assertEqual(self._get("/app-aluno/" + ruim)[0], 404, ruim)


class OtaTests(_Base):
    CAB = {"expo-platform": "android", "expo-runtime-version": "0.4.0"}

    def test_manifesto_valido_no_protocolo_v1(self):
        self._exportar()
        s, h, c = chamar(self.app, "GET", "/ota/manifest", None, self.CAB)
        self.assertEqual(s, 200)
        self.assertEqual(h["expo-protocol-version"], "1")
        self.assertTrue(h["content-type"].startswith("multipart/mixed; boundary="))
        texto = c if isinstance(c, str) else c.decode()
        corpo = json.loads(texto.split("\r\n\r\n", 1)[1].rsplit("\r\n--", 1)[0])
        self.assertIn('name="manifest"', texto)
        self.assertEqual(corpo["runtimeVersion"], "0.4.0")
        self.assertEqual(corpo["launchAsset"]["contentType"], "application/javascript")
        self.assertTrue(corpo["launchAsset"]["url"].startswith("https://exemplo.test/ota/assets/"))
        self.assertEqual(corpo["assets"][0]["contentType"], "image/png")
        # o hash é SHA-256 base64url sem padding do arquivo
        import base64
        esperado = base64.urlsafe_b64encode(hashlib.sha256(b"console.log(1)").digest()).decode().rstrip("=")
        self.assertEqual(corpo["launchAsset"]["hash"], esperado)
        self.assertEqual(corpo["launchAsset"]["key"], hashlib.md5(b"console.log(1)").hexdigest())

    def test_runtime_diferente_ou_sem_pacote_nao_tem_atualizacao(self):
        for cab in (self.CAB, {**self.CAB, "expo-runtime-version": "0.3.0"}):
            if cab is self.CAB:
                pass
            s, _, c = chamar(self.app, "GET", "/ota/manifest", None, cab)
            self.assertEqual(s, 200)
            self.assertIn("noUpdateAvailable", c if isinstance(c, str) else c.decode())
        self._exportar(runtime="0.5.0")
        s, _, c = chamar(self.app, "GET", "/ota/manifest", None, self.CAB)
        self.assertIn("noUpdateAvailable", c if isinstance(c, str) else c.decode())

    def test_mesmo_update_id_nao_reenvia(self):
        self._exportar()
        s, _, c = chamar(self.app, "GET", "/ota/manifest", None, self.CAB)
        texto = c if isinstance(c, str) else c.decode()
        uid = json.loads(texto.split("\r\n\r\n", 1)[1].rsplit("\r\n--", 1)[0])["id"]
        s, _, c2 = chamar(self.app, "GET", "/ota/manifest", None, {**self.CAB, "expo-current-update-id": uid})
        self.assertIn("noUpdateAvailable", c2 if isinstance(c2, str) else c2.decode())

    def test_plataforma_obrigatoria_e_validada(self):
        self.assertEqual(chamar(self.app, "GET", "/ota/manifest", None, {"expo-runtime-version": "0.4.0"})[0], 400)
        self.assertEqual(chamar(self.app, "GET", "/ota/manifest", None, {**self.CAB, "expo-platform": "windows"})[0], 400)

    def test_asset_so_por_chave_conhecida(self):
        self._exportar()
        chave = hashlib.md5(b"console.log(1)").hexdigest()
        s, h, _ = self._get(f"/ota/assets/{chave}?platform=android")
        self.assertEqual((s, h["content-type"]), (200, "application/javascript"))
        self.assertIn("immutable", h["cache-control"])
        for ruim in ("../metadata.json", "metadata.json", "0" * 32, "%2e%2e%2fota.json", chave + "x"):
            self.assertEqual(self._get(f"/ota/assets/{ruim}")[0], 404, ruim)

    def test_exportado_no_windows_normaliza_separadores(self):
        self._exportar()
        meta = json.loads((self.raiz / "ota/metadata.json").read_text())
        info = meta["fileMetadata"]["android"]
        info["bundle"] = info["bundle"].replace("/", "\\\\")
        info["assets"][0]["path"] = info["assets"][0]["path"].replace("/", "\\\\")
        (self.raiz / "ota/metadata.json").write_text(json.dumps(meta))
        pacote = pub.carregar_pacote(self.raiz / "ota", "android")
        self.assertIsNotNone(pacote)
        self.assertTrue(pacote["assets"])

    def test_metadata_maliciosa_nao_sai_da_pasta(self):
        self._exportar()
        (self.raiz / "fora.txt").write_text("segredo")
        meta = json.loads((self.raiz / "ota/metadata.json").read_text())
        meta["fileMetadata"]["android"]["assets"].append({"path": "../fora.txt", "ext": "txt"})
        (self.raiz / "ota/metadata.json").write_text(json.dumps(meta))
        pacote = pub.carregar_pacote(self.raiz / "ota", "android")
        self.assertNotIn(hashlib.md5(b"segredo").hexdigest(), pacote["arquivos"])


if __name__ == "__main__":
    unittest.main()
