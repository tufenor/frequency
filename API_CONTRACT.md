# Contrato observado da API — Frequency

Os arquivos `API_CONTRACT.md`, `PROJECT_STATUS.md` e `ARCHITECTURE.md` não existiam na raiz quando o trabalho de frontend foi separado em 28/09/2026. Este documento registra exclusivamente rotas já presentes em `backend/main.py` e modelos de entrada existentes. Não autoriza nem implementa novas APIs. O responsável pelo backend deve revisar este registro, principalmente a cobrança SaaS ainda em desenvolvimento.

## Convenções

- Origem relativa à página. Autenticação: `Authorization: Bearer <token>`; token em sessionStorage.
- JSON, salvo login (`application/x-www-form-urlencoded`) e envio de QR (bytes da imagem com Content-Type).
- Erros `{detail: string | array}`: 401 encerra sessão; 402 indica assinatura bloqueada; 403 permissão; 409 conflito; 422 validação; 503 recurso indisponível/migração pendente.
- Moeda ISO de cada registro. Dinheiro pode chegar como string decimal. Não somar moedas diferentes.
- Datas civis `YYYY-MM-DD`; não aplicar conversão de fuso em vencimentos.
- `/config` retorna `somente_consulta: boolean`. Nesta modalidade o frontend oculta escritas.
- GET `/operacao/status` exige administrador da plataforma ou dono da academia e retorna somente o estado operacional seguro: banco conectado, frontend disponível, flags de sincronização e último estado do backup local. Não retorna caminhos, credenciais, tokens ou conteúdo de backup; recepção recebe 403.

## Autenticação e academia

| Método e rota | Contrato consumido |
|---|---|
| POST `/login` | form `username,password`; retorna `access_token,token_type,nome,papel` |
| GET `/eu` | `id,nome,papel,academia_id,pais,idioma,moeda`; academia também pode receber `dias_atraso_frequency,aviso_frequency,bloqueada_frequency,status_assinatura_frequency,motivo_bloqueio_frequency,recursos_frequency` |
| GET/PATCH `/academia/preferencias` | dono; localização `{pais,cidade,estado,endereco,codigo_postal,moeda}`. PATCH aceita Brasil/Bolivia e atualiza idioma/moeda sugeridos, preservando moedas de registros existentes; exige migration010 |
| GET `/alunos` | array `id,nome,documento,status,plano_id,plano`; **não contém data de matrícula** |
| GET `/alunos/situacao` | situação/alerta/dias restantes por aluno |
| POST `/alunos` | nome,documento,telefone?,data_nascimento?,plano_id?,id_biometria?,foto_base64?,foto_media_type? |
| GET/PATCH `/alunos/{id}` | consulta/edição de documento,telefone,data_nascimento |
| PATCH `/alunos/{id}/plano` | `{plano_id}`; vincula o primeiro plano e cria a cobrança inicial em uma transação |
| PATCH `/alunos/{id}/status` | status do aluno conforme implementação existente |
| GET `/planos` | array `id,nome,valor,moeda,duracao_dias` |
| POST `/planos` | nome,valor,duracao_dias; moeda definida pela academia |
| GET `/pagamentos?filtro=todos` | array completo `id,aluno_id,aluno_nome,aluno_plano_id,valor,moeda,vencimento,data_pagamento,status,atrasado`; filtros `todos,abertos,atrasados,pagos` e aluno_id opcional |
| POST `/pagamentos/{id}/pagar` | confirma pagamento; recusa `409 aluno_sem_plano` até que o aluno tenha um plano |
| GET `/presencas?limite=100` | histórico `id,data_hora,liberado,motivo,nome_aluno` |

## Reservas de aulas e áreas (MVP)

Todas as rotas abaixo exigem Bearer de `dono` ou `recepcao` e filtram os registros pela academia do usuário. A migração `041_reservas_aulas_areas.sql` é obrigatória; quando ainda não foi aplicada, a resposta é 503 `migracao_reservas_pendente`. O MVP não oferece fila de espera, recorrência, pagamento da reserva ou conta de aluno: a recepção/dono reserva em nome do aluno cadastrado.

