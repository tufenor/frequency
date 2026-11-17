# Validação futura da sincronização

Este é um roteiro de staging para a proposta local → nuvem. **Não ative os sinalizadores no ambiente em uso.** A migração `003_sync_outbox.sql` foi aplicada numa instância PostgreSQL descartável e o fluxo foi exercitado em processo local com dados sintéticos. Não foi configurado servidor de hospedagem, não foi conectada a base da academia e nenhum dado real foi enviado. A validação de TLS com certificado e o teste de reinício do serviço continuam pendentes.

## O que o código faz

- A instalação local continua sendo a única origem de alterações operacionais.
- A fila local recebe eventos na mesma transação da alteração e atribui uma revisão crescente por academia.
- `criar_snapshot_sync.py` prepara uma única carga inicial dos registros já existentes. O snapshot só grava na fila local.
- `sync_worker.py` envia uma revisão por vez ao endereço HTTPS configurado; mantém a revisão pendente quando há falha e repete com espera crescente.
- `/sync/receber` autentica a origem por uma chave aleatória exclusiva, valida tamanho e campos e recusa revisões fora de ordem ou já aplicadas.
- O modo `SYNC_MIRROR_READ_ONLY=YES` bloqueia gravações feitas pela API da cópia na nuvem e a interface mostra o aviso “Consulta na nuvem”.

O resumo local fica em `GET /sync/estado-local`. Mostra fila, snapshot, última confirmação, erro do evento mais antigo e horário da próxima tentativa. Ainda não existe indicador de sincronização no painel.

## Evidência de validação isolada

- A suíte atual percorre as migrações 001–007 numa base temporária. QR, moeda, fotografia e configuração do monitor são dados locais e não fazem parte da projeção de eventos enviada à nuvem.
- Um cliente ASGI em memória confirmou autenticação do receptor, aplicação de plano/aluno/pagamento/presença, idempotência, rejeição de credencial/origem/revisão inválidas e recusa de HTTP sem TLS.
- O modo somente consulta negou as nove rotas de gravação cobertas na matriz.
- O trabalhador local enviou e confirmou eventos com transporte simulado, reteve a ordem após falha de rede e retomou após a retentativa.
- O snapshot sintético respeitou a ordem das entidades e omitiu campos pessoais não necessários. O endpoint de recebimento recusou uma origem HTTP.

Isso confirma a lógica local com dados fictícios; não comprova acesso HTTPS a uma nuvem, segurança do proxy, recuperação após reinício, instalação como serviço, restauração de backup ou adequação para dados de clientes.

## Ordem exigida em staging

1. Criar uma base descartável e um servidor de staging distintos dos dados da academia. Fazer um backup e confirmar que ele pode ser restaurado antes de começar.
2. Aplicar as migrações 001 a 007 somente nessa base descartável. Conferir o esquema e os vínculos gerados; não experimentar diretamente na base de demonstração ou de cliente.
3. Cadastrar previamente a academia de destino e as contas que poderão entrar no painel da nuvem. A rota de recebimento só mapeia os eventos para uma academia existente.
4. Configurar HTTPS válido no servidor. Depois, em seu arquivo de ambiente protegido, habilitar `SYNC_RECEIVER_ENABLED=YES` e `SYNC_MIRROR_READ_ONLY=YES`. As contas da nuvem devem ser preparadas antes de ativar o modo somente leitura, pois ele bloqueia as rotas de escrita da API.
5. Na origem descartável, habilitar `SYNC_OUTBOX_ENABLED=YES`, manter o trabalhador parado e consultar `/sync/estado-local` com a conta do dono para obter o UUID da academia local.
6. No servidor HTTPS, executar `python .\provisionar_sync_cloud.py <id_numerico_da_academia_de_destino> <uuid_local>`. Copiar a chave mostrada diretamente para o arquivo protegido da origem. Ela é mostrada uma vez; não deve ser enviada por chat, capturada em imagem ou colocada no Git.
7. Na origem descartável, enfileirar o snapshot uma única vez, com `python .\criar_snapshot_sync.py <id_numerico_da_academia_local>`. Conferir `/sync/estado-local` e garantir que o contador do snapshot existe antes de iniciar o envio.
8. Configurar na origem `SYNC_WORKER_ENABLED=YES`, `SYNC_LOCAL_ACADEMY_ID=<id_numerico_local>`, `SYNC_REMOTE_URL=https://<dominio>/sync/receber` e `SYNC_REMOTE_TOKEN=<chave>`. Iniciar manualmente `python .\sync_worker.py` em staging; não o instalar como serviço Windows ainda.
9. Conferir dados fictícios na cópia de consulta, testar queda de conexão, repetição, evento fora de ordem, chave errada, reinício do processo e restauração do banco. Verificar que uma repetição não duplica registros e que uma falha não libera revisões posteriores.
10. Guardar resultados, corrigir defeitos e repetir a validação. Só depois decidir retenção e privacidade, criar procedimento de rotação da chave e planejar instalação do serviço.

## Variáveis de ambiente

Todas as opções de sincronização permanecem `NO` no `.env.example`.

| Instalação | Variáveis necessárias quando staging for autorizado |
|---|---|
| Servidor de consulta | `SYNC_RECEIVER_ENABLED=YES`, `SYNC_MIRROR_READ_ONLY=YES` |
| Origem local | `SYNC_OUTBOX_ENABLED=YES`, `SYNC_WORKER_ENABLED=YES`, `SYNC_LOCAL_ACADEMY_ID`, `SYNC_REMOTE_URL`, `SYNC_REMOTE_TOKEN` |
| Origem local, opcional | `SYNC_WORKER_POLL_SECONDS` (2 a 60 segundos; padrão 10) |

Não use `SYNC_RECEIVER_ALLOW_HTTP_STAGING` na internet. Em produção, o receptor aceita apenas HTTPS. A configuração do proxy que termina TLS precisa fazer o servidor reconhecer corretamente a conexão HTTPS externa.

## Limites que continuam pendentes

- O fluxo só replica para a nuvem; não permite editar os mesmos dados nos dois lados.
- Não há eventos de exclusão, nem suporte a conflitos entre duas fontes. A fila bloqueia revisões posteriores até resolver o primeiro evento com falha.
- A projeção contém nomes e informações operacionais de mensalidades e presença. Ela omite documento, telefone, data de nascimento, identificador biométrico, credenciais e chaves da catraca, mas ainda exige decisão de privacidade, acesso e retenção antes do envio real.
- O servidor e a base de consulta ainda precisam de backup próprio; a fila sincronizada não substitui uma cópia de recuperação.
- Migrações, protocolo, política offline, integração física da catraca, instalador e serviço automático ainda precisam de validação antes de qualquer cliente.
