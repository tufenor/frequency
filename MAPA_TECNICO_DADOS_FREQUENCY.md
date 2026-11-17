# Mapa técnico de dados do Frequency

**Situação:** inventário técnico interno, baseado no código e no esquema do banco revisados em 28/09/2026. Não é uma avaliação jurídica nem uma política de privacidade aprovada. Deve ser revisado com o responsável pela academia e por profissional de privacidade antes de usar dados reais.

## 1. Dados presentes no esquema

| Grupo | Campos e registros | Uso observado no sistema | Observações |
|---|---|---|---|
| Academia | Nome, país, status ativo/suspenso | Identificar e administrar a academia | O administrador da plataforma cadastra, consulta e suspende academias. |
| Aluno | Nome, telefone, documento, data de nascimento, data de início, plano, identificador numérico de biometria, status | Matrícula, consulta e decisão de acesso | O identificador é um número associado ao cadastro. O esquema não contém imagem ou modelo biométrico. O equipamento externo ainda não foi verificado. |
| Plano | Nome, valor, duração em dias e academia | Informar o plano e calcular cobranças | Dono cria; recepção consulta. |
| Pagamento | Valor, vencimento, data de pagamento, status e referências do aluno e da academia | Acompanhar cobranças e registrar recebimentos | Não há campo de forma de pagamento, comprovante ou estorno no esquema atual. |
| Presença/acesso | Data e hora, resultado liberado/bloqueado, motivo, aluno e academia | Registrar tentativas de acesso | A tela consulta até 100 registros por vez; a API aceita até 500. |
| Situação do aluno | Nome, status, último pagamento, próximo vencimento, dias restantes e alerta | Resumo operacional calculado a partir de alunos e pagamentos | É uma view do banco, não uma tabela de cadastro independente. |
| Usuários | Nome, e-mail, hash de senha, perfil, academia e status ativo | Login e controle de acesso | A senha é armazenada como hash usando a biblioteca `pwdlib` com algoritmo recomendado; não é retornada pelas rotas de usuário. |
| Leitores/catracas | Nome do leitor, academia, hash da chave, status e data de criação | Autenticar chamadas do leitor à API | A chave em texto só é exibida quando o leitor é criado. A integração com aparelho real não foi validada. |

## 2. Onde os dados ficam e circulam

- O aplicativo lê e grava no PostgreSQL indicado pelas configurações locais do backend. A configuração está no arquivo `.env`, que não deve ser copiado para este documento, para o Git ou para mensagens.
- A interface envia solicitações à API do Frequency. O token de acesso fica no `sessionStorage` da aba do navegador e expira após oito horas; ao detectar sessão inválida, o aplicativo a remove.
- Senhas e chaves de leitor não são devolvidas nas rotas normais de consulta. O sistema guarda hashes: `pwdlib` para senhas e SHA-256 para a chave do leitor.
- O servidor local gera registros técnicos de acesso com endereço de origem, rota e resultado HTTP. Retenção, cópia e acesso a esses registros dependem de como o servidor for executado; isso ainda não foi definido para produção.
- Não foi encontrada integração externa de e-mail, pagamentos, analytics ou armazenamento de arquivos no código revisado. A conexão com equipamento físico e qualquer serviço exigido pelo fabricante continuam desconhecidos.

## 3. Acesso por perfil observado

- **Dono da academia:** consulta e administra alunos, planos, pagamentos, presença e contas da recepção da própria academia.
- **Recepção:** consulta e opera os fluxos autorizados de alunos, pagamentos e acessos da própria academia; não administra equipe, não cria planos e não altera o status do aluno.
- **Administrador da plataforma:** administra registros de academias. As rotas operacionais de alunos e cobranças recusam esse perfil.
- **Leitor/catraca:** chama somente o fluxo de autorização de acesso com uma chave própria; a chave é verificada por hash e vinculada a uma academia ativa.

Os filtros por academia foram conferidos na API e há uma segunda migração preparada para impedir relações entre academias. Essa migração ainda não foi aplicada ao banco local de demonstração.

## 4. Retenção e pontos ainda sem decisão

O código não define prazo de retenção nem rotina automática de descarte para alunos inativos, pagamentos, histórico de acesso, contas suspensas, logs ou backups. Não foi definida exclusão/anonimização quando termina o vínculo com a academia.

Antes do piloto, o cliente precisa definir finalidade e prazo de cada conjunto de dados, quem pode consultar ou corrigir, como tratar pedidos de exclusão, quem responde por incidentes, como encerrar o contrato e como apagar cópias de backup dentro do prazo acordado. Esses itens precisam de revisão profissional antes de serem tratados como política ou obrigação cumprida.

## 5. Informações que dependem do cliente e do fabricante

- Fabricante, modelo, versão, interface de comunicação e documentação da catraca.
- Se o aparelho guarda apenas um número de identificação ou também imagem, molde ou outro dado biométrico, e em que local.
- Se a comunicação exige SDK, serviço intermediário, rede local ou conexão externa.
- Quem opera a infraestrutura, onde o banco ficará hospedado e por quanto tempo logs e backups serão mantidos.
- Quais dados do aluno são realmente necessários para o serviço e quais não devem ser coletados.
- Procedimento aprovado para corrigir, exportar e apagar dados e para atender incidente ou encerramento do contrato.

## 6. Arquivos usados para este levantamento

- `backend/migrations/001_initial_schema.sql` — tabelas, view e campos.
- `backend/main.py` e `backend/seguranca.py` — rotas, autenticação e permissões.
- `backend/static/app.js` — fluxos da interface e armazenamento de sessão.
- `backend/database.py` — conexão do backend com PostgreSQL.