| Método e rota | Body/parâmetros | Resposta e erros |
|---|---|---|
| POST `/recursos-agendaveis` | **dono**; `{nome,tipo:"aula"|"area",descricao?,capacidade}` | 201 recurso; 409 `recurso_agendavel_ja_cadastrado`; 422 validação |
| GET `/recursos-agendaveis` | nenhum | 200 array dos recursos da academia, incluindo `ativo` |
| PATCH `/recursos-agendaveis/{id}` | **dono**; subconjunto de `nome,tipo,descricao,capacidade,ativo`; campos enviados não podem ser `null` | 200 atualizado; 404 fora da academia; 409 nome duplicado ou `capacidade_inferior_reservas_ativas`; 422 `campos_nulos_nao_permitidos`, body vazio ou valor inválido |
| DELETE `/recursos-agendaveis/{id}` | **dono** | 200 `{id,ativo:false}`; desativação preserva histórico; 404 inexistente |
| POST `/sessoes-agendadas` | **dono**; `{recurso_id,inicio,fim}` em ISO 8601 com fuso | 201 sessão; 404 recurso inexistente/inativo; 409 `sessao_no_passado` ou `recurso_agendavel_ocupado`; 422 período/fuso inválido |
| GET `/sessoes-agendadas?inicio_de=&inicio_ate=` | filtros opcionais em ISO 8601 com fuso | 200 sessões com `reservas_ativas` e `vagas_disponiveis`; 422 filtro inválido |
| DELETE `/sessoes-agendadas/{id}` | **dono** | 200 sessão cancelada e suas reservas ativas canceladas; 404 inexistente/já cancelada |
| POST `/sessoes-agendadas/{id}/reservas` | `{aluno_id}` | 201 reserva; 404 sessão/aluno de outra academia; 409 `sessao_indisponivel`, `aluno_inativo`, `reserva_duplicada` ou `sessao_lotada` |
| GET `/reservas-agendadas?sessao_id=&aluno_id=` | filtros opcionais | 200 reservas com aluno, sessão, recurso e status, sempre dentro da academia |
| DELETE `/reservas-agendadas/{id}` | cancela em nome do aluno | 200 reserva cancelada; 404 inexistente, de outra academia ou já cancelada |

O conflito de horário é definido por `inicio_existente < fim_novo` e
`fim_existente > inicio_novo` para o mesmo recurso e sessões `agendada`.
Intervalos que apenas encostam são permitidos. A criação bloqueia a linha do
recurso na transação para que duas criações concorrentes não ocupem o mesmo
horário. Todas as rotas de reserva verificam as colunas, constraints e índice
único da migration; schema parcial retorna 503
`migracao_reservas_pendente`.
| GET/PUT/DELETE `/academia/qr` | QR privado da academia, bytes PNG/JPEG/WebP <=2 MB; dono escreve |
| GET/POST `/usuarios/recepcao` | lista/cadastra equipe; dono; PATCH `/{id}/status` altera ativo |
| GET `/admin/academias` | academias id,nome,pais,ativa |
| POST `/admin/academias` | nome_academia,pais,nome_dono,email_dono,senha_dono; logo_monitor_base64/media_type opcionais; plano_frequency_id/vencimento_frequency opcionais |
| PATCH `/admin/academias/{id}/status` | `{ativa:boolean}` |

Financeiro da academia pode ser agregado no frontend a partir da lista completa de pagamentos, usando **data_pagamento para receita**, status e flag atrasado para pendências. Não existe `/financeiro/resumo` no código atual nem contrato para despesas/lucro. Idioma individual persistido e mercados além de Brasil/Bolívia continuam pendentes.

## Cobrança Frequency — administrador da plataforma

Exige migração 008, cuja aplicação na instalação atual não foi verificada. Rotas já existentes:

