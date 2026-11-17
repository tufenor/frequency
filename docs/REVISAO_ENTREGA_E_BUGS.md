# Revisão de entrega e bugs

## Notificações faciais no painel — 01/10/2026

Validação: frontend 16/16 testes e lint; node --check; build estático; testes direcionados de regras de acesso, vínculo de plano e notificações em PostgreSQL descartável; login/autenticação aprovados. git diff --check aprovado. A validação visual com câmera real em desktop/tablet/celular e o deploy continuam pendentes. Os testes de acesso isolam a assinatura SaaS para verificar especificamente plano, vencimento e registro de tentativa sem aluno identificado; isso não comprova uso real da câmera.

O painel /app exibe até oito acessos faciais novos na lateral, com Liberado/Bloqueado, nome, ícone e data/hora no idioma selecionado. O clique abre Alunos e o formulário existente quando há aluno identificado, respeitando as permissões de gravação. Eventos sem identificação são registrados sem aluno e não têm ação de perfil. A consulta incremental de /presencas usa o último ID, aproximadamente a cada 2,5 segundos; a abertura estabelece a linha de base sem mostrar histórico como novidade. Logout cancela a atualização e limpa a lista. O contador representa os cartões presentes. Erros de imagem ou motor facial continuam sendo erros, sem registro de acesso.

Deploy verificado em 01/10/2026 no local (porta 8000) e em https://frequencygym.tech/app. No VPS Hostinger, aplicação Docker reconstruída e reiniciada, HTTPS 200, painel/arquivos estáticos e cursor depois confirmados; PostgreSQL saudável. Alterações anteriores da versão web foram preservadas por combinação dos cinco arquivos da funcionalidade. Cópia de recuperação: /opt/frequency-deploy-backups/facial-20261001-1790876713/files.tar.gz; imagem anterior: frequency-app:before-facial-20261001. Serviços usam restart unless-stopped. Com o PC desligado, o local para e o VPS continua. Backup periódico estava desativado no compose; restauração e teste visual com câmera real continuam pendentes, portanto o deploy não significa homologação completa de produção.

Atualização: 01/10/2026.

## Estado validado

- migrations 001–010 completas no banco local;
- verificação de prontidão local aprovada;
- 51 testes de backend aprovados em PostgreSQL descartável;
- 12 testes de frontend, lint e build aprovados;
- painel disponível em `http://192.168.0.4:8000/app`;
- tela de entrada disponível em `http://192.168.0.4:8000/monitor`.

## Bugs corrigidos

- reagendamento de assinatura agora atualiza a fatura aberta na mesma transação;
- cancelamento da última fatura aberta de assinatura ativa é recusado;
- edição com nome nulo retorna erro controlado;
- monitor recebe acessos em ordem e não perde uma pequena sequência de eventos;
- falha de rede e código inválido do monitor têm mensagens diferentes;
- idioma/moeda da Bolívia usam a normalização regional compartilhada;
- recursos de câmeras e Spotify são validados pelo backend e pelo pacote Premium;
- Spotify comercial fica bloqueado por padrão;
- iniciador local recusa banco, migrations ou frontend incompletos;
- estado do backup é gravado atomicamente sem incluir credenciais.

## Pendências que impedem produção homologada

- executar backup e restauração de prova em destino definido;
- fixar o IP da máquina no roteador e revisar o firewall;
- homologar catraca, leitor biométrico e câmera reais;
- concluir instalador/serviço Windows com atualização e rollback;
- validar sincronização e recuperação em staging HTTPS;
- definir provedor bancário/webhook, se houver cobrança automática;
- usar serviço de música com licença comercial ou autorização aplicável;
- executar piloto acompanhado com o primeiro cliente.

O sistema pode ser demonstrado localmente, mas ainda não deve ser descrito como
produção homologada enquanto essas pendências continuarem abertas.
