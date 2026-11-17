# Verificação Frequency V1 — 2026-10-04

## Alterações deste bloco

- O limite do painel de notificações faciais voltou a exibir até oito eventos recentes.
- O monitor legado por `chave_monitor_hash` continua compatível quando a tabela de monitores ainda não tem uma linha correspondente.
- A prontidão local exige as migrations centrais 001–010 e rejeita estados parciais; migrations opcionais totalmente ausentes não bloqueiam o V1.
- Foram preparados `Dockerfile`, `docker-compose.production.yml`, `Caddyfile`, `.env.production.example` e o guia de operação Docker. O compose não aplica SQL automaticamente.

## Evidências executadas

- Frontend: `npm test` — 17/17; `npm run lint` — 12 arquivos; `npm run build` — concluído.
- Backend focado: 18 testes passando (QR, readiness, verificação de migrations e notificações faciais).
- Prontidão local: banco disponível, frontend disponível, migrations centrais completas, `pronto: true`.
- Suíte backend completa: 63 testes, 55 aprovados e 8 falhas.
## Pendências reais antes do piloto

- As quatro falhas restantes precisam de decisão/revisão: uma reflete o status de backup carregado pelo ambiente de teste, duas refletem expectativas antigas sobre limites/campos de hardware e uma reflete a resposta histórica de perfil. A regra comercial de academias legadas sem assinatura foi corrigida com `status_comercial`.
- Docker não foi executado neste computador porque o engine não está instalado; build e subida ainda precisam ser validados em staging.
- A interface atual permanece frontend estático/PWA. A migração ampla para React + TypeScript foi deliberadamente adiada para não reescrever fluxos funcionais sem um contrato de API aprovado.
- Não declarar produção liberada enquanto autenticação real, backup/restore separado, sync em dois ambientes e staging HTTPS não forem verificados.

## Migração local concluída neste bloco

- Dump local pré-alteração: `backend/backups/frequency-pre-024-025-20261004.dump` (1.703.587 bytes; SHA-256 `CF0B118ABEFCAD8B87ECB4482B26F724AEA81E089375DA322BE9E37926316FE1`).
- Dump adicional antes da migration 026: `backend/backups/frequency-pre-026-20261004.dump` (1.716.683 bytes; SHA-256 `3FC9EEA2CC7F886FA4F2281E1A6DC3738BA46409BA69B2B9B6E029E728D981FE`).
- Aplicadas em ordem: `021_hardware_frequency.sql`, `022_monitores_eventos_individuais.sql`, `023_sessoes_telas_acesso.sql`, `024_relogio_local.sql`, `025_codigo_monitor_persistente.sql` e `026_status_comercial_academia.sql`.
- Contagens preservadas após a migração: 3 academias, 5 usuários, 9 alunos, 1 monitor e 2 leitores.
- A regra de relógio persistente agora integra a cobrança; recuo de data bloqueia a academia com `relogio_local_recuou` e o ensaio transacional não deixou alteração nos dados.
- Suíte backend completa: 63 testes, 59 aprovados e 4 falhas de expectativas/ambiente antigas; QR, readiness, migrations e facial permanecem verdes.

## Bloco frontend TypeScript/SEO — 04/10/2026

- Adicionado `frontend/tsconfig.json` em modo estrito e `frontend/src/site.ts`, compilado para `frontend/public/static/generated/site.js`.
- O site público mantém o painel autenticado existente e passou a usar o controlador tipado sem reescrever componentes estáveis.
- SEO e compartilhamento revisados: idioma padrão em português, description, robots, theme-color, canonical, Open Graph/Twitter e JSON-LD coerente.
- Responsividade revisada para desktop, tablet e telas pequenas, com foco visível, skip link, alvos de toque, movimento reduzido e renderização adiada das seções abaixo da dobra.
- Cotação cambial deixou de bloquear a primeira pintura; o fallback local mantém a página funcional offline.
- PWA shell atualizado para incluir a entrada pública e os assets versionados sem armazenar dados privados.
- Verificação: `npm run typecheck`, `npm test` (20/20), `npm run lint` (14 arquivos) e `npm run build` concluídos.
- Pendência real: não foi atribuído um score de PageSpeed/Lighthouse nesta execução; a validação executada é estática e de build. A migração integral do painel para React/TypeScript continua planejada por módulos, condicionada ao contrato da API.

## Backup e dispositivos — 04/10/2026

- O app identifica desktop, mobile e tablet, incluindo iPadOS (MacIntel com pontos de toque), sem bloquear o uso do backup.
- Todos os dispositivos autorizados podem iniciar a cópia e baixar o arquivo criptografado pela rota /operacao/backup/download.
- Navegadores com File System Access API podem escolher uma pasta e gravar o arquivo nela; iPhone, iPad, Android e navegadores sem essa API usam o download padrão do sistema.
- O seletor nativo do backend continua sendo uma opção do computador que hospeda o Frequency; sua ausência não impede o download para outro dispositivo.
- Verificação deste ajuste: node --check frontend/public/static/app.js, python -m py_compile backend/main.py, testes frontend, lint e build.

- A nuvem segue o mesmo princípio multiplataforma: Drive montado no computador pode ser destino local sincronizado; celular e tablet usam compartilhamento nativo ou download seguro, sem alegar upload automático.

## Publicação web do backup multiplataforma — 04/10/2026

- O VPS foi preservado antes da publicação em /opt/frequency-deploy-backups/backup-cross-device-20261004T183541Z.
- Publicados frontend/public/index.html, frontend/public/static/app.js, frontend/public/static/styles.css, frontend/public/service-worker.js e backend/main.py.
- O domínio respondeu HTTP 200 com o marcador backup-cross-device-20261004; o OpenAPI público passou a expor /operacao/backup/download.
- Os três contêineres Docker ficaram em execução e o endpoint de download sem autenticação respondeu 401, confirmando que a rota permanece protegida.

## Salvamento no iPhone, iPad e Android — 04/10/2026

- O botão muda para “Salvar no dispositivo” em celulares e tablets.
- iPhone/iPad abrem o compartilhamento nativo; o usuário escolhe “Salvar em Arquivos”. Android oferece Files, Downloads ou Google Drive.
- O formulário de pasta local fica oculto nesses dispositivos, pois controla somente o computador que hospeda o Frequency.
- Navegadores sem compartilhamento de arquivos usam download padrão, preservando o arquivo criptografado.
- Publicado com o cache `backup-save-device-20261004-v6`; testes frontend 21/21, typecheck, lint, build e verificação pública concluídos.

## Fluxo funcional de backup móvel — 04/10/2026

- O botão “Salvar no dispositivo” agora cria automaticamente uma cópia criptografada quando ainda não existe uma disponível; depois abre o compartilhamento nativo do iPhone/iPad/Android.
- O contêiner online foi configurado com volume persistente `/backups`, `BACKUP_ENABLE=YES`, `BACKUP_STORAGE_PROVIDER=local` e chave pública `age`.
- O cliente `pg_dump` da imagem foi alinhado ao PostgreSQL 18 do servidor.
- Dump real executado no banco online: arquivo criptografado de 392.103 bytes, estado `sucesso`, download autenticado validado.
- Verificação pública: app v5, OpenAPI com `/operacao/backup/download`, resposta 401 sem autenticação e três contêineres saudáveis.
- A chave privada de restauração foi gerada localmente em pasta ignorada pelo Git; ela não foi enviada ao contêiner nem exposta na aplicação.