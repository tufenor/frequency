# Login do aluno (backend) — Plano 1

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O aluno cadastrado pela academia entra no app com e-mail: primeiro acesso por código de 6 dígitos e criação de senha, depois e-mail+senha ou Google; só e-mails cadastrados na academia entram.

**Architecture:** Um módulo novo `backend/aluno_auth.py` (APIRouter, lógica pura separada das rotas) incluído em `main.py` com uma linha, em vez de crescer o `main.py` (6.509 linhas). Sessões opacas e revogáveis guardadas por hash em tabela própria. Migrações aditivas 043–045. Recurso ligado por academia (`academias.recursos`/flag).

**Tech Stack:** FastAPI, psycopg 3 (`dict_row`), pwdlib/Argon2 (`seguranca.gerar_hash`/`verificar_senha`), SMTP existente, unittest com PostgreSQL descartável (padrão de `tests/test_business_postgres.py`), Python 3.12/3.13.

**Spec:** `docs/superpowers/specs/2026-10-11-app-aluno-login-evolucao-treinos-design.md` (seções 2, 3, 11).

## Global Constraints

- Código de primeiro acesso: 6 dígitos, validade 10 minutos, no máximo 5 tentativas por código, guardado só como HMAC-SHA256 com `SECRET_KEY`.
- Sessão: token de 32 bytes `secrets.token_urlsafe`, guardado como SHA-256, validade 30 dias, revogável, uma linha por aparelho.
- Senha: mínimo 8 caracteres; Argon2 via `seguranca.gerar_hash`.
- Respostas de `/aluno/auth/iniciar` e `/aluno/auth/entrar` não revelam se o e-mail existe (mesma resposta e mesmo formato de erro).
- E-mail normalizado: `strip().lower()`; único por academia entre alunos ativos.
- Limite de tentativas reutiliza `rate_limiting.LoginRateLimiter` (por e-mail + IP).
- Migrações: números 043, 044, 045; `BEGIN/COMMIT`; só `CREATE`/`ADD COLUMN IF NOT EXISTS`; nenhuma aplicada em banco real.
- Nada de segredo, código ou token em logs e respostas de erro. Mensagens de erro como códigos (`credenciais_invalidas`, `codigo_invalido`, `acesso_nao_habilitado`).
- Aluno `inativo` não entra. Academia suspensa pela cobrança SaaS não permite login (reutilizar `cobranca_saas.estado_assinatura_frequency`).

## Review Focus

- E-mail com maiúsculas/espaços ("  Aluno@Gmail.COM ") entra como o cadastrado.
- Mesmo e-mail em duas academias: o código vai para a academia correta; sem ambiguidade (exige `academia_id` apenas se houver mais de uma correspondência, senão resposta genérica e e-mail lista as academias).
- Código expirado, reutilizado e tentativa 6: todos negados e o código invalidado.
- Reenvio de código em sequência: limite de 1 por 60 s e 5 por hora.
- Aluno inativo, sem e-mail ou academia suspensa: resposta idêntica a "e-mail não encontrado".
- Token de definir-senha usado duas vezes ou depois de 10 min: negado.

---

### Task 1: Contrato da API e migrações 043–045

**Files:**
- Modify: `API_CONTRACT.md` (nova seção "Aluno — autenticação")
- Create: `backend/migrations/043_aluno_email.sql`, `044_aluno_credenciais_sessoes.sql`, `045_aluno_codigos.sql`
- Test: `backend/tests/test_aluno_migracoes.py`

**Interfaces:**
- Produces: `alunos.email text` (+ índice único parcial `(academia_id, lower(email)) WHERE status='ativo' AND email IS NOT NULL`); `aluno_credenciais(aluno_id PK→alunos, senha_hash, definida_em, google_sub UNIQUE nullable)`; `aluno_sessoes(id bigint identity, aluno_id, token_hash UNIQUE, criado_em, expira_em, revogada_em, aparelho text)`; `aluno_codigos(id bigint identity, aluno_id, codigo_hash, criado_em, expira_em, tentativas int default 0, usado_em, ticket_hash text nullable, ticket_expira_em timestamptz nullable, ticket_usado_em timestamptz nullable)`.

