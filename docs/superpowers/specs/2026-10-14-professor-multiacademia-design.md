# Conta profissional de professor multiacademia

**Status:** desenho aprovado pelo usuário; aguardando revisão da especificação antes do plano de implementação  
**Data:** 2026-10-14  
**Escopo:** autenticação profissional, vínculos multiacademia, permissões da área de lutas/aulas, alunos, turmas, faixas, graduações, planos e auditoria.

## 1. Objetivo e resultado esperado

Permitir que um professor use uma única conta profissional para trabalhar em várias academias. Depois do login, o professor escolhe a academia ativa; a interface e todas as consultas passam a refletir somente aquela academia, suas modalidades, turmas, alunos, planos, idioma, moeda e permissões.

O professor deve ganhar autonomia operacional sem receber controle comercial ou financeiro por padrão. O dono continua responsável por preços, duração, moeda, cobranças, usuários, recursos globais e decisões estruturais.

Critérios de sucesso:

- uma conta profissional pode ter zero, uma ou várias academias vinculadas;
- nenhum endpoint permite ler ou alterar dados de uma academia sem vínculo ativo;
- a troca de academia muda o contexto do token/sessão e atualiza a UI sem misturar dados;
- permissões são avaliadas no servidor, por academia e por recurso;
- alterações sensíveis têm auditoria com autor, horário, antes, depois e motivo;
- o comportamento existente de dono, recepção e aluno permanece compatível.

## 2. Estado atual relevante

O módulo de lutas já possui modalidades, planos ligados a modalidades, professores, turmas, horários, reservas, chamada, presença, faixas, graduação, atestado e relatórios. Atualmente `usuarios` tem um único `academia_id`, `professores.usuario_id` é único e a autorização do professor é derivada principalmente da turma atribuída. O desenho novo deve ser aditivo e preservar os vínculos existentes durante a migração.

## 3. Identidade e vínculo

### 3.1 Conta global

Criar uma identidade profissional global associada ao usuário de login. Dados globais:

- nome profissional;
- e-mail de login;
- telefone;
- foto;
- bio;
- modalidades/certificações informativas;
- status global: `ativa`, `suspensa` ou `bloqueada`.

O e-mail continua identificando a conta. Um convite para outra academia cria vínculo, não uma segunda conta.

### 3.2 Vínculo por academia

Cada vínculo contém:

- academia;
- cargo (`professor`, `gestor_modalidade`, `coordenador`);
- status (`convite_pendente`, `ativo`, `pausado`, `removido`, `recusado`);
- convidado por, aceito em e removido em;
- permissões concedidas;
- modalidades e turmas autorizadas.

O vínculo de uma academia não altera os vínculos das demais.

### 3.3 Contexto ativo

Após autenticar, o servidor retorna as academias disponíveis. Se houver mais de uma, o cliente exige uma academia ativa antes de abrir páginas operacionais. A troca de contexto deve emitir uma sessão/token contextualizado ou atualizar a sessão server-side de forma atômica.

Toda resposta operacional deve carregar `academia_id` e, quando útil, o nome da academia para facilitar diagnóstico de contexto.

## 4. Papéis e permissões

### Professor básico

Pode visualizar suas turmas e alunos relacionados, abrir chamada, validar presença, marcar ausência, acompanhar frequência, ver modalidade/faixa, inserir observação técnica e solicitar graduação.

Não pode editar preço, moeda, duração, pagamentos, dados financeiros, configurações globais, outros professores ou alunos fora do seu escopo.

### Gestor de modalidade

Além do básico, pode administrar turmas, horários, capacidade, reservas, filas e faixas das modalidades autorizadas. Pode consultar indicadores da modalidade e propor alterações de plano esportivo.

### Coordenador

Além do gestor, pode revisar chamadas, atribuir professores às turmas autorizadas, aprovar graduações, editar regras técnicas da modalidade e consultar relatórios completos da área.

### Dono e recepção

Continuam com seus poderes atuais. O dono concede e revoga vínculos e permissões. A recepção pode operar alunos e cobranças conforme as regras atuais, mas não ganha automaticamente poderes de segurança do vínculo profissional.

As permissões devem ser capacidades explícitas, por exemplo:

`alunos.ver`, `alunos.editar_tecnico`, `alunos.solicitar_cadastro`, `turmas.gerenciar`, `chamada.registrar`, `chamada.corrigir`, `faixas.gerenciar`, `graduacao.solicitar`, `graduacao.aprovar`, `relatorios.modalidade`, `planos.modalidades.sugerir`.

## 5. Impactos funcionais

### Cadastro e edição de professores

O dono poderá convidar um e-mail existente ou cadastrar um novo profissional. Se o e-mail já existir, o sistema reutiliza a conta e cria um vínculo pendente. O aceite ativa o vínculo. Remover um vínculo desativa o acesso àquela academia, mas não apaga a conta nem outros vínculos.

### Alunos

O professor só visualiza alunos vinculados às suas turmas/modalidades. Dados civis, contato principal, plano, pagamento, biometria e status financeiro continuam protegidos. Campos técnicos e observações só aparecem quando a permissão correspondente estiver ativa.

### Turmas e chamada

O servidor valida que a turma pertence à academia ativa, à modalidade autorizada e ao professor vinculado. Correções de chamada têm prazo e auditoria. Filas e reservas respeitam capacidade e regras atuais.

