# Contrato backend — cobrança Frequency

## GET /presencas — histórico e cursor incremental (01/10/2026)

Exige Bearer de dono ou recepcao e mantém isolamento pela academia da sessão. `limite`: 1–500, padrão 100. `depois`: inteiro opcional >= 0; inválido retorna 422. Sem cursor, retorna IDs decrescentes (limite=1 estabelece o maior ID); com cursor, somente p.id > depois, em ordem crescente para consumir lotes sem saltar registros.

Resposta: lista de `{id, aluno_id, data_hora, liberado, motivo, metodo_identificacao, confianca, nome_aluno}`. Nome vem de LEFT JOIN com alunos da mesma academia; aluno/nome podem ser nulos. Não expõe fotos, templates ou documentos. O painel filtra metodo_identificacao=facial. O monitor mantém seu contrato existente.

POST /acesso/facial passa a registrar também reconhecimento sem correspondência como presença facial bloqueada sem aluno, reutilizando o processamento existente, inclusive as regras de assinatura. Falhas de imagem/motor mantêm os erros existentes; identificações repetidas mantêm a supressão existente de dez segundos.

Atualizado em 01/10/2026. Este complemento documenta as notificações faciais incrementais e as correções BE-01/02/03. O fluxo operacional completo está em [`docs/NOTIFICACOES_ACESSO_FACIAL.md`](../NOTIFICACOES_ACESSO_FACIAL.md). A referência das demais rotas continua em `API_CONTRACT.md` na raiz; sua consolidação está pendente.

## Convenções

Rotas administrativas abaixo exigem `Authorization: Bearer <token>` de `admin_plataforma`. Erros de negócio: `{"detail":"codigo"}`. Validação: HTTP 422, `detail` é uma lista de erros por campo. Credencial ausente/inválida: 401; perfil sem permissão ou espelho somente consulta para escrita: 403. Migração de cobrança ausente: 503. Datas: ISO `YYYY-MM-DD`. Nenhuma alteração é aplicada se a transação falhar.

## GET /operacao/status

Autenticação: administrador da plataforma ou dono da academia. Resposta 200 contém `banco`, `frontend`, `sincronizacao` e `backup`. O objeto `backup` informa apenas se a rotina está ativada, seu último estado, data e contagens de arquivos; não expõe credenciais, caminhos ou conteúdo. Recepção recebe 403. A ausência de uma execução é reportada como `nunca_executado`; isso não é tratado como sucesso.

## PATCH /admin/frequency/planos/{plano_id}

Parâmetro: ID inteiro. Body parcial: `nome` (texto 2–100 caracteres, após remover espaços externos deve ter pelo menos 2), `descricao` (até 1000), `valor` (positivo, até 12 dígitos e 2 casas), `moeda` (3 letras maiúsculas), `duracao_dias` (1–3660).

Resposta 200: `{id,nome,descricao,valor,moeda,duracao_dias,ativo}`. Valores numéricos monetários podem ser serializados como texto decimal; consumidores não devem usar arredondamento binário para cálculos financeiros.

Erros: nome explicitamente nulo, vazio ou somente espaços → 422; demais campos explicitamente nulos → 400 `campos_nulos_nao_permitidos`; body vazio → 400 `nenhuma_alteracao_informada`; inexistente → 404 `plano_frequency_nao_encontrado`; nome duplicado → 409 `plano_frequency_ja_cadastrado`.

Alterações de preço/moeda/duração valem para futuras emissões, preservando faturas já emitidas.

## PATCH /admin/frequency/assinaturas/{assinatura_id}

Parâmetro: ID inteiro. Body parcial: `plano_id` (inteiro positivo), `proximo_vencimento` (data), `status` (`ativa`, `suspensa`, `cancelada`).

Resposta 200: `{id,academia_id,plano_id,proximo_vencimento,status}`.

Ao alterar o vencimento, atualiza também a fatura em aberto mais antiga, ordenada por vencimento/ID, na mesma transação. Não muda valor, moeda, período ou faturas finalizadas. Auditoria registra ID da fatura, data anterior e nova.

