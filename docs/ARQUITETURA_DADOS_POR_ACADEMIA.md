# Dados por academia e operação local

## Decisão do produto

Cada academia terá uma instalação própria do Frequency e um banco de dados próprio. Alunos, fotos, planos, pagamentos, presenças, chaves de monitor e configurações ficam no computador ou mini-PC da própria academia. O serviço online do Frequency não será usado como banco operacional.

```text
Computadores da academia ── rede local ──> Frequency Local + PostgreSQL local
                                                │
                                                ├─ catraca e monitores
                                                ├─ alunos, fotos e pagamentos
                                                └─ backup cifrado escolhido pela academia

Frequency Cloud ── somente licença, atualização e suporte (sem dados operacionais)
```

## O que isso garante

- A queda da internet não interrompe cadastro, consulta ou decisão de entrada quando a rede local e o computador servidor continuam ligados.
- Os dados de uma academia não são consultados por outra.
- Fotos faciais e documentos permanecem no ambiente da academia.
- O dono escolhe a pasta local e o destino de backup; o Frequency não publica uma cópia operacional por padrão.

## Estado atual e limite de segurança

O aplicativo publicado hoje ainda usa um PostgreSQL central multiacademia para autenticação e operação. O isolamento por `academia_id` protege os registros entre academias, mas isso não é o mesmo que um banco físico por academia. A fila de sincronização e o receptor remoto permanecem desativados no servidor (`SYNC_OUTBOX_ENABLED=NO`, `SYNC_WORKER_ENABLED=NO`, `SYNC_RECEIVER_ENABLED=NO`); isso evita uma réplica automática, mas não transforma o banco central em banco local.

Não devemos declarar que a política de dados por academia está concluída antes de entregar o instalador local e migrar cada academia para uma base própria. A migração precisa preservar registros, testar restauração e revogar as credenciais da cópia central depois da validação.

## Entrega necessária para concluir

1. Criar o serviço local Frequency para Windows, macOS e Linux com PostgreSQL local inicializado automaticamente.
2. Provisionar uma base vazia por academia e importar somente o backup autorizado pelo dono.
3. Mover autenticação operacional, monitores, catracas e reconhecimento facial para o serviço local.
4. Manter no servidor apenas identificador da instalação, estado da licença, versão disponível e telemetria mínima sem dados pessoais.
5. Criar backup cifrado local e restauração guiada; o dono escolhe Google Drive, pasta de rede ou outro destino.
6. Testar desligamento, perda de internet, reinício, atualização e restauração antes de ativar a academia.
7. Excluir ou anonimizar os registros operacionais da instalação central após a migração confirmada.

## Decisões que permanecem abertas

- O computador servidor da academia deve ficar ligado para que outros dispositivos usem a rede local.
- Acesso remoto ao dono será por túnel seguro ou réplica somente leitura aprovada pelo dono; não abriremos o PostgreSQL na internet.
- Pagamentos online, quando existirem, retornarão apenas um evento de confirmação para a instalação local, sem copiar o cadastro completo.
- O relógio local, a validade da assinatura e a política de acesso durante uma queda prolongada precisam ser definidos antes do piloto.
