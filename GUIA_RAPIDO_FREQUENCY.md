# Guia provisório de uso do Frequency

## Notificações faciais no painel — 01/10/2026

O painel /app exibe até oito acessos faciais novos na lateral, com Liberado/Bloqueado, nome, ícone e data/hora no idioma selecionado. O clique abre Alunos e o formulário existente quando há aluno identificado, respeitando as permissões de gravação. Eventos sem identificação são registrados sem aluno e não têm ação de perfil. A consulta incremental de /presencas usa o último ID, aproximadamente a cada 2,5 segundos; a abertura estabelece a linha de base sem mostrar histórico como novidade. Logout cancela a atualização e limpa a lista. O contador representa os cartões presentes. Erros de imagem ou motor facial continuam sendo erros, sem registro de acesso.

Deploy verificado em 01/10/2026 no local (porta 8000) e em https://frequencygym.tech/app. No VPS Hostinger, aplicação Docker reconstruída e reiniciada, HTTPS 200, painel/arquivos estáticos e cursor depois confirmados; PostgreSQL saudável. Alterações anteriores da versão web foram preservadas por combinação dos cinco arquivos da funcionalidade. Cópia de recuperação: /opt/frequency-deploy-backups/facial-20261001-1790876713/files.tar.gz; imagem anterior: frequency-app:before-facial-20261001. Serviços usam restart unless-stopped. Com o PC desligado, o local para e o VPS continua. Backup periódico estava desativado no compose; restauração e teste visual com câmera real continuam pendentes, portanto o deploy não significa homologação completa de produção.

**Situação:** rascunho interno, baseado na versão local conferida em 28/09/2026. Ainda não entregar este guia como instrução final ao cliente: endereço público, regras comerciais, catraca física e contingência precisam ser definidos.

## 1. Entrar no sistema

1. Abra o endereço que o responsável da academia fornecer. Durante o desenvolvimento, `http://127.0.0.1:8000/app` só abre no computador onde a API local está rodando; não é o endereço para os funcionários do cliente.
2. Informe o e-mail e a senha da sua própria conta.
3. Se aparecer “E-mail ou senha incorretos”, confira o e-mail e tente novamente. Se não lembrar a senha, peça ajuda ao responsável da academia; não envie sua senha pelo chat.
4. Quando terminar, use **Sair** no canto superior direito.

As contas de dono e recepção são individuais. O sistema encerra a sessão quando o token expira; a validade atual é de até oito horas. Nesse caso, entre novamente.

## 2. O que cada perfil pode fazer

**Dono da academia** pode consultar as telas diárias, cadastrar e ativar ou desativar alunos, criar planos, consultar pagamentos, registrar recebimentos e criar ou suspender contas da recepção.

**Recepção** pode consultar a visão geral, alunos, planos, pagamentos e histórico de acessos; pode cadastrar aluno e registrar pagamento. Não administra a equipe, não cria planos e não ativa ou desativa alunos.

Cada conta vê os dados da própria academia. Se uma opção não aparecer no menu, peça ao dono para confirmar se sua conta tem o perfil correto.

## 3. Consultar a visão geral

1. Abra **Visão geral**.
2. Confira as quantidades de alunos cadastrados, ativos e com alerta.
3. Consulte a tabela de situação para identificar quem está em dia ou perto do vencimento.
4. Use **Atualizar** para buscar os dados mais recentes.

O alerta é um resumo; para conferir uma cobrança específica, abra **Pagamentos**.

## 4. Cadastrar e localizar um aluno

1. Abra **Alunos** e escolha **Novo aluno**.
2. Preencha **Nome** e **Documento**, que são obrigatórios.
3. Se necessário, informe telefone, data de nascimento e identificador numérico da biometria usado pelo equipamento compatível.
4. Selecione um plano quando houver um plano contratado. Sem plano, deixe **Plano** em “Sem plano”.
5. Escolha **Salvar aluno**. A mensagem na tela confirma se o cadastro foi feito.
6. Para localizar alguém, use **Buscar por nome ou documento**. Apague o texto da busca para voltar à lista completa.
7. Use **Pagamentos** na linha do aluno para consultar suas cobranças.
8. Para corrigir o documento, telefone ou data de nascimento, escolha **Editar** na linha, altere os campos e salve. Telefone e nascimento podem ser apagados. Nome, plano, cobranças e identificador biométrico não são alterados por esse formulário.
9. A foto é opcional. Só selecione/capture uma imagem após informar à pessoa e receber sua autorização. A foto fica na instalação local e pode ser removida pelo dono; defina a retenção antes de cadastrar pessoas reais.

O sistema não deve receber imagens ou modelos de biometria por esse campo; ele é um identificador numérico. O que o leitor físico armazena ainda precisa ser confirmado com o fabricante.

Ao cadastrar aluno com plano, o sistema abre a cobrança inicial pelo valor desse plano. Sem plano, o cadastro é permitido, mas a regra de acesso da API bloqueia a entrada até haver plano e cobrança em aberto. A regra comercial da próxima data de vencimento ainda precisa ser confirmada com o cliente antes do piloto.

O dono pode usar **Ativar** ou **Desativar** na linha do aluno. A recepção não recebe esses controles.
O dono e a recepção podem editar os dados pessoais permitidos. A cópia de consulta na nuvem não permite abrir nem salvar esse formulário.

## 5. Consultar planos

1. Abra **Planos**.
2. Confira o nome, o valor e a duração em dias.
3. Somente o dono pode criar um plano. A recepção pode consultar os planos disponíveis, mas não vê o formulário de criação.