### Faixas e graduação

Faixas pertencem à modalidade e à academia. Uma graduação registra aluno, modalidade, faixa anterior, nova faixa, autor, aprovador, data, aulas válidas e observação. Graduação não é apagada: uma correção gera evento de reversão com justificativa.

### Planos

Separar dados comerciais de dados esportivos. Preço, moeda, duração, vencimento, limites e cobrança são administrativos. Modalidades, faixas e requisitos esportivos podem ser editados por gestores autorizados ou enviados como sugestão ao dono. Alterar plano comercial em uso exige confirmação administrativa e não pode quebrar assinaturas existentes.

### Interface

O cabeçalho deve mostrar academia ativa, cargo e indicador de permissões. Menus sem permissão ficam ocultos ou somente leitura; o backend continua sendo a autoridade. Ao trocar academia, limpar caches de listas, alunos, planos, turmas e relatórios antes de renderizar o novo contexto.

## 6. Persistência proposta

Adicionar, em migração aditiva:

### `profissionais`

`id`, `usuario_id`, `nome_profissional`, `telefone`, `bio`, `foto`, `ativo`, timestamps.

### `profissional_academias`

`id`, `profissional_id`, `academia_id`, `cargo`, `status`, `convidado_por`, `aceito_em`, `removido_em`, timestamps. Unicidade por profissional e academia.

### `profissional_permissoes`

Vínculo, capacidade, concedida por, data de concessão e status. Unicidade por vínculo e capacidade.

### `profissional_modalidades` e `profissional_turmas`

Tabelas de escopo para limitar o alcance de um gestor/coordenador. Devem ter chaves compostas ou validações que impeçam cruzamento de academias.

### `auditoria_lutas`

Academia, usuário, entidade, entidade_id, ação, JSON antes, JSON depois, motivo, timestamp e request_id opcional. A auditoria é append-only para o aplicativo.

### Compatibilidade

Remover a unicidade global atual de `professores.usuario_id` somente depois de migrar os vínculos existentes. Cada registro antigo de professor deve ganhar um vínculo profissional equivalente. Não apagar usuários, professores, graduações ou presenças.

## 7. Contratos de API esperados

Novos contratos deverão incluir, no mínimo:

- listar academias disponíveis para o profissional;
- selecionar/trocar academia ativa;
- consultar perfil global;
- listar, aceitar, recusar e revogar convites;
- listar permissões e escopos do contexto;
- conceder/revogar permissões pelo dono;
- solicitar edição de aluno ou plano quando não houver permissão direta;
- consultar auditoria conforme papel.

Rotas existentes de lutas devem passar por uma dependência única de contexto e autorização, sem confiar em `academia_id` fornecido pelo cliente.

## 8. Regras de segurança e privacidade

- Cada consulta deve filtrar por academia do contexto e validar escopo do profissional.
- IDs de outra academia devem responder como inexistentes, sem revelar existência.
- Troca de contexto deve invalidar ou substituir o contexto anterior.
- Convites devem expirar e ser de uso único.
- Suspender conta global encerra todos os contextos ativos; remover vínculo encerra somente aquela academia.
- Dados de saúde, biometria, documentos e pagamentos não entram em permissões técnicas padrão.
- Logs não devem registrar senha, token ou imagem facial.
- Graduação, chamada e alteração de plano devem ter trilha de auditoria.

## 9. Plano de testes de aceitação

### Identidade

1. Conta nova recebe convite de duas academias.
2. Aceita as duas e escolhe cada contexto.
3. Recusa uma e confirma que ela não aparece.
4. Vínculo removido deixa de autorizar chamadas naquela academia.

### Isolamento

1. Professor tenta consultar turma por ID de outra academia.
2. Professor tenta enviar `academia_id` diferente no corpo.
3. Professor troca o contexto e verifica que caches anteriores foram limpos.
4. Relatório não mistura alunos nem turmas.

### Permissões

1. Básico registra chamada, mas não altera faixa.
2. Gestor altera horário de modalidade autorizada, mas não preço.
3. Coordenador aprova graduação.
4. Dono concede e revoga capacidade; a mudança entra em vigor sem novo usuário.

### Dados de negócio

1. Plano com preço e modalidade funciona sem alteração comercial pelo professor.
2. Aluno elegível pode ser graduado.
3. Aluno sem modalidade no plano é bloqueado.
4. Correção de presença fora do prazo é rejeitada e auditada.

### Regressão

Executar a suíte atual do backend, testes de contrato, testes de autorização e testes responsivos das telas de login, seletor de academia, turmas, chamada, faixas e planos.

## 10. Fora do escopo inicial

- marketplace público de professores;
- agenda compartilhada entre academias;
- repasse financeiro automático ao professor;
- perfil público de professor;
- acesso do professor a múltiplas academias simultaneamente na mesma tela;
- edição de preços e cobranças sem aprovação administrativa.

## 11. Decisões pendentes para a implementação

- se o convite será enviado por e-mail, WhatsApp ou ambos;
- se o professor poderá solicitar cadastro de aluno ou apenas solicitar alteração;
- se `gestor_modalidade` e `coordenador` serão cargos fixos ou combinações de permissões;
- se a troca de academia exigirá senha novamente em dispositivos não reconhecidos.

