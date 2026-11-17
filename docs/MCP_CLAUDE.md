# Integração MCP com Claude

O arquivo `.mcp.json` na raiz registra o servidor `frequency-local`. Ele usa o
Python da venv do backend e o transporte padrão `stdio`, portanto não abre
nenhuma porta de rede.

## Ferramentas expostas

- `frequency_status`: lê README, status do projeto, contrato da API e arquitetura.
- `frequency_pending_tasks`: lista pendências explícitas do status do projeto.
- `frequency_manager_commands`: lê as instruções de coordenação aprovadas.
- `frequency_run_tests`: executa `python -m unittest discover -s backend/tests -v` usando a venv local.

O servidor não expõe senhas, tokens, cookies, banco remoto, deploy, migrações
reais, exclusões ou envio de mensagens. Para carregar a configuração, abra o
projeto no Claude Code/Desktop e recarregue os servidores MCP do projeto. A
confirmação deve aparecer na lista de ferramentas como `frequency-local`.

## Validação local

O protocolo MCP foi validado com `initialize` e `tools/list`. Se o Claude não
mostrar o servidor, reinicie a sessão do projeto e confirme que o caminho do
Python e do arquivo ainda existem neste computador.
