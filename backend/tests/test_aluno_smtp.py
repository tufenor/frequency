import logging
import os
import smtplib
import unittest
from unittest import mock

from backend.tests import _path  # noqa: F401
import aluno_auth

ENV = {
    "FREQUENCY_SMTP_HOST": "smtp.exemplo.test",
    "FREQUENCY_SMTP_USER": "conta@exemplo.test",
    "FREQUENCY_SMTP_PASSWORD": "segredo-de-teste",
    "FREQUENCY_SMTP_FROM": "conta@exemplo.test",
}


class _Servidor:
    chamadas = []

    def __init__(self, host, porta, timeout=None):
        _Servidor.chamadas.append(("conectar", host, porta))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        _Servidor.chamadas.append(("starttls",))

    def login(self, u, s):
        _Servidor.chamadas.append(("login",))

    def send_message(self, m):
        _Servidor.chamadas.append(("enviar", m["To"]))


class SmtpTests(unittest.TestCase):
    def setUp(self):
        _Servidor.chamadas = []

    def _rodar(self, extra, ssl=_Servidor, plain=_Servidor):
        with mock.patch.dict(os.environ, {**ENV, **extra}, clear=False), \
                mock.patch.object(smtplib, "SMTP_SSL", ssl), mock.patch.object(smtplib, "SMTP", plain):
            return aluno_auth.enviar_email_texto("aluno@exemplo.test", "a", "b")

    def test_porta_465_usa_ssl_direto(self):
        self.assertTrue(self._rodar({"FREQUENCY_SMTP_PORT": "465"}))
        self.assertNotIn(("starttls",), _Servidor.chamadas)
        self.assertIn(("enviar", "aluno@exemplo.test"), _Servidor.chamadas)

    def test_porta_587_usa_starttls_antes_do_login(self):
        self.assertTrue(self._rodar({"FREQUENCY_SMTP_PORT": "587"}))
        nomes = [c[0] for c in _Servidor.chamadas]
        self.assertEqual(nomes, ["conectar", "starttls", "login", "enviar"])

    def test_variavel_security_forca_starttls(self):
        self.assertTrue(self._rodar({"FREQUENCY_SMTP_PORT": "2525", "FREQUENCY_SMTP_SECURITY": "starttls"}))
        self.assertIn(("starttls",), _Servidor.chamadas)

    def test_falha_de_conexao_loga_so_o_tipo_e_retorna_false(self):
        class Quebrado(_Servidor):
            def __init__(self, *a, **k):
                raise ConnectionRefusedError("segredo-de-teste aluno@exemplo.test")

        with self.assertLogs("frequency.aluno_auth", level=logging.WARNING) as capturado:
            self.assertFalse(self._rodar({"FREQUENCY_SMTP_PORT": "465"}, ssl=Quebrado))
        texto = "\n".join(capturado.output)
        self.assertIn("ConnectionRefusedError", texto)
        self.assertNotIn("segredo-de-teste", texto)
        self.assertNotIn("aluno@exemplo.test", texto)

    def test_sem_configuracao_retorna_false(self):
        with mock.patch.dict(os.environ, {"FREQUENCY_SMTP_HOST": ""}, clear=False):
            self.assertFalse(aluno_auth.enviar_email_texto("a@b.c", "a", "b"))


if __name__ == "__main__":
    unittest.main()
