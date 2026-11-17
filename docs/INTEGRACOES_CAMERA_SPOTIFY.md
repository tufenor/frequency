# Câmeras e Spotify — etapa local

Implementado em 29/09/2026, acessível pelo menu do dono ou `/integracoes`.

## Câmeras

1. Entre no Frequency como dono com assinatura liberada.
2. Abra **Câmeras de segurança**, informe nome, formato e endereço de transmissão.
3. Clique em **Adicionar câmera** e depois em **Conectar**.

Até oito endereços ficam neste navegador, separados pelo ID da academia e do usuário. Não são sincronizados nem gravados no banco. Computadores compartilhados exigem um perfil de navegador protegido: armazenamento local não é um cofre nem uma permissão do equipamento. A própria câmera deve controlar o acesso à transmissão.

Suporte inicial: MJPEG e vídeo reproduzível nativamente pelo navegador. HLS depende do navegador; RTSP/ONVIF exigem uma ponte local ainda não fornecida pelo Frequency. O técnico deve fornecer a URL correta e configurar rede/acesso; não há descoberta automática. URLs com usuário, senha, query string ou fragmento são recusadas para evitar persistir credenciais. Em HTTPS, somente câmeras HTTPS. Regras de acesso à rede local do navegador também podem exigir autorização.

Transmissões começam somente ao clicar em Conectar e param ao ocultar/sair da página, remover a câmera ou desconectar. Não há gravação, proxy no servidor, reconhecimento facial nem envio de imagens para serviços externos. Uma resposta MJPEG contínua pode não emitir evento de carregamento; a interface orienta conferir a imagem sem alegar conexão confirmada.

## Spotify

O serviço comum é de uso pessoal e não autoriza sonorização comercial da academia. Para esse uso é necessário escolher um serviço licenciado para empresas. Esta implementação é controle de sessão pessoal, não uma licença comercial.

1. Configure um aplicativo no Spotify for Developers e cadastre exatamente o endereço de retorno mostrado em **Configurar conexão**. Use HTTPS ou HTTP no loopback `127.0.0.1`; `localhost` e IP de LAN via HTTP não são aceitos pelo fluxo.
2. Informe o Client ID público e clique em **Conectar Spotify**. Não é usado Client Secret.
3. Autorize a conta elegível no Spotify. Limites de desenvolvimento e acesso ao aplicativo são definidos pelo Spotify.
4. Abra o Spotify em um dispositivo e inicie uma música. No Frequency, use **Atualizar**, escolha o dispositivo e controle reprodução, pausa, anterior, próxima e volume.

Os controles de reprodução exigem Premium. OAuth usa PKCE S256, state aleatório, vínculo à conta Frequency e prazo de dez minutos para o retorno. Tokens ficam no sessionStorage desta aba, com renovação quando necessário, e são removidos no logout do Frequency ou ao desconectar. Desconectar localmente não revoga a autorização na conta Spotify nem pausa a reprodução. Não há consultas periódicas ao Spotify; o usuário atualiza manualmente, e a resposta 429 impõe espera.

## Validação e limites

- Seis testes locais cobrem endereços inválidos, credenciais, conteúdo misto e retorno OAuth com conta/state/prazo incorretos ou cancelamento.
- Sintaxe Python e JavaScript conferida.
- Sem alteração de `.env`, dados reais ou migração de banco.
- Falta homologar câmera real, conta Spotify autorizada e navegador/rede do cliente. Não marcar esses testes como concluídos sem os equipamentos e credenciais.
- A nova página está em português; tradução para os outros idiomas permanece pendente.

Teste: `node --test frontend/tests/integracoes.test.mjs`.

Referências oficiais:
- https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow
- https://developer.spotify.com/documentation/web-api/reference/start-a-users-playback
- https://support.spotify.com/us/article/spotify-public-commercial-use/
