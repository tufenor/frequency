import re
import unittest

from backend.tests import _path  # noqa: F401
import aluno_auth


class NucleoAlunoAuthTests(unittest.TestCase):
    def test_normalizar_email_remove_espacos_e_caixa(self):
        self.assertEqual(aluno_auth.normalizar_email("  Aluno@Gmail.COM "), "aluno@gmail.com")

    def test_gerar_codigo_tem_6_digitos(self):
        for _ in range(1000):
            self.assertRegex(aluno_auth.gerar_codigo(), r"^\d{6}$")

    def test_hash_codigo_depende_do_aluno(self):
        self.assertNotEqual(aluno_auth.hash_codigo("123456", 1), aluno_auth.hash_codigo("123456", 2))
        self.assertRegex(aluno_auth.hash_codigo("123456", 1), r"^[0-9a-f]{64}$")

    def test_codigo_valido_aceita_e_recusa(self):
        h = aluno_auth.hash_codigo("123456", 7)
        self.assertTrue(aluno_auth.codigo_valido("123456", 7, h))
        self.assertFalse(aluno_auth.codigo_valido("654321", 7, h))
        self.assertFalse(aluno_auth.codigo_valido("123456", 8, h))

    def test_novo_token_hash_confere(self):
        token, h = aluno_auth.novo_token_sessao()
        self.assertGreaterEqual(len(token), 40)
        self.assertEqual(aluno_auth.hash_token(token), h)
        self.assertNotEqual(token, aluno_auth.novo_token_sessao()[0])


if __name__ == "__main__":
    unittest.main()
