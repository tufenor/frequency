# Contribuindo com o Frequency

O Frequency é um sistema de gestão de academia em desenvolvimento. Sugestões de código são bem-vindas quando vêm acompanhadas de contexto, critério de aceite e uma forma segura de validar a mudança.

## Como propor uma ideia

Abra uma [issue de melhoria](../../issues/new?template=feature_request.yml) e informe o módulo: alunos, planos, acesso, relatórios, integrações, mobile ou infraestrutura. Explique o problema, o fluxo desejado e como saberemos que a solução funcionou.

Para defeitos, use o [modelo de bug](../../issues/new?template=bug_report.yml). Se você quiser implementar a ideia, aguarde a triagem e abra um pull request ligado à issue.

## Cuidados obrigatórios

- Use somente dados fictícios ou anonimizados nas issues, capturas e testes.
- Nunca publique `.env`, tokens, dumps, backups, dados de alunos, fotos, documentos ou credenciais.
- Mudanças em migrations precisam explicar compatibilidade, rollback e impacto em instalações existentes.
- Mudanças de cobrança, autenticação, biometria ou permissões precisam de testes e revisão extra.
- Não trate uma validação local como prova de deploy em produção.

## Pull requests

Inclua escopo, arquivos afetados, comandos de teste, limitações conhecidas e se a alteração exige migration ou configuração nova. Prefira mudanças pequenas e reversíveis.