- [ ] **Step 1: Escrever `test_aluno_migracoes.py`** com `test_migracoes_043_a_045_aplicam_em_banco_descartavel` (aplica 001…045 em um banco descartável como `test_aplicar_migracoes.py` e confere as 3 tabelas e a coluna `alunos.email`) e `test_email_unico_por_academia_entre_ativos` (segundo INSERT ativo com mesmo e-mail em maiúsculas levanta `UniqueViolation`; mesmo e-mail em outra academia passa; aluno `inativo` não conflita).
- [ ] **Step 2: Rodar e ver falhar** — `python -m unittest backend.tests.test_aluno_migracoes -v` → FAIL (arquivos 043–045 inexistentes).
- [ ] **Step 3: Escrever as três migrações** conforme as colunas acima, com `CHECK (char_length(codigo_hash) = 64)` e índices por `aluno_id` e `expira_em`.
- [ ] **Step 4: Rodar e ver passar** → PASS; rodar também `test_verificar_migracoes.py` e `test_aplicar_migracoes.py` (a numeração contígua deve aceitar 043 mesmo com 042 pendente: se o verificador exigir contiguidade, incluir 042 como placeholder do patch 031→042 no ambiente de teste e anotar no relatório).
- [ ] **Step 5: Atualizar `API_CONTRACT.md`** com os 6 endpoints (corpos, respostas, códigos de erro) exatamente como nas Tasks 3–6.
- [ ] **Step 6: Commit** — `git commit -m "feat(aluno): migrações 043-045 e contrato de autenticação"`

### Task 2: Núcleo puro de autenticação

**Files:**
- Create: `backend/aluno_auth.py` (parte lógica)
- Test: `backend/tests/test_aluno_auth_core.py`

**Interfaces:**
- Produces (em `aluno_auth.py`):
  - `normalizar_email(email: str) -> str`
  - `gerar_codigo() -> str` (6 dígitos, `secrets.randbelow`, com zeros à esquerda)
  - `hash_codigo(codigo: str, aluno_id: int) -> str` (HMAC-SHA256 hex com `SECRET_KEY`)
  - `hash_token(token: str) -> str` (SHA-256 hex)
  - `novo_token_sessao() -> tuple[str, str]` (token, hash)
  - `codigo_valido(codigo_informado: str, aluno_id: int, hash_guardado: str) -> bool` (`hmac.compare_digest`)

- [ ] **Step 1: Testes**: `test_normalizar_email_remove_espacos_e_caixa` ("  Aluno@Gmail.COM " → "aluno@gmail.com"); `test_gerar_codigo_tem_6_digitos` (1000 execuções casam `^\d{6}$`); `test_hash_codigo_depende_do_aluno` (mesmo código, alunos 1 e 2 → hashes diferentes); `test_codigo_valido_aceita_e_recusa`; `test_novo_token_hash_confere`.
- [ ] **Step 2: Rodar e ver falhar** (`ImportError`).
- [ ] **Step 3: Implementar** as funções acima; `SECRET_KEY` vem de `seguranca.SECRET_KEY`.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** — `feat(aluno): núcleo de autenticação (códigos e tokens)`

### Task 3: Início do primeiro acesso e envio do código

**Files:**
- Modify: `backend/aluno_auth.py` (rota + serviço), `backend/main.py` (incluir o router)
- Test: `backend/tests/test_aluno_auth_iniciar.py`

**Interfaces:**
- Consumes: Task 2; `main._email_verificacao_config`/padrão SMTP (extrair para `enviar_email_texto(destino, assunto, corpo) -> bool` em `aluno_auth.py`, usando as mesmas variáveis `FREQUENCY_SMTP_*`).
- Produces: `POST /aluno/auth/iniciar` corpo `{"email": str}` → sempre `200 {"enviado": true}` (inclusive e-mail desconhecido); `iniciar_acesso(conn, email: str, ip: str | None, enviar=enviar_email_texto) -> None`.

