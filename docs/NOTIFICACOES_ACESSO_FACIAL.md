# Notificações de acesso facial

Atualizado em 01/10/2026.

## Objetivo

Informar a equipe da academia no painel `/app` quando o reconhecimento facial
registrar uma tentativa de entrada. A tela `/monitor` continua sendo a tela
visual da entrada; a notificação do painel é um complemento para dono e
recepção.

## Fluxo

1. O leitor autorizado envia uma imagem para `POST /acesso/facial`.
2. A API valida a academia do leitor, o modelo facial, a assinatura e as
   regras de acesso.
3. A API grava uma linha em `presencas` com `metodo_identificacao = 'facial'`.
   Uma tentativa sem correspondência também pode ser gravada como bloqueada,
   sem `aluno_id`.
4. O painel consulta `GET /presencas` em lotes incrementais usando `depois`.
5. O painel mostra até oito eventos faciais recentes na lateral.
6. Quando existe `aluno_id`, o cartão é acionável e abre **Alunos** com o
   formulário desse aluno. Sem aluno identificado, o cartão permanece apenas
   informativo.

## Contrato incremental

`GET /presencas?limite=100&depois=<id>` exige um token de dono ou recepção e
mantém o filtro pela `academia_id` da sessão. A resposta inclui:

```json
{
  "id": 123,
  "aluno_id": 45,
  "data_hora": "2026-10-01T12:30:00+00:00",
  "liberado": true,
  "motivo": "acesso_liberado",
  "metodo_identificacao": "facial",
  "confianca": 0.91,
  "nome_aluno": "Nome do aluno"
}
```

O painel estabelece uma linha de base ao abrir a sessão para não transformar o
histórico antigo em notificações novas. Depois, busca somente IDs maiores que
o último recebido, aproximadamente a cada 2,5 segundos. O logout cancela o
timer e limpa os cartões.

## Apresentação responsiva

Com pelo menos um evento novo, a lista aparece como uma barra fixa que sobe no
canto direito do desktop. Em telas estreitas ela sobe no canto inferior, sem
ocupar o fluxo do menu e sem esconder os controles principais.
O painel usa `aria-live="polite"`, mantém no máximo oito cartões e respeita a
preferência de movimento reduzido do navegador.

## Privacidade e segurança

- Fotos, templates faciais, documentos e telefone não são retornados pelo
  endpoint de notificações.
- O backend mantém autorização por perfil e isolamento por academia.
- O reconhecimento facial não substitui a decisão de acesso da API.
- Falhas de imagem ou do motor facial não viram notificações falsas; continuam
  sendo erros da solicitação.
- O cartão não permite abrir perfil quando não existe aluno identificado.

## Operação e limitações

O recurso exige que o painel esteja aberto e conectado à API. A consulta
incremental não é uma fila offline e não substitui o histórico de acessos.
Com a instalação local, desligar o PC interrompe API, banco e notificações. Em
um VPS com serviço persistente, o recurso continua funcionando sem o PC local,
desde que o serviço, banco, HTTPS e backup tenham sido homologados.

## Validação

Os testes direcionados ficam em:

- `backend/tests/test_facial_notifications.py`;
- `frontend/tests/facial-notifications.test.mjs`.

Antes de uma entrega, executar `node --check frontend/public/static/app.js`,
`python -m compileall backend/main.py` e `git diff --check`. A homologação
final ainda precisa usar câmera, leitor e rede reais.
