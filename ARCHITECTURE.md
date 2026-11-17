# Arquitetura do frontend Frequency

Registro criado em 28/09/2026 a partir do código existente; o documento não existia anteriormente.

- Interface web estática HTML/CSS/JavaScript, servida pela API FastAPI em `/app`.
- `frontend/public/static/app.js`: sessão, perfis, navegação, alunos, pagamentos, planos, academias, equipe e configuração do monitor.
- `frontend/public/static/business.js`: telas comerciais, gráficos por moeda, faturas, QR e assinatura. Usa somente rotas existentes documentadas em API_CONTRACT.md.
- `frontend/public/static/i18n.js`: cinco idiomas de interface e preferências locais de idioma; escolha independente da moeda.
- `/monitor` usa arquivos próprios e uma chave de leitura restrita aos eventos recentes. Não compartilha a sessão administrativa.
- SVG/CSS e fontes do sistema; sem CDN, bibliotecas de gráficos ou dependência de internet para carregar a interface local.
- JWT apenas em sessionStorage; imagens privadas carregadas com autenticação e URLs temporárias revogadas.
- Nenhum saldo/dado de cliente simulado no produto. Testes de navegador usam servidor isolado e respostas sintéticas.
- Permissões são aplicadas pelo backend. Ocultação de menu apenas orienta a interface.
- `/operacao/status` apresenta ao administrador/dono o estado seguro do banco, frontend, sincronização e backup; não expõe segredos.
- `backend/ops/local_server.py` verifica a instalação antes de iniciar o Uvicorn e não aplica migrações automaticamente.

Operação offline, instalador e backups continuam detalhados em ARQUITETURA_ONLINE_OFFLINE_FREQUENCY.md. A tela local requer o serviço e banco em funcionamento; não é por si só um executável ou um banco offline de navegador.
