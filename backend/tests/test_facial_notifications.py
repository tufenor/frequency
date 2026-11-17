"""Attendance feed tested against a disposable PostgreSQL cluster."""
from unittest.mock import patch
import unittest
from backend.tests import test_business_postgres as fixture

setUpModule = fixture.setUpModule
tearDownModule = fixture.tearDownModule

class FacialNotificationsTests(unittest.TestCase):
    setUp = fixture.BusinessPostgresIntegrationTests.setUp
    tearDown = fixture.BusinessPostgresIntegrationTests.tearDown
    create_academy = fixture.BusinessPostgresIntegrationTests.create_academy
    owner = fixture.BusinessPostgresIntegrationTests.owner
    def test_incremental_notifications(self):
        main = fixture.main
        academy = self.create_academy('Feed synthetic', 'Brasil')
        other = self.create_academy('Other synthetic', 'Brasil')
        owner = self.owner(academy, 'Brasil')
        with fixture._test_connection() as conn:
            old = conn.execute("INSERT INTO presencas (academia_id, liberado, metodo_identificacao) VALUES (%s, true, 'facial') RETURNING id", (academy,)).fetchone()['id']
            conn.execute("INSERT INTO presencas (academia_id, liberado, metodo_identificacao) VALUES (%s, true, 'facial')", (other,))
        self.assertEqual(main.listar_presencas(limite=1, depois=None, usuario=owner)[0]['id'], old)
        with patch.object(main, 'embedding', return_value=object()), patch.object(main, 'estado_assinatura_frequency', return_value={'bloqueada_frequency': False}):
            result = main.verificar_acesso_facial(main.PedidoAcessoFacial(foto_base64='cHJvYmU='), leitor={'id': None, 'academia_id': academy})
        self.assertFalse(result['identificado'])
        rows = main.listar_presencas(limite=100, depois=old, usuario=owner)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]['aluno_id'])
        self.assertIsNone(rows[0]['nome_aluno'])
        self.assertEqual(rows[0]['metodo_identificacao'], 'facial')
        self.assertFalse(rows[0]['liberado'])
        self.assertEqual(rows[0]['motivo'], 'rosto_nao_identificado')
        self.assertEqual(main.listar_presencas(limite=100, depois=rows[0]['id'], usuario=owner), [])
        for role in ('dono', 'recepcao'):
            self.assertEqual(len(main.listar_presencas(limite=100, depois=old, usuario={**owner, 'papel': role})), 1)
        with self.assertRaises(main.HTTPException) as error:
            main.listar_presencas(limite=100, depois=0, usuario={**owner, 'papel': 'admin_plataforma'})
        self.assertEqual(error.exception.status_code, 403)
