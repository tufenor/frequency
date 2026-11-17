# Frequency Local para Windows

## O que foi entregue

A homepage pública oferece o instalador **FrequencyLocalWindows.exe** e um pacote ZIP alternativo. O instalador prepara uma instância isolada no computador da academia, em `%LOCALAPPDATA%\Frequency\local`, e cria o atalho `Frequency Local` na área de trabalho.

## Primeiro uso

1. Baixe o instalador na homepage e execute-o.
2. O instalador verifica Windows, Python e PostgreSQL. Se algum componente faltar, ele informa o que instalar.
3. Informe a senha do usuário local `postgres`. A senha é usada somente para preparar o banco no próprio computador.
4. O instalador cria o banco `frequency_local`, aplica as migrações oficiais e prepara um ambiente Python separado.
5. Abra o atalho `Frequency Local`. A aplicação fica em `http://127.0.0.1:8000/app`.

## Limites da versão inicial

- Ela é uma instalação local real, mas ainda exige PostgreSQL instalado no Windows. O pacote não instala o servidor de banco silenciosamente nem altera o banco online.
- A sincronização com a nuvem começa desligada. Isso evita misturar dados de academias diferentes antes da configuração e validação do vínculo da academia.
- A rotina de migração é deliberadamente explícita e aborta se alguma migração falhar; não apaga dados existentes.
- O instalador cria a base técnica. O primeiro dono da academia ainda deve ser criado pelo fluxo de cadastro do Frequency.

## Arquivos publicados

- `frontend/public/downloads/FrequencyLocalWindows.exe`: instalador autoextraível para Windows.
- `frontend/public/downloads/FrequencyLocalWindows.zip`: alternativa para ambientes que bloqueiam executáveis autoextraíveis.
- `installer/windows/install.ps1`: verificação de pré-requisitos, criação da base local e atalho.