| Método e rota | Dados |
|---|---|
| GET `/admin/frequency/resumo` | academias,academias_ativas,assinaturas_ativas,assinaturas_suspensas,faturas_em_atraso,academias_bloqueadas; receita_mensal[{mes,moeda,faturas,recebido}], vendas_mensais[{mes,assinaturas}], faturas_abertas_por_moeda[{moeda,faturas,total,faturas_atrasadas,total_atrasado}] |
| GET `/admin/frequency/academias` | academia_id,academia,pais,academia_ativa,nome_dono,email_dono,assinatura_id,assinatura_status,inicio_assinatura,proximo_vencimento,plano_id,plano; fatura_id,referencia,valor,moeda,vencimento,fatura_status,data_pagamento,dias_atraso,aviso,bloqueada |
| GET/POST `/admin/frequency/planos` | lista/cria `{nome(2..100),descricao(<=1000),valor>0,moeda(3 letras),duracao_dias(1..3660),nivel(essencial|profissional|premium),cameras,spotify}`; câmera/Spotify só podem ser habilitados no Premium |
| PATCH `/admin/frequency/planos/{id}/status` | `{ativo:boolean}` |
| POST `/admin/frequency/assinaturas` | `{academia_id,plano_id,vencimento}`; cria assinatura e primeira fatura |
| PATCH `/admin/frequency/assinaturas/{id}/status` | `{status:ativa|suspensa|cancelada}` |
| GET `/admin/frequency/faturas?status=todas` | até 500 faturas; filtros todas,em_aberto,pago,cancelado,estornado; id,academia_id,academia,referencia,periodo_inicio,periodo_fim,valor,moeda,vencimento,status,data_pagamento,meio_pagamento,referencia_pagamento,observacao_admin |
| PATCH `/admin/frequency/faturas/{id}/pagar` | `{meio_pagamento(2..80),referencia_pagamento?(<=160),observacao_admin(<=1000)}`; confirma e gera próximo período quando assinatura ativa |
| POST `/assinatura-frequency/checkout` | **dono**; `{documento}`; cria ou reutiliza checkout dLocal para a fatura aberta e devolve `checkout_url`; a assinatura só é liberada após webhook assinado |
| POST `/webhooks/dlocal` | endpoint público HTTPS; valida `Authorization` HMAC e `X-Date` (aceita `Signature` legado), confere pedido, valor e moeda; eventos repetidos são idempotentes |
| PATCH `/admin/frequency/faturas/{id}/cancelar` | `{observacao_admin(3..1000)}`; apenas fatura aberta |
| GET `/admin/frequency/auditoria?limite=100` | id,criado_em,administrador,acao,entidade,entidade_id,detalhes |
| GET/PUT/DELETE `/admin/frequency/qr/{moeda}` | imagem privada por moeda, PNG/JPEG/WebP <=2 MB |
| GET/PUT `/admin/frequency/configuracao` | `{contato_email?,contato_telefone?}` |

## Prospecção comercial — administrador da plataforma

Exige as migrations 029 e 030. É uma área global, exclusiva de `admin_plataforma`: os leads não criam academia, usuário, assinatura ou dados visíveis aos clientes finais.

| Método e rota | Dados |
|---|---|
| GET `/admin/prospeccao/leads?prioridade=&status=&cidade=` | `{leads,funil}`; filtra A/B/C, status e cidade; exclui registros arquivados. Cada lead inclui textos personalizados de e-mail e WhatsApp. |
| POST `/admin/prospeccao/leads` | cria lead com nome, cidade/endereço, telefone, e-mail, site/Instagram, avaliação, observações, prioridade, status e último contato. |
| PATCH `/admin/prospeccao/leads/{id}` | altera os dados e status de um lead ativo. |
| DELETE `/admin/prospeccao/leads/{id}` | exclusão lógica e auditável; o lead deixa de aparecer no painel. |
| POST `/admin/prospeccao/importar` | importa até 500 leads de CSV já revisado; ignora duplicatas ativas por nome+cidade. Não coleta dados externamente. |
| GET/PATCH `/admin/prospeccao/configuracao` | templates persistentes de WhatsApp, assunto e corpo de e-mail. Aceita `{academia}` e `{cidade}`. |
| GET/PUT `/admin/prospeccao/imagem` | imagem comercial privada JPG/PNG/WebP até 5 MB, normalizada como JPEG e usada para anexação manual. |

Os botões do frontend só preenchem um e-mail ou conversa do WhatsApp por lead; o usuário confirma cada envio no aplicativo correspondente. Não há envio automático em massa.

## Assinatura da academia

- GET `/assinatura-frequency`: **dono**; estado de atraso/bloqueio; assinatura{id,status,inicio,proximo_vencimento,plano} ou null; últimas 12 faturas; contato{contato_email,contato_telefone}; fatura_atual{id,valor,moeda,vencimento,status} ou null.
- GET `/assinatura-frequency/qr`: **dono**; QR da moeda da fatura atual; 404 quando ausente.
- Recepção usa somente flags de `/eu`, sem valores/QR de assinatura.
- Aviso a partir de 2 dias; bloqueio a partir de 5 dias ou suspensão manual. A interface reflete flags do servidor. Catraca depende da aplicação desta política no backend.
- O checkout online exige a migração `015_pagamentos_online.sql`, credenciais dLocal somente no servidor (`DLOCAL_X_LOGIN`, `DLOCAL_X_TRANS_KEY`, `DLOCAL_SECRET_KEY`) e `PAYMENT_PUBLIC_BASE_URL` em HTTPS. O QR estático continua fallback e nunca baixa uma fatura sozinho.

