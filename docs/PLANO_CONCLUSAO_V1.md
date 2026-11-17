# Plano de conclusão — Frequency Gym v1 comercial

Elaborado em 2026-10-09 por Claude (Opus 5.5) e GPT (Codex CLI, GPT-5), a partir do código atual, dos testes executados nesta data e de `CLAUDE_HANDOFF_FREQUENCY.md`.

## Situação verificada em 2026-10-09

| Item | Estado |
|---|---|
| Frontend `npm test` | 22/22 |
| Backend `pytest backend/tests` | 68/70; as 2 falhas estão em `test_business_postgres.py` |
| Falha 1 | `POST /academia/tela-acesso/chave` → 403 `limite_de_monitores_do_plano_atingido` (academia sem plano tem `max_monitores = 0`) |
| Falha 2 | `test_http_roles_and_tenant_isolation` falha na suíte e passa isolado: estado compartilhado entre testes |
| Migrations | Duas com número `031` (`prospeccao_osm` e `vinculo_frequency_local`); 013, 020 e 024–040 fora do Git |
| Git | Sem remote; escrita em `.git` bloqueada pelo Windows; ~3.000 linhas e ~130 arquivos sem commit |
| Sessão | Token Bearer em `sessionStorage`, não em cookie HttpOnly |
| Saúde | Sem `/health`; o healthcheck do Docker usa `/docs`, que expõe o Swagger em produção |
| Rotas órfãs | `/integracoes` e `/spotify` apontam para HTML apagado |
| Arquivos de risco | `frequency-pre-034.dump`, zips de 3 GB, instaladores de 728 MB no diretório público |
| Testes | Imports mistos (`backend.X` e `X`); só rodam com a raiz no path e `PYTHONPATH=backend` |

## Definição de "v1 comercial concluída"

- [ ] Deploy reproduzível a partir do Git: código, migrations sem duplicidade e configuração.
- [ ] Backup, restauração e rollback testados com sucesso.
- [ ] Cadastro, login, academia, alunos, planos, limites, QR e webhook dLocal funcionando em produção.
- [ ] Isolamento por `academia_id`, papéis e sessão cobertos por testes negativos automatizados e com a suíte estável.
- [ ] Google OAuth validado em navegador real, incluindo erro, logout e retorno.
- [ ] Instalador Windows funcionando em máquina sem PostgreSQL.
- [ ] Modo offline, sincronização, conflito e reconexão testados em equipamento real.
- [ ] Fluxos críticos funcionando em Android, iPhone/iPad e desktop.
- [ ] Recursos não homologados (Spotify, câmera RTSP etc.) desligados ou marcados como pendentes no servidor.
- [ ] `/health` dedicado, logs úteis, rollback documentado e go/no-go assinado pelo dono.

## Fases

| Fase | Objetivo | Quem | Saída |
|---|---|---|---|
| 0. Desbloqueio | Liberar a escrita em `.git` e configurar um remote privado. Decidir o destino do dump, dos zips e dos instaladores grandes. Primeiro commit seletivo. | Dono libera; Claude commita | Histórico recuperável e working tree limpo |
| 1. Evidência e contenção | Inventário de migrations, rotas, arquivos sensíveis (com hashes) e estado do Git. Schema congelado. | Claude coleta; GPT revisa | Matriz de migrations sem ambiguidade e lista de riscos |
| 2. Testes, migrations e 503 | Colisão do `031` resolvida com `042_vinculo_frequency_local.sql`. Adicionar `conftest.py` com imports determinísticos. Corrigir o estado compartilhado. Decidir a regra de monitores. Reproduzir o 503 de cadastro/QR. | Claude implementa; GPT revisa | Suíte 100% estável em qualquer ordem e fluxo de cadastro/QR aprovado |
| 3. Segurança e contrato | Auditoria multi-tenant e de papéis. Destino das rotas órfãs. `/health`. Swagger fechado em produção. Plano de sessão com cookie + CSRF (ou risco aceito por escrito). | Claude implementa; GPT audita | Testes negativos verdes e contrato da API coerente com as rotas reais |
| 4. Release | Build Docker validado (staging ou Docker Desktop), backup antes do deploy, deploy controlado, smoke test e rollback ensaiado. | Dono opera o VPS; Claude prepara e acompanha; GPT revisa as evidências | Local e produção na mesma versão, rollback comprovado |
| 5. Integrações e dispositivos | OAuth, dLocal real, instalador limpo, sync offline, câmera, leitores e celulares. | Dono fornece credenciais e equipamentos; Claude executa; GPT analisa | Cada integração aprovada, corrigida ou desligada |
| 6. Aceite | Checklist final, privacidade, planos e limites, documentação de suporte. | Dono decide; Claude prepara; GPT audita | Go/no-go formal |

A refatoração de `backend/main.py` em módulos fica para depois da Fase 3. Antes disso, ela aumenta o risco sem destravar o lançamento.

## Protocolo Claude ↔ GPT

