# Operação em produção com Docker

Esta configuração empacota o Frequency com PostgreSQL e Caddy. Ela não aplica migrations, não cria usuários e mantém sincronização, backup remoto e cobrança online desligados por padrão.

## Preparação

1. Instale Docker Engine e Docker Compose no servidor.
2. Copie `.env.production.example` para `.env.production` e troque `POSTGRES_PASSWORD`, `DB_PASSWORD` e `SECRET_KEY` por valores únicos. Os dois valores de senha do banco devem ser idênticos.
3. Aponte `FREQUENCY_DOMAIN` para o DNS público do servidor e mantenha as portas 80 e 443 disponíveis para o Caddy emitir e renovar HTTPS.
4. Antes de reutilizar um banco existente, faça backup e rode `backend/verificar_migracoes.py`. Um estado parcial é motivo para parar e revisar; nunca reaplique a migration parcial.

## Primeiro banco ou staging

Em um banco novo, aplique os arquivos oficiais de `backend/migrations` estritamente em ordem e pare no primeiro erro. Em banco existente, aplique somente a migration que a verificação apontar como totalmente ausente, depois de backup e ensaio em staging. A inicialização do compose não executa SQL justamente para preservar esse controle.

## Subida e verificação

Use `docker compose --env-file .env.production -f docker-compose.production.yml up -d --build`. Depois verifique o estado dos três serviços, o HTTPS do domínio, `/app`, `/docs` e o banco. Configure o backup criptografado apenas depois de informar destino, chave pública age e restaurar uma cópia em banco separado.

## Limites conhecidos

A configuração foi validada estaticamente neste checkout. Docker não está instalado no computador de desenvolvimento usado nesta revisão, portanto o build e a subida em contêiner ainda precisam de validação em staging antes de qualquer deploy ou piloto.