## Monitor e personalização

- GET `/academia/tela-acesso`: dono; chave_ativa,logo_cadastrada.
- POST `/academia/tela-acesso/chave`: dono; retorna chave apenas agora.
- GET/PUT/DELETE `/academia/tela-acesso/logo`: dono; PUT JSON foto_base64,foto_media_type; entrada <=5 MB JPEG/PNG/WebP.
- `/monitor/estado`, `/monitor/logo`, `/monitor/eventos?depois=id`, `/monitor/eventos/{id}/foto`: header `X-Monitor-Key`, sem token de usuário. Estado academia,ultimo_evento,logo_cadastrada. Eventos recentes id,nome,liberado,motivo,data_hora,foto_disponivel.

## Integrações Premium

- GET `/academia/integracoes/{recurso}`: dono; `recurso` é `cameras` ou `spotify`. Retorna `{permitido:true,recurso}` quando a assinatura ativa possui o direito Premium. Retorna 403 `recurso_exclusivo_plano_premium` sem direito, 403 `modo_somente_consulta` no espelho e 404 para recurso desconhecido.
- Câmeras e Spotify não são serviços hospedados pelo Frequency. Câmeras ficam configuradas apenas no navegador, sem gravação ou transmissão ao servidor. Spotify depende de OAuth PKCE, conta e dispositivo compatíveis; nenhum Client Secret é enviado ao produto.

## Alterações de contrato

Qualquer rota nova deve ser aprovada/implementada pelo backend antes de ser consumida. Solicitações pendentes em PROJECT_STATUS.md, seção BACKEND REQUEST.

### Regras SaaS confirmadas em 29/09/2026

- `PATCH /admin/frequency/assinaturas/{id}` ao alterar `proximo_vencimento` também atualiza, na mesma transação, a fatura aberta corrente da assinatura. Faturas pagas/canceladas não são reescritas; sem fatura aberta a alteração retorna `409`.
- `PATCH /admin/frequency/planos/{id}` rejeita `nome: null` ou nome somente com espaços com `422`.
- `PATCH /admin/frequency/faturas/{id}/cancelar` retorna `409` com `fatura_necessaria_para_assinatura_ativa` quando a fatura é a última aberta de uma assinatura ativa. A fatura permanece inalterada.

## Aluno — autenticação (app do aluno)

Todas as rotas `/aluno/*` exigem a academia com a flag `app_aluno_login` ligada e assinatura em dia. Erros são códigos em `detail`. Nenhuma resposta revela se um e-mail existe.

| Rota | Corpo | Sucesso | Erros |
|---|---|---|---|
| `POST /aluno/auth/iniciar` | `{email}` | `200 {enviado: true}` (sempre) | `429 {retry_after}` |
| `POST /aluno/auth/codigo` | `{email, codigo}` | `200 {ticket}` (vale 10 min, uso único) | `400 codigo_invalido` |
| `POST /aluno/auth/definir-senha` | `{ticket, senha, aparelho?}` | `200 {token, expira_em, aluno}` | `400 ticket_invalido`, `422 senha_curta` (mín. 8) |
| `POST /aluno/auth/entrar` | `{email, senha, aparelho?}` | `200 {token, expira_em, aluno}` | `401 credenciais_invalidas`, `429` |
| `POST /aluno/auth/google` | `{id_token}` | `200 {token, expira_em, aluno}` | `401 credenciais_invalidas`, `503 google_nao_configurado` |
| `POST /aluno/auth/sair` | (Bearer) | `204` | `401` |
| `GET /aluno/eu` | (Bearer) | `{id, nome, email, academia{id,nome,pais,moeda}, plano{id,nome,modalidades}|null, status}` | `401` |

