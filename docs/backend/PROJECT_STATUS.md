# Status backend — 01/10/2026

## Reservas de aulas e áreas — 09/10/2026

O MVP de reservas foi implementado no backend com recursos `aula`/`area`,
sessões com capacidade, isolamento por academia, cancelamento e proteção
contra concorrência. A migration 041 foi testada somente em PostgreSQL
descartável e permanece pendente no banco configurado. Contrato e arquivos
alterados estão registrados em `API_CONTRACT.md` e no status raiz.
O MVP cancela uma reserva e permite reservar novamente na mesma sessão; ele
não altera o horário da sessão.
Auditoria somente leitura também encontrou migrations 018–020 e 027–041
ausentes no banco configurado; nenhuma alteração foi aplicada nele.

## Pagamento online da assinatura — 01/10/2026

O núcleo local agora está preparado para criar checkout dLocal e receber
notificações assinadas em `POST /webhooks/dlocal`. A confirmação confere
referência, valor e moeda, registra o evento uma única vez e gera a próxima
fatura na mesma transação. A migração `015_pagamentos_online.sql`, HTTPS
público e credenciais dLocal de sandbox/produção ainda precisam ser configurados
fora do repositório; sem esses três itens o QR manual continua sendo o único
meio disponível e nenhuma cobrança é liberada automaticamente.

## Notificações faciais no painel — 01/10/2026

O painel /app exibe até oito acessos faciais novos na lateral, com Liberado/Bloqueado, nome, ícone e data/hora no idioma selecionado. O clique abre Alunos e o formulário existente quando há aluno identificado, respeitando as permissões de gravação. Eventos sem identificação são registrados sem aluno e não têm ação de perfil. A consulta incremental de /presencas usa o último ID, aproximadamente a cada 2,5 segundos; a abertura estabelece a linha de base sem mostrar histórico como novidade. Logout cancela a atualização e limpa a lista. O contador representa os cartões presentes. Erros de imagem ou motor facial continuam sendo erros, sem registro de acesso.

Deploy verificado em 01/10/2026 no local (porta 8000) e em https://frequencygym.tech/app. No VPS Hostinger, aplicação Docker reconstruída e reiniciada, HTTPS 200, painel/arquivos estáticos e cursor depois confirmados; PostgreSQL saudável. Alterações anteriores da versão web foram preservadas por combinação dos cinco arquivos da funcionalidade. Cópia de recuperação: /opt/frequency-deploy-backups/facial-20261001-1790876713/files.tar.gz; imagem anterior: frequency-app:before-facial-20261001. Serviços usam restart unless-stopped. Com o PC desligado, o local para e o VPS continua. Backup periódico estava desativado no compose; restauração e teste visual com câmera real continuam pendentes, portanto o deploy não significa homologação completa de produção.

## Etapas validadas

Implementado: BE-01 reagendamento transacional da fatura aberta com assinatura e auditoria; BE-02 validação422 de nome nulo/espaços; BE-03 recusa409 de cancelamento da última fatura ativa. Pagamento/cancelamento serializados pela assinatura.

Arquivos modificados: `backend/main.py`, `backend/tests/test_business_postgres.py`; documentação nova em `docs/backend/`.

Testes: cobrança cobre reagendamento da fatura junto à assinatura, cancelamento concorrente e assinatura suspensa. O registro histórico `Ran 51 tests in 79.075s — OK` foi supersedido; a contagem de release deve vir da suíte completa após a revisão atual. Frontend: `npm run lint` verificou 8 arquivos, `npm test` passou com 12 testes e `npm run build` gerou `frontend/dist`; o painel agora mostra o estado seguro da operação para administrador/dono. Smoke test com banco temporário e contas fictícias confirmou login de administrador, dono e recepção, academias, pacotes, cobrança/QR, câmera Premium e monitor conectado.

Problemas: distribuição oficial instalada, execução diária do backup, restauração e serviço HTTPS ainda não homologados. Contratos regionais além de Brasil/Bolívia, indicadores completos, instalador, integração bancária, testes visuais/E2E e produção pendentes. Frontend em `frontend/dist` pode ser servido com `FREQUENCY_FRONTEND_DIR`; por padrão a API usa `frontend/public`. `/operacao/status` e `ops.local_server --check` já existem, mas não substituem staging, servidor externo ou restauração real.

Decisões para coordenação: confirmar política de reativação de assinatura sem fatura após suspensão/cancelamento; definir matriz dos três pacotes e licenciamento offline.

Não pronto para release. Progresso global e prazo ainda sem base suficiente para percentual/estimativa responsável. Risco atual alto para entrega a cliente até staging e recuperação serem comprovados.