- [ ] **Step 1: Testes** (banco descartável, `enviar` substituído por função que guarda mensagens): `test_email_cadastrado_recebe_codigo_de_6_digitos`; `test_email_desconhecido_responde_igual_sem_enviar`; `test_aluno_inativo_nao_recebe`; `test_reenvio_antes_de_60s_nao_gera_novo_codigo`; `test_sexto_envio_na_hora_e_negado_silenciosamente`; `test_codigo_nao_aparece_no_banco_em_texto` (coluna só tem hash).
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** `iniciar_acesso`: busca aluno ativo com e-mail normalizado numa academia com assinatura em dia e recurso `app_aluno_login` ligado; invalida códigos anteriores; grava hash e `expira_em = now()+10min`; e-mail em PT/ES conforme `academias.pais`. Rota usa `LoginRateLimiter` e retorna sempre o mesmo corpo.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** — `feat(aluno): iniciar primeiro acesso com código por e-mail`

### Task 4: Conferir código e definir senha

**Files:**
- Modify: `backend/aluno_auth.py`
- Test: `backend/tests/test_aluno_auth_senha.py`

**Interfaces:**
- Produces: `POST /aluno/auth/codigo` `{email, codigo}` → `200 {"ticket": str}` (token curto de 10 min, guardado como hash em `aluno_codigos.ticket_hash` com `ticket_expira_em` e `ticket_usado_em`) ou `400 {"detail":"codigo_invalido"}`; `POST /aluno/auth/definir-senha` `{ticket, senha}` → `200 {"token", "expira_em", "aluno": {id, nome, academia_id}}`.
- `verificar_codigo(conn, email, codigo) -> str | None` (ticket); `definir_senha(conn, ticket, senha, aparelho) -> SessaoNova`.

- [ ] **Step 1: Testes**: `test_codigo_correto_gera_ticket`; `test_sexta_tentativa_invalida_o_codigo`; `test_codigo_expirado_e_negado`; `test_codigo_usado_nao_vale_duas_vezes`; `test_definir_senha_cria_credencial_e_sessao`; `test_senha_curta_e_recusada` (<8); `test_ticket_so_vale_uma_vez`; `test_ticket_expira_em_10_minutos`.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** com `SELECT ... FOR UPDATE` no código para evitar corrida de tentativas; marcar `usado_em` ao gerar o ticket.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** — `feat(aluno): conferir código e definir senha`

### Task 5: Entrar com senha, sessão atual e sair

**Files:**
- Modify: `backend/aluno_auth.py`
- Test: `backend/tests/test_aluno_auth_sessao.py`

**Interfaces:**
- Produces: `POST /aluno/auth/entrar` `{email, senha, aparelho?}` → `200 {token, expira_em, aluno}` / `401 {"detail":"credenciais_invalidas"}` (igual para e-mail inexistente, senha errada, aluno inativo); `POST /aluno/auth/sair` (Bearer) → `204`; `GET /aluno/eu` (Bearer) → `{id, nome, email, academia: {id, nome, pais, moeda}, plano: {id, nome, modalidades}|null, status}`; dependência `aluno_atual(token) -> dict` exportada para os planos seguintes.

- [ ] **Step 1: Testes**: `test_entrar_com_senha_correta`; `test_senha_errada_e_email_inexistente_mesma_resposta_e_tempo_proximo` (usa `verificar_senha(None…)` do hash fictício); `test_oitava_falha_bloqueia_com_429_retry_after`; `test_sair_revoga_sessao`; `test_eu_exige_token_valido`; `test_sessao_expirada_ou_revogada_da_401`; `test_aluno_inativado_perde_acesso_imediatamente`.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** reutilizando `seguranca.verificar_senha` e `login_rate_limiter` de `main` (injetar para evitar import circular).
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** — `feat(aluno): entrar, sair e sessão atual`