- Código: 6 dígitos, validade 10 min, 5 tentativas, guardado como HMAC. Reenvio: 1 por 60 s e 5 por hora.
- Sessão: token opaco, validade 30 dias, revogável, guardado como SHA-256.
- Painel: `POST /alunos/{id}/convite`, `POST /alunos/{id}/redefinir-acesso`; `acesso_app` ∈ `sem_email|convidado|ativo` na ficha do aluno.

## Alunos — ficha complementar (painel)

Dados opcionais coletados pela recepção/dono. Tabela `aluno_ficha` (migração 047). Dados de saúde são sensíveis: só o painel autenticado da própria academia lê e grava; nunca vão para log.

- `GET /alunos/{id}/ficha` → `{contato_emergencia_nome, contato_emergencia_telefone, endereco_rua, endereco_numero, endereco_cidade, objetivo, restricoes_saude, atestado_medico, sexo, peso_kg, altura_cm}` (campos vazios = `null`; `atestado_medico` = `false`). `404 aluno_nao_encontrado` para aluno de outra academia.
- `PUT /alunos/{id}/ficha` → grava/atualiza (upsert, textos aparados, vazio vira `null`). `sexo` ∈ `feminino|masculino|outro|nao_informar`; `peso_kg` 20–400 (1 casa); `altura_cm` 80–250; fora disso `422`. `403 modo_somente_consulta` no espelho de leitura.
- O e-mail do aluno continua em `POST /alunos` (`email`) e `PUT /alunos/{id}/email`. É obrigatório apenas no formulário de novo aluno do painel (o backend segue aceitando vazio, para importações e quiosque).

## Aluno — treinos, catálogo e modelos (migração 048)

Todas exigem Bearer do aluno (mesmas regras de `/aluno/*`). Erros em `detail`. Tudo isolado por aluno e academia.

| Rota | Função | Erros |
|---|---|---|
| `GET /aluno/catalogo` | `{grupos, grupos_livres, exercicios[]}`; cada exercício: `ref` (`c:<id>` catálogo ou `x:<id>` próprio/da academia), `origem` (`catalogo|academia|aluno`), `nome, grupo, equipamento, nivel, series, reps, tempo, descanso_s, foto_chave`. Efetivo = global − ocultos pela academia + da academia + do aluno | `401` |
| `POST /aluno/exercicios` | `{nome, grupo, equipamento?, tempo?}` → exercício próprio (máx. 100) | `422 grupo_invalido|limite_de_exercicios` |
| `DELETE /aluno/exercicios/{id}` | desativa o próprio | `404` |
| `GET /aluno/modelos` | 20+ modelos `{id, nome, descricao, nivel, dias}` | |
| `POST /aluno/modelos/{id}/copiar` | cria uma cópia editável (um treino por dia do modelo); o modelo não muda | `404`, `422 limite_de_treinos` |
| `GET /aluno/treinos` | `{treinos[]}` em árvore: treino → `blocos[]` → `itens[]` | |
| `POST /aluno/treinos` | `{nome, letra?, dias_semana[0-6]?, blocos[]}` (máx. 30 treinos, 12 blocos, 30 itens) | `422` |
| `GET/PUT/DELETE /aluno/treinos/{id}` | PUT exige `versao` atual; blocos/itens com `id` são atualizados, sem `id` criados, ausentes removidos | `404`, `409 versao_desatualizada`, `422 bloco_invalido|item_invalido|exercicio_indisponivel|dias_semana_invalidos` |
| `POST /aluno/treinos/{id}/duplicar` | cópia independente (sem dias) | `404`, `422` |
| `POST /aluno/treinos/blocos/{id}/mover` | `{treino_id}`: só troca o treino do bloco | `404`, `422 limite_de_blocos` |
| `PUT /aluno/treinos/ordem` | `{ids[]}` com todos os treinos | `422 ordem_invalida` |

- Item: `ref` **ou** `nome_livre` (cardio, aquecimento), nunca os dois. `series 1–30`, `reps` texto (ex.: `8-12`, ou segundos se `tempo`), `carga 0–1000` (1 casa), `descanso_s 0–900`.
- Dia da semana: `0=domingo … 6=sábado`; vários treinos podem cair no mesmo dia (variações).
- Exercício ocultado pela academia depois de entrar num treino continua nele com `removido_pela_academia: true`; não pode ser adicionado de novo.

## Painel — exercícios da academia

