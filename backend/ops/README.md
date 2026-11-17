# Rotina de backup do PostgreSQL

O script `backup_postgres.py` gera um dump customizado do PostgreSQL, envia o fluxo diretamente ao `age` para que o dump em texto claro não seja gravado em disco e envia o arquivo criptografado para um bucket S3 ou compatível. Se o envio falhar, mantém o arquivo criptografado na pasta local para tentar novamente na próxima execução. AWS CLI v2 solicita validação SHA-256 durante o envio. Depois, o script lê o checksum armazenado por `HeadObject` com `--checksum-mode ENABLED` e confere também tamanho e digest completo guardado como metadado. Para upload multipart, o S3 pode devolver SHA-256 composto por partes; nesse caso o S3 validou as partes durante o upload, e o script valida o tipo/formato do checksum armazenado sem compará-lo incorretamente ao SHA-256 simples do arquivo. Consulte a documentação oficial da AWS sobre [verificação de checksum no AWS CLI](https://docs.aws.amazon.com/cli/latest/topic/s3-faq.html), [integridade de uploads](https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity-upload.html) e [HeadObject](https://docs.aws.amazon.com/AmazonS3/latest/API/API_HeadObject.html).

## Estado e segurança

- O script vem **desativado**. Só executa o dump com `BACKUP_ENABLE=YES`.
- Não foi executado contra o banco de demonstração nem contra banco de cliente.
- Nenhuma chave, bucket ou servidor foi configurado.
- A chave pública `age` fica no servidor; a chave privada de restauração deve ser gerada e guardada fora dele, em local seguro. Sem ela não será possível recuperar o backup.
- AWS CLI deve usar credenciais protegidas da conta de serviço, com permissão mínima para gravar objetos, ler o checksum em `HeadObject`, listar e remover backups vencidos; quando o provedor suportar, prefira identidade de máquina a chave estática. Para bucket S3 geral com SSE-KMS, a consulta do checksum exige a permissão KMS correspondente (por exemplo, `kms:Decrypt`). Não coloque credenciais no código, em argumentos da linha de comando ou no Git.
- Use para `DB_USER` uma conta PostgreSQL de backup com acesso de leitura ao banco; não use o superusuário `postgres` em produção.
- A retenção remota precisa ser escolhida em `BACKUP_REMOTE_RETENTION_DAYS` antes de ativar. O valor de 30 dias é uma sugestão inicial para o piloto, ainda sujeita à decisão do responsável; o script não assume um prazo silenciosamente.
- A rotina remove somente backups antigos que tenham o nome esperado e estejam dentro do diretório da unidade configurada. Ela mantém ao menos o backup remoto mais recente daquela unidade.
- O bucket deve estar com versionamento desativado. A rotina confere essa condição antes de apagar ou enviar; com versionamento ligado, uma exclusão simples pode apenas criar um marcador e manter versões antigas ocupando espaço. Consulte a [documentação do Lightsail sobre versionamento](https://docs.aws.amazon.com/lightsail/latest/userguide/buckets-in-amazon-lightsail.html) e o comportamento de [exclusão no S3](https://docs.aws.amazon.com/AmazonS3/latest/API/API_DeleteObject.html).
- `BACKUP_S3_MAX_GB` limita o tamanho combinado dos objetos encontrados no prefixo configurado (padrão: 90 GB decimais). Use um bucket/prefixo dedicado ao Frequency. Se atingir o limite, o envio falha com aviso e os arquivos criptografados continuam na máquina para nova tentativa.
- Cópias ainda não enviadas nunca são removidas automaticamente. Cópias enviadas ficam localmente pelo número de dias definido em `BACKUP_LOCAL_RETENTION_DAYS` (padrão: 7), e só depois são removidas.

## Pré-requisitos do servidor

Instale e configure os programas oficiais `pg_dump`, `age` e AWS CLI v2, além das dependências Python do backend. Para S3 compatível, confirme antes que o endpoint aceita `PutObject` com checksum SHA-256, `HeadObject` com checksum habilitado, metadado e verificação de tamanho. Um destino incompatível deve deixar o backup criptografado local e sinalizar falha, sem ser marcado como enviado.

Para gerar a chave de restauração, execute `age-keygen` numa máquina administrativa segura, fora do servidor. Guarde a identidade privada fora do computador da academia e fora do servidor de produção; copie somente a chave pública para a configuração do backend. Não envie nenhuma das chaves por chat.

## Configuração

Adicione as variáveis abaixo ao arquivo local `backend/.env` ou às variáveis protegidas do serviço. Preencha os valores no computador de implantação; não os cole em mensagens. O arquivo `.env` existente não deve ser substituído. A unidade systemd exige `/etc/frequency/backup.env`; crie esse arquivo apenas quando decidir ativar o serviço, proteja-o para leitura pelo usuário do serviço e coloque nele `BACKUP_ENABLE=YES` junto das configurações necessárias. Sem esse arquivo, o serviço não inicia.

```dotenv
BACKUP_ENABLE=YES
BACKUP_LOCAL_DIR=C:/ProgramData/Frequency/backups
BACKUP_LOCAL_RETENTION_DAYS=7
BACKUP_REMOTE_RETENTION_DAYS=30
BACKUP_S3_MAX_GB=90
BACKUP_STORAGE_PROVIDER=s3
BACKUP_NODE_ID=unidade-principal
BACKUP_AGE_RECIPIENT=age1...chave_publica...
BACKUP_S3_BUCKET=nome-do-bucket
BACKUP_S3_PREFIX=frequency/backups
AWS_REGION=sa-east-1
# Para bucket do Lightsail, use BACKUP_STORAGE_PROVIDER=lightsail.
# Opcional para serviço S3 compatível:
# BACKUP_S3_ENDPOINT_URL=https://endpoint-do-provedor
```

As variáveis `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` e `DB_PASSWORD` já usadas pelo backend serão lidas sem imprimir seus valores. `BACKUP_REMOTE_RETENTION_DAYS` é obrigatório e o exemplo de 30 dias precisa ser confirmado pelo responsável antes de ativar. Use `BACKUP_STORAGE_PROVIDER=lightsail` para buckets Lightsail; para outros destinos S3 compatíveis, deixe `s3` e confirme que o serviço implementa as operações usadas. Se necessário, `DB_SSLMODE`, `PG_DUMP_BIN`, `AGE_BIN` e `AWS_BIN` podem apontar para a configuração/instalação correta. A identidade do serviço também precisa de permissão para consultar o estado de versionamento (Lightsail `GetBuckets` ou S3 `GetBucketVersioning`), listar objetos, enviar, conferir e remover os backups vencidos; não conceda acesso administrativo amplo ao bucket.

## Agendamento e retenção

Foram adicionados `frequency-backup.service` e `frequency-backup.timer` para um servidor Linux. O timer executa diariamente às 03:30 UTC (23:30 no horário de Manaus) e, após uma reinicialização que perdeu a hora marcada, tenta recuperar a execução. A unidade roda com o usuário sem privilégios `frequency`, protege o sistema contra gravação e só permite gravação em `/var/lib/frequency/backups`.

Esses arquivos ainda não estão instalados em servidor algum. Antes de ativar, ajuste os caminhos para a instalação real, crie o usuário de serviço e pasta de backup, confirme acesso de leitura ao `.env` do backend, configure o cliente PostgreSQL/AWS CLI/age e confirme que o bucket permite listar, enviar, conferir e remover objetos vencidos. A unidade não contém `BACKUP_ENABLE=YES`: ela exige `/etc/frequency/backup.env`, configurado deliberadamente pelo responsável. No Windows local, configure uma tarefa equivalente no Agendador de Tarefas; o instalador futuro deverá fazer essa configuração sem pedir que o dono abra um terminal.

O serviço executa `python -m ops.backup_postgres` com a conta que acessa o PostgreSQL e o bucket. Uma falha gera código de saída diferente de zero e precisa produzir alerta para o responsável. O agendador não deve iniciar uma segunda execução enquanto a anterior estiver ativa.

O script aplica a retenção diária definida em `BACKUP_REMOTE_RETENTION_DAYS`; cópias mensais de longo prazo ainda não são geradas. Os 30 dias do exemplo são uma sugestão para discussão, não uma decisão já aprovada. Backups reais só serão considerados prontos depois de restaurar um deles em outro banco e conferir que a aplicação consegue abrir os dados recuperados.

O script não cria servidores, buckets, chaves ou tarefas agendadas automaticamente.

## Estado exibido no painel

Cada execução escreve atomicamente um arquivo pequeno em
`BACKUP_STATUS_FILE` (por padrão `.backups/frequency-backup-status.json`). Ele
contém somente o resultado, a hora, a quantidade enviada e a quantidade
pendente; não contém senha, token, caminho de banco ou conteúdo do dump. Em
caso de falha, os arquivos criptografados continuam no diretório local para a
próxima tentativa. O endpoint autenticado `/operacao/status` usa esse arquivo
para o administrador e o dono da academia. Ausência do arquivo aparece como
`nunca_executado`, nunca como sucesso.

## Início local no Windows

`local_server.py` é o iniciador que será usado pelo futuro instalador/atalho.
Ele não aplica migrações nem cria contas: verifica a chave da instalação, as
quatro páginas do frontend, a conexão com o PostgreSQL e se as migrações estão
completas. Se algo faltar, encerra com uma mensagem segura e não inicia uma
API parcialmente configurada.

No diretório `backend`, depois de configurar `.env` e aplicar as migrações
em ordem, a verificação é:

```powershell
python -m ops.local_server --check
```

Para iniciar o serviço local:

```powershell
python -m ops.local_server
```

O comando ainda é uma etapa de homologação; não instala PostgreSQL, não cria
um serviço do Windows e não configura um servidor externo automaticamente.
O instalador final precisa incluir PostgreSQL, inicialização automática,
atualização/rollback e uma tarefa diária de backup, todos testados em uma
máquina limpa antes do primeiro cliente.