Erros: body vazio/nulos → 400; tipo/data/status inválido → 422; assinatura/plano ativo inexistente → 404; sem fatura aberta ao alterar data → 409 `fatura_frequency_em_aberto_nao_encontrada`. Neste último caso nem os outros campos enviados são alterados.

## PATCH /admin/frequency/faturas/{fatura_id}/cancelar

Body: `{"observacao_admin":"Motivo do cancelamento"}`. Resposta 200: `{"cancelada":true}`.

Última fatura em aberto de assinatura ativa → 409 `fatura_necessaria_para_assinatura_ativa`. Suspenda/cancele explicitamente a assinatura antes de cancelar sua última fatura. Fatura ausente ou já finalizada → 404 `fatura_frequency_em_aberto_nao_encontrada`. Operações concorrentes são serializadas pela assinatura; ao menos uma cobrança aberta permanece quando ativa.

## PATCH /admin/frequency/faturas/{fatura_id}/pagar

Body: `meio_pagamento` (2–80 caracteres), `referencia_pagamento` (opcional, até 160), `observacao_admin` (opcional, até 1000). Resposta 200: `{id,pago:true,proxima_fatura_id}`; próximo ID pode ser nulo.

Fatura inexistente → 404 `fatura_frequency_nao_encontrada`; já finalizada → 409 `fatura_frequency_ja_finalizada`. Pagamento repetido não emite segunda cobrança. Assinatura suspensa/cancelada não é reativada pelo pagamento e não gera recorrência. Assinatura ativa gera período seguinte segundo o plano atual, preservando a fatura paga.

## Leituras relacionadas

- GET `/admin/frequency/faturas?status=...`: `todas` (padrão), `em_aberto`, `atrasadas`, `pago`, `cancelado`, `estornado`; lista limitada a 500. Status inválido: 400. Cada item inclui ID, academia, referência, período, valor/moeda, vencimento, status e confirmação. `atrasadas` acrescenta dias de atraso e sinalizadores de aviso/bloqueio por atraso.
- GET `/eu`: usuário autenticado; flags `dias_atraso_frequency`, `aviso_frequency`, `bloqueada_frequency` refletem fatura aberta. Aviso a partir de 2 dias, bloqueio a partir de 5 ou suspensão/cancelamento manual.
- GET `/alunos`: assinatura bloqueada → 402 `assinatura_frequency_bloqueada`. Reagendar a única dívida para data futura remove bloqueio por atraso; não remove suspensão manual.

O checkout online da assinatura usa `POST /assinatura-frequency/checkout`; o dono fornece o documento exigido pelo provedor e recebe uma URL hospedada. O webhook público `POST /webhooks/dlocal` valida `X-Date` e `Authorization` HMAC (aceita `Signature` legado), confere pedido, valor e moeda e baixa a fatura em uma transação idempotente. QR estático continua sendo fallback e nunca libera a assinatura sozinho. A migração `015_pagamentos_online.sql`, credenciais do servidor e HTTPS público são obrigatórios.

## Reservas de aulas e áreas — migration 041

O MVP usa `recursos_agendaveis`, `sessoes_agendadas` e `reservas_agendadas`.
Todas as consultas têm `academia_id` derivado do token; IDs de outra academia
respondem 404. Dono cria/edita/desativa recursos e cria/cancela sessões.
Dono e recepção listam e reservam/cancelam em nome de alunos ativos. A
capacidade é verificada com bloqueio da sessão e o índice único de reservas
ativas torna a operação concorrente segura. Cancelar uma sessão cancela suas
reservas ativas. Não há fila, recorrência, cobrança ou autoatendimento de
aluno nesta etapa.

Campos opcionais enviados como `null` na edição são recusados com 422
`campos_nulos_nao_permitidos`. Reduzir a capacidade abaixo das reservas ativas
retorna 409 `capacidade_inferior_reservas_ativas`. Sessões sobrepostas no
mesmo recurso retornam 409 `recurso_agendavel_ocupado`; intervalos encostados
são permitidos e a linha do recurso é bloqueada durante a checagem.