- `GET /academia/exercicios` (dono e recepção) → `{grupos[{grupo, ativos, total, aviso}], exercicios[]}`; `aviso` quando há menos de 10 ativos no grupo.
- `PUT /academia/exercicios/{id}/visibilidade` `{oculto}` (só dono; `id` do catálogo).
- `POST /academia/exercicios`, `PATCH /academia/exercicios/{id}`, `DELETE /academia/exercicios/{id}` (só dono; exercícios próprios da academia; DELETE desativa).
- Equivalentes com `{academia_id}` explícito em `/academias/{academia_id}/exercicios...` (`403` se não for a academia do usuário). `403 modo_somente_consulta` no espelho de leitura.

## Aluno — evolução (migração 049)

Todas as rotas exigem `Authorization: Bearer <token do aluno>` e são isoladas por aluno.

| Método | Rota | Descrição |
|---|---|---|
| POST | `/aluno/series` | Lote idempotente `{series:[{client_id, registrada_em, treino_uid?, exercicio_ref, exercicio_nome, grupo, serie_numero, carga, reps, concluida}]}`. Máx. 200 (413 `lote_grande_demais`). `client_id` repetido não duplica; resposta `{confirmadas:[client_id…], novas}` — o app só descarta da fila o que vier em `confirmadas`. 422: carga 0–1000, reps 0–500, `data_no_futuro`. |
| GET | `/aluno/series?desde=&limite=` | Séries do próprio aluno, mais recentes primeiro (limite máx. 1000). |
| DELETE | `/aluno/series/{client_id}` | Apaga uma série própria (idempotente: 204 mesmo se já não existir). Usado ao desmarcar uma série já enviada. |
| GET/POST | `/aluno/medidas` | `tipo` ∈ peso, gordura, cintura, quadril, peito, braco, coxa, panturrilha; POST faz upsert por (data, tipo). |
| DELETE | `/aluno/medidas/{id}` | 404 se for de outro aluno. |
| PUT | `/aluno/meta-peso` | `{peso_alvo: 20–500 \| null}`. |
| GET/PUT | `/aluno/consentimento` | `compartilhar_com_academia`, desligado por padrão. |
| GET | `/aluno/evolucao` | `semana`, `pulso` (seg–dom), `sequencia_semanas`, `mapa_7_dias`, `recordes` (top 10), `peso`, `peso_alvo`. |

Fotos de progresso ficam só no aparelho.

## Quiosque (migração 050)

Recurso `quiosque` por academia (`academia_recursos`). O tablet usa o cabeçalho `X-Quiosque-Token` (código mostrado uma única vez ao dono; só o hash fica no banco).

| Método | Rota | Descrição |
|---|---|---|
| POST | `/quiosque/identificar` | `{foto_base64}` (≤ 700 KB, nada é gravado). Resposta `{identificado, liberado, motivo, ticket, expira_em, nome}`; sem rosto/ambíguo → `ticket: null`. |
| POST | `/quiosque/qr` | `{codigo}` do QR gerado no app (`POST /aluno/quiosque/qr`, uso único, 90 s). 400 `qr_invalido`. |
| POST | `/quiosque/email/pedir`, `/quiosque/email/confirmar` | Fallback por e-mail + código de 6 dígitos (consome o código de primeiro acesso). Nunca revela se o e-mail existe. |
| GET | `/quiosque/treino-do-dia?dia=0..6` | Cabeçalho `X-Quiosque-Ticket`. Só primeiro nome, treinos do dia e últimas cargas. Ticket: 5 min, ≤ 60 leituras, preso ao quiosque; não vale como token de aluno. |
| POST | `/quiosque/encerrar` | Invalida o ticket. |
| POST | `/aluno/quiosque/qr` | (aluno logado) gera o QR de uso único. |
| GET/POST/DELETE | `/academia/quiosques[/{id}]` | Painel (dono): lista, cadastra (token só na resposta) e revoga (derruba os tickets). Máx. 10 ativos. |

Limite de tentativas (429) reaproveita o limitador do login do aluno.

## Publicação do app e OTA (Plano 6)

Rotas públicas (sem login), servidas a partir das pastas `FREQUENCY_APP_ALUNO_DIR` (versao.json e APK) e `FREQUENCY_OTA_DIR` (saída de `expo export` + `ota.json` com a `runtimeVersion`); URL pública em `FREQUENCY_PUBLIC_URL`. Nome de arquivo é validado (sem `..`, só `frequency-X.Y.Z.apk`).

