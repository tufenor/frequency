# Frequency — guia backend

## Estado

Em desenvolvimento, sem autorização de release. Código Python/FastAPI, Uvicorn, psycopg/PostgreSQL, SQL parametrizado, migrations SQL, sem ORM. API concentrada em `backend/main.py`; autenticação em `seguranca.py`, regras SaaS em `cobranca_saas.py`; sincronização e backups em módulos próprios. Não foi feita refatoração arquitetural.

## Instalação e ambiente

Dependências fixadas em `backend/requirements.txt`. Use ambiente virtual e PostgreSQL separado por ambiente. Consulte `backend/.env.example` para nomes de configuração; nunca copie segredos para documentação. Configuração mínima: `SECRET_KEY` de pelo menos 32 caracteres e `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`. Produção deve usar usuário de banco com privilégios mínimos.

Desenvolvimento: na pasta `frontend`, `npm run dev` inicia o FastAPI com o ambiente virtual local, servindo `frontend/public`. Alternativa, na pasta `backend`: `python -m uvicorn main:app --host 127.0.0.1 --port 8000`. O segredo inválido impede inicialização. Esse comando não configura HTTPS nem serviço automático.

## Banco e migrations

Migrations `001` a `010` em `backend/migrations`. A suíte isolada aplica os arquivos em ordem ao PostgreSQL temporário. Migração008 contém planos, assinaturas, faturas, QR e auditoria da plataforma. Migração009 adiciona categoria Essencial/Profissional/Premium e flags de câmera/Spotify; as rotas de integração verificam o pacote atual no servidor. Migração010 adiciona cidade, estado, endereço e código postal à academia. Não aplicar manualmente mudanças ao banco em uso: preparar backup, ensaiar migrations e restore em staging antes da implantação. Correções BE-01/02/03 não exigem nova migration.

Spotify fica bloqueado por padrão em pacotes pagos. `FREQUENCY_SPOTIFY_COMMERCIAL_APPROVED=true` só pode ser usado após autorização comercial escrita aplicável; a configuração do usuário do cliente não deve liberar o recurso. Câmeras só aceitam transmissões HTTP/HTTPS compatíveis com navegador; RTSP/ONVIF ainda precisa de uma ponte local.

## API e testes

Veja [contrato de cobrança](api-contract.md), contrato central e `/openapi.json` da instalação. O contrato completo consolidado ainda é uma pendência.

Na raiz, Windows:

```powershell
.\backend\venv\Scripts\python.exe -m unittest discover -s backend/tests -v
```

Os testes de integração criam PostgreSQL descartável, usam dados sintéticos e impedem carregamento do `.env`. Exigem binários PostgreSQL instalados. Nunca alterar a conexão desses testes para um banco de cliente. Consulte [status](PROJECT_STATUS.md) para resultados efetivamente obtidos.

Frontend estático, a partir de `frontend`: `npm run lint`, `npm test`, `npm run build`. O build valida páginas e referências a assets e copia `public/` para `dist/`. Para servir o build com a API, defina `FREQUENCY_FRONTEND_DIR` como o caminho absoluto de `frontend/dist` antes de iniciar Uvicorn. Sem essa variável, o servidor usa `frontend/public` para desenvolvimento.

## Produção, backup e recuperação

Produção ainda requer homologação do comando de serviço, HTTPS/proxy, timeouts, observabilidade, revisão de dependências, conta de banco e ensaio de recuperação. Não existe evidência de instalação de servidor pago neste trabalho.

Rotina existente: `backend/ops/backup_postgres.py`, dumps PostgreSQL comprimidos e criptografados com age; upload S3, retenção controlada e arquivo de estado atômico. Por padrão desativada. Consulte `backend/ops/README.md`. Os testes de checksum/retenção não equivalem a restore real. O endpoint `/operacao/status` informa se houve execução; `nunca_executado` não é sucesso.

Procedimento de recuperação a ensaiar: obter arquivo criptografado e chave privada guardada separadamente; validar integridade; descriptografar em ambiente protegido; restaurar com pg_restore para banco novo isolado; aplicar versão compatível da aplicação; conferir contas, contagens, vínculos, faturas e acesso; só então planejar troca do serviço. Não restaurar por cima do banco em uso. Instalação como serviço e teste completo desse procedimento estão pendentes.

Sincronização local → nuvem descrita em `backend/SINCRONIZACAO.md`; não substitui backup. O iniciador local está em `backend/ops/local_server.py`, mas ainda faltam executável Windows, instalação do banco e agendamento automático homologados.

## Diagnóstico

- 401: autenticação inválida/expirada; não registrar tokens.
- 402: verificar fatura e status manual da assinatura.
- 409 ao cancelar: suspensão explícita necessária se última fatura ativa.
- 503 em cobrança: conferir migrations no ambiente correto.
- Teste acusa plano duplicado: verificar limpeza das tabelas SaaS no banco descartável.

## Inventário inicial resumido

| Área | Estado | Evidência / pendência |
|---|---|---|
| API, autenticação, ownership | PARTIAL | Implementação e testes existentes; auditoria final pendente |
| Banco, migrations001–010 | PARTIAL | Aplicadas em testes; staging/restore pendentes |
| Cobrança manual/QR | PARTIAL | Correções de integridade; banco automático ausente |
| Fila/sync | PARTIAL | Outbox ordenada/idempotente; HTTPS real/reinício pendentes |
| Cache | MISSING | Sem cache de dados; nenhuma necessidade comprovada |
| Backup | PARTIAL | Script e testes de armazenamento; restore integral pendente |
| Build frontend | PARTIAL | Build/lint/test Node executam; teste visual em cliente e integração ao instalador ainda pendentes |
| Executável/serviço local | PARTIAL | Check/iniciador local prontos; distribuição ainda não homologada |
| CI/CD e produção | MISSING | Sem pipeline/deploy homologados |
| Isolamento Git | RISK | Branch work/backend-frequency criada; sem commit inicial, checkout compartilhado |

Próximas etapas: concluir regressões de cobrança; distribuição/integrar frontend; regionalização persistida; pacotes/permissões; indicadores/despesas; offline/instalador; staging/backup/restore; segurança/carga e entrega. Credenciais bancárias, provedor pago e equipamento físico dependem de informações externas.