Rotas e códigos completos estão na seção **Reservas de aulas e áreas (MVP)**
de `API_CONTRACT.md` na raiz. A ausência da migration retorna 503
`migracao_reservas_pendente` quando tabelas, colunas, constraints ou índice
estão ausentes; horário sem fuso ou período inválido retorna 422; sessão
passada retorna 409 `sessao_no_passado`.

## Recursos Premium

O acesso é verificado pelo servidor a partir da assinatura ativa da academia e do pacote atual. Interface, links e armazenamento do navegador não substituem essa verificação.

### GET /eu

Para o dono de academia, a resposta inclui `recursos_frequency`:

```json
{"nivel":"premium","cameras":true,"spotify":true}
```

Em pacote Essencial ou Profissional, `cameras` e `spotify` são `false`. Sem assinatura ativa, o nível é `null` e ambos são `false`. Assinatura bloqueada não recebe recursos.

### GET /academia/integracoes/{recurso}

Autenticação: dono da academia. `recurso` aceito: `cameras` ou `spotify`.

Resposta 200: `{"permitido":true,"recurso":"cameras"}` ou equivalente para Spotify. Recurso desconhecido: 404 `recurso_nao_encontrado`; pacote sem direito: 403 `recurso_exclusivo_plano_premium`; cópia de consulta: 403 `modo_somente_consulta`.

`/cameras` e `/spotify` apenas entregam as páginas locais. Câmeras são configuradas no navegador e não têm gravação, envio de imagens ou suporte a RTSP/ONVIF pelo servidor. Spotify usa OAuth PKCE diretamente no navegador, não recebe Client Secret e depende de uma conta, aplicativo Spotify e dispositivo compatíveis do cliente. Esses recursos não incluem monitoramento profissional de câmeras, serviço de música comercial ou disponibilidade de terceiros.

Para Spotify, uma assinatura Premium corretamente configurada sem autorização comercial do produto retorna 403 `spotify_comercial_nao_autorizado`; uma academia sem o recurso no pacote retorna 403 `recurso_exclusivo_plano_premium`.

## Localização da academia

### GET /academia/preferencias

Autenticação: dono. Resposta 200: `{pais,cidade,estado,endereco,codigo_postal,moeda}`. Migração 010 ausente: 503 `migracao_localizacao_pendente`.

### PATCH /academia/preferencias

Autenticação: dono. Body obrigatório: `pais` (`Brasil` ou `Bolivia`); opcionais: `cidade` até 120 caracteres, `estado` até 120, `endereco` até 300 e `codigo_postal` até 30. Espaços externos são removidos. Resposta 200 possui os mesmos campos do GET.

O país atualiza idioma/moeda sugeridos da academia. Planos e cobranças existentes preservam a moeda histórica. Admin da plataforma recebe 403 neste endpoint; validação inválida recebe 422.

## Backup local e compatibilidade entre dispositivos

As rotas /operacao/backup-config, PUT /operacao/backup-config, /operacao/backup-selecionar-pasta e POST /operacao/backup podem ser usadas a partir de desktop, tablet ou celular. O app envia X-Frequency-Device-Class: desktop|tablet|mobile apenas para adaptar a interface; essa informação não bloqueia o backup.

A rota GET /operacao/backup/download entrega a cópia criptografada mais recente para download em qualquer dispositivo autorizado. Navegadores que oferecem showDirectoryPicker podem salvar diretamente em uma pasta escolhida; os demais usam o download padrão do sistema (por exemplo, Arquivos/Downloads/Compartilhar no iPhone, iPad e Android). seletor_pasta_disponivel informa somente se o picker nativo do computador que hospeda o backend está disponível.

### Google Drive em dispositivos móveis

Quando o Google Drive para computador estiver montado no host, o backup local pode usar a pasta sincronizada desse Drive. Em celular ou tablet, a interface não inventa um upload de nuvem: ela baixa a cópia criptografada e usa o compartilhamento nativo do dispositivo (navigator.share) para que o usuário escolha Google Drive. Se o navegador não suportar compartilhamento de arquivos, o download continua disponível.