- **Papéis:** Claude é o executor principal neste checkout. O GPT atua como arquiteto e revisor e só edita quando isso for combinado explicitamente. Nunca há dois editores ao mesmo tempo.
- **Contexto do GPT:** o sandbox do Codex no Windows não executa comandos (`helper_unknown_error`). Até isso ser resolvido, o Claude entrega ao GPT os trechos de código, diffs e saídas de teste pela entrada padrão.
- **Handoff:** cada handoff traz os arquivos alterados, o resumo do diff, os comandos executados, os resultados dos testes, os riscos e o próximo passo.
- **Revisão obrigatória** para migrations, autenticação, isolamento multi-tenant, cobrança e deploy.
- **Discordâncias:**
  - questão de **fato** → resolver com teste ou inspeção;
  - questão de **interpretação técnica** → decidir por evidência e por `API_CONTRACT.md`;
  - questão de **produto, legal ou comercial** → levar ao dono.
- **Recuperação:** enquanto `.git` estiver bloqueado, toda mudança precisa de uma cópia recuperável (patch salvo).

## Registro de decisões (2026-10-09)

O dono delegou estas decisões ao Claude, que as tomou como responsável técnico.

| # | Decisão | Motivo | Status |
|---|---|---|---|
| D1 | **Telas de entrada exigem assinatura ativa com vaga** (`max_monitores`). Academia sem plano não gera chave. Academias legadas recebem um plano pelo admin, sem exceção no código. | Hardware é parte do preço do plano: uma exceção abriria uso grátis e duas regras para manter. O teste estava desatualizado desde a migration 021. | Teste corrigido |
| D2 | **Dump, backups, mídia e instaladores ficam fora do Git e da imagem Docker.** Nada é apagado. Instaladores são publicados pelo deploy. | Dados pessoais e arquivos acima de 100 MB não pertencem ao repositório; apagar é irreversível. | `.gitignore` e `.dockerignore` atualizados. Mover os arquivos para `C:\Users\tufen\FrequencyArquivo` exige a autorização do dono (bloqueado pelo sistema). Quando o `.git` for liberado: `git rm --cached` em `FrequencyLocalWindows.exe/.zip`. |
| D3 | **Remote: repositório privado no GitHub.** | É o padrão de mercado, tem CI gratuito (Actions) e é privado por padrão. | Depende de o dono liberar a escrita em `.git` e criar ou autorizar a conta. |
| D4 | **Sessão continua com Bearer em `sessionStorage` na v1. Cookie HttpOnly + CSRF fica para a v1.1.** | A CSP já bloqueia scripts inline e de terceiros (`script-src 'self'`), o token expira em 8 h e `sessionStorage` some ao fechar a aba. Migrar agora mexe em login, logout, monitor e CSRF de uma vez, com risco maior que o benefício antes do lançamento. | Risco aceito e documentado |
| D5 | **`/integracoes` e `/spotify` ficam como estão.** | Correção da análise anterior: elas não estão órfãs, já redirecionam para `/cameras` e `/youtube`. | Nada a fazer |

## Correções aplicadas em 2026-10-09

- **Bug crítico (P0):** a criação de aluno em academia com assinatura ativa quebrava com erro 500. A consulta do limite de alunos usava `alunos.ativo`, coluna que não existe; o certo é `status = 'ativo'`. A causa foi a migration 037, que ainda não está no Git. Corrigido em `backend/main.py`, com teste de regressão `test_student_limit_counts_only_active_students_of_subscribed_academy`. **Se a migration 037 já estiver em produção, todo cliente pagante está sem conseguir cadastrar alunos: publicar esta correção é prioridade máxima.**
- **Furo no limite do plano (P1):** reativar um aluno (`PATCH /alunos/{id}/status`) não verificava o limite de alunos. Dava para criar, inativar, criar de novo e reativar acima do plano. A verificação foi extraída para `_exigir_vaga_de_aluno` e agora vale na criação e na reativação, coberta pelo mesmo teste de regressão.
- **Teste dependente da máquina:** `test_http_roles_and_tenant_isolation` lia o backup real do `.env` local. O teste agora fixa `BACKUP_ENABLE=NO`.
- **Docker:** o build copiava `backend/venv` e mandava ao daemon o zip de 3 GB e o dump. Corrigido no `.dockerignore`.
- **Resultado:** backend com **71/71** testes passando (antes 68/70); frontend com 22/22.
- **Pendente:** a revisão do GPT sobre estas mudanças foi bloqueada pelo sistema de permissões (envio de código para um serviço externo). Também falta revisar se o limite de alunos deve valer no `sync_receiver` (eventos vindos do modo local) e em importações.

## Próximas três tarefas (não dependem do dono)

1. **Claude:** inventário somente leitura (status do Git, migrations, tamanhos e hashes dos arquivos sensíveis), sem apagar nem mover nada.
2. **Claude:** reproduzir as 2 falhas de teste em ordens diferentes e separar bug de produto de teste inválido.
3. **GPT (com contexto entregue pelo Claude):** matriz cruzando `API_CONTRACT.md`, as rotas reais e as chamadas do frontend.