| Método | Rota | Descrição |
|---|---|---|
| GET | `/app-aluno/versao.json` | `{versao, versao_minima, url, sha256, notas}` gerado por `scripts/publicar-versao.mjs`. 404 se nada publicado. |
| GET | `/app-aluno/frequency-X.Y.Z.apk` | APK publicado. O app confere o SHA-256 antes de abrir o instalador. |
| GET | `/ota/manifest` | Protocolo Expo Updates v1 (multipart/mixed). Cabeçalhos `expo-protocol-version: 1`, `expo-runtime-version`, `expo-platform`. Só entrega se a `runtimeVersion` do pedido bater com a do pacote. |
| GET | `/ota/assets/{chave}` | Asset do pacote (`expo export`). |

OTA entrega só JavaScript; mudança nativa exige novo APK (nova `runtimeVersion`).

## Lutas e aulas coletivas (migração 051)

Flags por academia: `lutas` (modalidades `categoria='luta'`) e `agenda_aulas` (`categoria='aula'`). Sem flag → 403 `lutas_desligado`. A migração amplia `usuarios.papel` com `professor`. Horários são de parede, no `fuso` da academia (`academia_local`, padrão America/Sao_Paulo); `dia_semana` 0 = domingo.

**Painel** (dono = estrutura; recepção = leitura + atestado; professor = só as próprias turmas, outras dão 404)

| Método | Rota | Quem | Descrição |
|---|---|---|---|
| GET/PUT | `/lutas/local` | ler: todos; PUT: dono | latitude, longitude, `raio_m` (20–2000), `fuso`. (0,0) é rejeitado. |
| GET/POST/PATCH | `/lutas/modalidades[/{id}]` | ler: todos; escrever: dono | 409 `modalidade_ja_existe`. |
| GET | `/lutas/planos` · PUT `/lutas/planos/{id}/modalidades` | gestão · dono | Plano com combo de modalidades. |
| GET/POST/DELETE | `/lutas/professores[/{id}]` | gestão · dono | POST com `email`+`senha` (≥ 10) cria login de professor; só o hash é guardado. |
| GET/POST/PATCH | `/lutas/turmas[/{id}]` | todos · dono | `capacidade`, `exige_reserva`, `professor_id`. Subir a capacidade promove a fila. |
| POST/DELETE | `/lutas/turmas/{id}/horarios[/{hid}]` | dono | 409 `horario_ja_existe`, 422 `horario_invalido`. |
| GET | `/lutas/turmas/{id}/alunos` | todos | Reservas (`ativa`/`espera`). |
| GET | `/lutas/chamada?turma_id&data[&horario_id]` | todos | Cria a aula do dia se preciso. Devolve `aula_id`, `codigo_qr` (assinado, só vale para aquela aula), alunos com estado. 404 `sem_aula_neste_dia`, 422 `aula_no_futuro`; com 2+ horários no dia devolve `escolher_horario`. |
| PUT | `/lutas/chamada/{aula}/alunos/{aluno}` | todos | `{acao: validar\|ausentar}`. 409 `fora_do_prazo_de_ajuste` (> 24 h após o fim); 422 `plano_sem_modalidade`. |
| GET/POST/DELETE | `/lutas/faixas` | todos · dono | Ordem única por modalidade; `aulas_minimas`. |
| POST | `/lutas/alunos/{id}/graduacao` | gestão ou professor da turma do aluno | `{faixa_id}`. |
| POST | `/lutas/alunos/{id}/atestado` | gestão | `{valido_ate, observacao}`. Informativo: não bloqueia presença. |
| GET | `/lutas/relatorios/frequencia?turma_id&de&ate` · `/lutas/relatorios/ocupacao` | todos | Só `validada` conta como presença. |

**Aluno** (Bearer; só enxerga modalidades do próprio plano)