### Task 6: Login com Google

**Files:**
- Modify: `backend/aluno_auth.py`, `backend/requirements.txt` (somente se necessário `google-auth`; preferir validar o ID token pelas chaves públicas do Google com `PyJWT` já presente)
- Test: `backend/tests/test_aluno_auth_google.py`

**Interfaces:**
- Produces: `POST /aluno/auth/google` `{id_token}` → mesma resposta de `/entrar`; `validar_id_token_google(id_token: str, audiencias: list[str], jwks_fetch=...) -> dict` (retorna `sub`, `email`, `email_verified`); env `GOOGLE_ALUNO_CLIENT_IDS` (lista, separada por vírgula).

- [ ] **Step 1: Testes** com chaves RSA geradas no teste e `jwks_fetch` falso: `test_google_com_email_cadastrado_entra_e_vincula_sub`; `test_google_com_email_nao_cadastrado_e_negado`; `test_google_email_nao_verificado_e_negado`; `test_audiencia_errada_e_negada`; `test_token_expirado_e_negado`; `test_segundo_login_exige_mesmo_sub`.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** validação de assinatura RS256, `iss` (`https://accounts.google.com`), `aud`, `exp`; cria linha em `aluno_credenciais` sem senha (`senha_hash` nulo) com `google_sub`. Sem `GOOGLE_ALUNO_CLIENT_IDS` configurado a rota responde `503 google_nao_configurado`.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** — `feat(aluno): login com Google`

### Task 7: Painel — convite e e-mail do aluno

**Files:**
- Modify: `backend/main.py` (`POST /alunos`, `PATCH /alunos/{id}`, `GET /alunos/{id}`: campo `email` e `acesso_app`), `backend/static/app.js` e `index.html` (campo E-mail na ficha, selo "Acesso ao app: convidado/ativo", botão "Reenviar convite" e "Redefinir acesso")
- Create: `POST /alunos/{id}/convite` e `POST /alunos/{id}/redefinir-acesso` (somente dono/recepção)
- Test: `backend/tests/test_alunos_email_painel.py`

**Interfaces:**
- Consumes: `aluno_auth.iniciar_acesso`.
- Produces: `acesso_app` ∈ `sem_email|convidado|ativo`; `redefinir-acesso` revoga sessões e apaga a credencial para novo primeiro acesso.

- [ ] **Step 1: Testes**: `test_cadastro_aceita_email_e_normaliza`; `test_email_duplicado_na_academia_retorna_409`; `test_convite_envia_codigo`; `test_redefinir_acesso_revoga_sessoes`; `test_papel_sem_permissao_recebe_403`.
- [ ] **Step 2–4:** falhar → implementar → passar.
- [ ] **Step 5: Commit** — `feat(painel): e-mail do aluno e convite ao app`

### Task 8: Dados de teste, flag e pacote de publicação

**Files:**
- Create: `backend/tests/fixtures_aluno.py` (aluno `testealuno@gmail.com`, senha de teste com hash gerado em tempo de execução, **somente** em banco descartável), `docs/superpowers/relatorios/2026-10-11-plano-1.md`
- Modify: `DEPLOYMENT_NOTES.md` (projeto), `backend/recursos_premium.py` ou tabela de recursos para a flag `app_aluno_login` (padrão desligada)

- [ ] **Step 1: Teste** `test_fixture_nao_roda_fora_de_banco_descartavel` (recusa conexão cuja base não termina em `_test`).
- [ ] **Step 2–4:** falhar → implementar → passar; rodar a suíte completa em Python 3.13 e registrar contagem.
- [ ] **Step 5: Escrever o relatório** (arquivos, testes, resultado, riscos) e atualizar o checklist de publicação com: aplicar 043–045 só após backup e com autorização do dono; configurar SMTP e `GOOGLE_ALUNO_CLIENT_IDS`; ligar a flag só na academia de demonstração.
- [ ] **Step 6: Commit** — `chore(aluno): fixtures, flag e relatório do plano 1`