Antes do piloto, o dono deve confirmar os valores e a duração que serão usados na academia.

## 6. Consultar e registrar pagamentos

1. Abra **Pagamentos**.
2. Use os filtros para ver todos os alunos ou apenas um, e para mostrar cobranças em aberto, atrasadas ou pagas.
3. Confira aluno, vencimento, valor e situação de cada cobrança.
4. O dono pode adicionar, substituir ou remover a imagem do QR usado pela academia. A migração 004 precisa estar aplicada para esse recurso funcionar.
5. Quando o pagamento tiver sido realmente recebido, escolha **Registrar pagamento** e confirme a ação. Exibir o QR não confirma a transferência; até a integração bancária existir, a equipe verifica o recebimento e registra a baixa manual.
6. Confira a mensagem de sucesso e a situação atualizada.

O sistema cria a próxima cobrança quando registra um pagamento de aluno com plano. Atualmente, o cálculo usa como início o que for posterior entre a data de hoje e o vencimento anterior, somando a duração do plano. O dono do negócio precisa aprovar essa regra antes de ela ser apresentada como política definitiva.

## 7. Consultar acessos

1. Abra **Acessos**.
2. Confira as últimas tentativas registradas, o horário, o aluno e se o acesso foi liberado ou negado.
3. Leia o motivo quando uma tentativa for negada.
4. Use **Atualizar** para consultar novamente.

Esta tela mostra registros da API. A comunicação com o equipamento físico, a abertura da trava e o comportamento sem internet ainda não foram validados.

Enquanto o painel estiver aberto, dono e recepção também recebem os novos
eventos faciais na lateral, em **Acessos faciais**. O cartão mostra se a entrada
foi liberada ou bloqueada, o nome e o horário. Toque no cartão para abrir o
perfil em **Alunos** quando o rosto tiver sido associado a um aluno. Uma
tentativa sem correspondência aparece sem botão de perfil. Essa área acompanha
a sessão atual; ao sair, os cartões são limpos. O comportamento técnico está
descrito em [`docs/NOTIFICACOES_ACESSO_FACIAL.md`](docs/NOTIFICACOES_ACESSO_FACIAL.md).

## 8. Preparar a segunda tela da entrada — somente dono

1. Depois de aplicar as migrações 006 e 007 no banco de destino, abra **Tela do aluno** no painel do dono.
2. Para personalizar a tela, escolha uma logo opcional. O cadastro de uma nova academia pela conta de administrador também aceita a logo desde o começo.
3. Escolha **Gerar ou renovar código**. O sistema mostra o código uma vez; copie-o diretamente para o computador do monitor e não o publique em chats ou fotos. Renovar o código desconecta a tela atual.
4. No segundo computador, abra `/monitor`, informe o código e escolha o idioma que a pessoa verá.
5. Toque em **Ativar som** nesse computador. Depois disso, o monitor toca um sinal curto quando libera a entrada e um sinal diferente quando a recusa; use o ícone, a cor e a mensagem como confirmação visual.
6. Na entrada, a tela mostra nome abreviado e foto opcional quando a entrada é liberada; um acesso recusado informa para procurar a recepção. O aviso apaga automaticamente.

A página principal `/app` continua separada e exige login. O código do monitor só permite buscar resultados recentes de acesso, não dá acesso ao painel nem ao histórico de pagamentos.

## 9. Gerenciar a recepção — somente dono

1. Abra **Equipe**.
2. Para uma nova pessoa, informe nome, e-mail e uma senha inicial exclusiva com pelo menos oito caracteres.
3. Combine previamente como a pessoa receberá a senha inicial. O formulário é limpo depois de criar a conta, e o sistema não envia nem mostra a senha novamente.
4. Escolha **Criar acesso** e confira a mensagem de sucesso.
5. Entregue a senha diretamente à pessoa por um canal seguro; não a publique em chats ou capturas de tela.
6. Para suspender uma conta, escolha **Suspender** na linha correspondente. A pessoa deixará de conseguir entrar.
7. Use **Reativar** para reativar uma conta suspensa, se isso for autorizado pelo dono.

Não compartilhe a conta do dono. Cada pessoa deve usar sua própria conta de recepção.

## 10. Mensagens comuns

- **Documento ou biometria já cadastrados:** confira se o aluno já existe antes de tentar novamente.
- **Plano inválido:** escolha um plano que pertença à mesma academia.
- **Não há mensalidade em aberto:** confira o histórico de pagamentos do aluno.
- **Pagamento já registrado:** não registre novamente; atualize a tela e confira o histórico.
- **Sem permissão:** peça ao dono para confirmar se essa tarefa pertence ao seu perfil.
- **Sessão expirada:** entre novamente com seu e-mail e senha.
- **Falha de conexão:** interrompa a operação e peça ajuda ao responsável. Não tente compensar uma falha da catraca sem a contingência definida com a academia.

## 11. Itens a concluir antes de entregar este guia

- Substituir o endereço local pelo endereço HTTPS de produção.
- Confirmar a regra de vencimento e as formas de recebimento aceitas.
- Definir um procedimento seguro de troca e redefinição de senha; hoje não há uma tela de autosserviço para isso.
- Confirmar marca, modelo, protocolo, chave e comportamento da catraca real sem copiar a chave para este documento.
- Confirmar a migração 007 e testar a tela do monitor, sons, código de conexão e encerramento automático com o equipamento real.
- Definir o procedimento quando faltar internet, energia ou serviço.
- Definir suporte, troca de senha, retenção e aviso de privacidade com o cliente.
- Repetir os passos com o cliente em staging e ajustar os nomes das telas após o aceite.