| Método | Rota | Descrição |
|---|---|---|
| GET | `/aluno/lutas` | `{disponivel:false}` se não há flag/modalidade no plano; senão `grade` (horários, vagas, espera, `minha_reserva`), `faixas` (atual, próxima, faltam, %), `atestado`, `janela`. |
| POST/DELETE | `/aluno/lutas/turmas/{id}/reservar` | `{entrar_na_espera}`; 409 `turma_cheia`; cancelar promove o primeiro da fila. |
| POST | `/aluno/lutas/presenca` | `{turma_id, horario_id?, metodo: toque\|qr, codigo?, latitude?, longitude?}`. Janela: 30 min antes a 15 min depois (422 `fora_da_janela`). 403 `sem_reserva`, 403 `plano_sem_modalidade`, 422 `codigo_invalido`. Resposta `{estado:'confirmada', dentro_do_raio: true\|false\|null, ja_confirmada}`. A coordenada é lida uma vez e **nunca** gravada; fora do raio só marca a presença para o professor decidir. Tentativas recusadas esgotam o limite (429). |

## Onda 1B (migração 052)

Cada recurso tem a própria flag em `academia_recursos`; desligada → 403 com o código indicado.

**Mensalidade e QR** (`mensalidade_qr` → `mensalidade_desligada`; não precisa de tabela nova: usa `situacao_alunos` e `pagamentos`)

| Método | Rota | Descrição |
|---|---|---|
| GET | `/aluno/mensalidade` | `{plano, proximo_vencimento, valor_em_aberto, moeda, estado: em_dia\|vence_em_breve\|atrasada\|sem_cobranca, dias, liberado, motivo, pagamento_online:false}`. `liberado` segue a mesma regra da catraca. |
| POST | `/aluno/mensalidade/qr` | `{codigo:'fqm_…', expira_em, segundos:120}`. Assinado (HMAC com SECRET_KEY), preso à academia, não é gravado. Cada geração conta no limite (429). |
| POST | `/aluno/mensalidade/pagar` | **Desligada**: sempre 503 `pagamento_online_desligado`. Só será ligada com as credenciais de pagamento do dono. |
| POST | `/academia/acesso/qr` | (dono/recepção) `{codigo}` → `{nome, liberado, motivo, dias_restantes}`. 400 `qr_invalido` para adulterado/vencido/de outra academia (sem dizer qual). Só consulta: não registra presença. Falhas esgotam o limite (429). |

**Desafios** (`desafios` → `desafios_desligado`)

| Método | Rota | Descrição |
|---|---|---|
| GET/POST | `/academia/desafios` | POST só dono: `{nome, metrica: treinos\|volume, inicio, fim}` (≤ 366 dias; máx. 10 ativos). |
| PATCH | `/academia/desafios/{id}` | `{ativo}`; encerrar desliga a TV. |
| GET | `/academia/desafios/{id}/ranking` | Top 100. |
| POST/DELETE | `/academia/desafios/{id}/tv` | Gera/troca (token só na resposta) ou desliga o endereço da TV. |
| GET | `/painel/ranking/{token}` · `/painel/ranking/{token}/dados` | **Sem login**, somente leitura, `Cache-Control: no-store`, CSP restrita. Mostra só `Nome I.` e pontos (top 10), atualiza a cada 30 s. 404 para token errado/desligado/encerrado; erros esgotam o limite (429). |
| GET | `/aluno/desafios` | Lista + `participo`, `minha_posicao`, `meu_valor`. |
| POST/DELETE | `/aluno/desafios/{id}/participar` | 409 `desafio_encerrado`, `desafio_lotado` (500). |
| GET | `/aluno/desafios/{id}/ranking` | Top 20 + `eu`. |

Pontuação: `treinos` = dias com ≥ 3 séries concluídas; `volume` = Σ carga×reps com teto de 10.000 por série e 150 séries/dia. Só conta a partir do início ou da entrada do aluno (o que for depois), no fuso da academia.

**Agenda de aulas** (`agenda_aulas`): usa as rotas de Lutas (051) com modalidades `categoria='aula'`; o app mostra as turmas em "Aulas" (reserva, fila de espera, confirmação de presença).

**Gerador de treino** (`gerador_treino` → `gerador_desligado`)

| Método | Rota | Descrição |
|---|---|---|
| GET/PUT | `/academia/equipamentos` | PUT só dono: `{indisponiveis:[…]}` (422 `equipamento_invalido`, `pelo_menos_um_equipamento`). |
| POST | `/aluno/treinos/gerar` | `{objetivo: hipertrofia\|forca\|emagrecimento\|condicionamento, nivel, dias: 2–6, variacao?, salvar?}`. Sem `salvar` devolve só a proposta (`treinos`, `avisos`); com `salvar` cria pelo mesmo caminho do editor (limite de 30 treinos). Determinístico; `variacao` troca os exercícios. |
