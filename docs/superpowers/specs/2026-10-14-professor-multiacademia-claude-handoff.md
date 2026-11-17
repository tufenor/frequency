# Orientação para o Claude — Professor profissional multiacademia

## Mensagem de trabalho

Você está trabalhando no repositório Frequency Gym em `C:\Users\tufen\Documents\frequency`.

Leia primeiro, nesta ordem:

1. `AGENTS.md`;
2. `docs/superpowers/specs/2026-10-14-professor-multiacademia-design.md`;
3. `docs/GATE_PRE_DEPLOY.md` apenas para conhecer os portões; esta tarefa não autoriza deploy;
4. o estado atual do Git, migrações, autenticação, autorização, módulo de lutas e telas relacionadas.

O arquivo de especificação é a fonte funcional desta tarefa. Não invente recursos, não remova dados e não sobrescreva alterações existentes. Antes de editar, registre branch, `git status`, arquivos modificados e testes disponíveis.

## Regra de aprovação

Antes de escrever código, apresente um plano técnico curto com:

- arquivos que serão alterados;
- migração aditiva prevista;
- estratégia de compatibilidade com `usuarios.academia_id` e `professores.usuario_id`;
- endpoints e dependências de autorização;
- telas afetadas;
- testes por etapa;
- riscos e rollback.

Espere aprovação explícita do responsável pela especificação. Se a aprovação já tiver sido registrada no chat, confirme isso no relatório e ainda assim pare se surgir uma decisão pendente da seção 11 da especificação.

## Ordem de implementação após aprovação

### Fase 1 — persistência e compatibilidade

- Criar migração aditiva para `profissionais`, `profissional_academias`, `profissional_permissoes`, `profissional_modalidades`, `profissional_turmas` e `auditoria_lutas`.
- Migrar os professores existentes para um profissional e um vínculo equivalente sem apagar registros.
- Só remover a unicidade global de `professores.usuario_id` depois de validar a migração e manter compatibilidade de leitura.
- Não executar migração em banco de produção sem autorização separada.

### Fase 2 — contexto e autorização

- Criar serviço único de contexto profissional: listar academias, selecionar academia e invalidar o contexto anterior.
- Nunca confiar em `academia_id` enviado pelo cliente; derivar academia e escopo do token/sessão.
- Fazer IDs de outra academia responderem como inexistentes.
- Centralizar capacidades como `alunos.ver`, `alunos.editar_tecnico`, `turmas.gerenciar`, `chamada.registrar`, `chamada.corrigir`, `faixas.gerenciar`, `graduacao.solicitar`, `graduacao.aprovar`, `relatorios.modalidade` e `planos.modalidades.sugerir`.

### Fase 3 — API e regras de negócio

- Implementar perfil global, convites, aceite/recusa/revogação, permissões, escopos e auditoria.
- Adaptar as rotas existentes de lutas, alunos, turmas, chamada, faixas, graduação e planos à dependência de contexto.
- Separar dados comerciais de dados esportivos: professor não recebe preço, cobrança, moeda ou dados financeiros por padrão.
- Graduação, correção de chamada e mudança sensível devem ser auditáveis e não destrutivas.

### Fase 4 — interface

- Adicionar seletor de academia, cargo e indicador de permissões.
- Limpar caches de alunos, turmas, planos e relatórios ao trocar de academia.
- Ocultar ações sem permissão, mantendo o backend como autoridade.
- Preservar comportamento responsivo em celular, tablet/iPad, notebook e desktop.

### Fase 5 — testes

Cobrir, no mínimo:

- login único com duas academias e troca de contexto;
- convite aceito, recusado, expirado e revogado;
- isolamento por academia e por modalidade/turma;
- permissões de professor básico, gestor e coordenador;
- proteção de dados civis, financeiros, biométricos e de saúde;
- chamada, correção, faixas, graduação e planos;
- regressão das rotas atuais e testes responsivos das telas afetadas.

Execute testes pequenos após cada fase e a suíte completa ao final. Se algum teste falhar, pare, preserve o estado e relate o erro; não force o código nem altere banco real para fazer o teste passar.

## Restrições obrigatórias

- Backend, frontend e banco devem continuar compatíveis com os fluxos existentes de dono, recepção e aluno.
- Não publicar, não fazer deploy, não aplicar migrations em produção e não criar contas externas nesta tarefa.
- Não expor senhas, tokens, chaves, dados de alunos ou imagens faciais nos logs.
- Não apagar arquivos, dados, usuários, professores, graduações ou presenças.
- Não afirmar conclusão sem mostrar arquivos alterados, testes executados, resultado, riscos e pendências.

## Entrega esperada

Ao concluir uma fase, informe:

1. o que foi alterado;
2. testes executados e saída resumida;
3. decisões tomadas;
4. riscos ou bloqueios;
5. próximo passo recomendado.

Ao final, entregue também uma matriz de permissões e um roteiro manual para validar duas academias com o mesmo login.
