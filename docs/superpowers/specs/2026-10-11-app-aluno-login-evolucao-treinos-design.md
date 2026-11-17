---
title: "App do aluno — login, evolução, treinos editáveis e tablet"
subtitle: "Especificação de design (rascunho para revisão)"
date: 2026-10-11
---

# 1. Objetivo

Transformar o app do aluno (Expo / React Native, Android primeiro) em um app que exige login, acompanha a evolução do aluno, permite montar e editar treinos, oferece muitos treinos prontos e recebe conteúdo da própria academia. Deve funcionar bem em **celular e tablet**.

**Regra de ouro:** o app nunca decide o acesso. O servidor decide (regra `/acesso`) e cada aluno fica preso à sua `academia_id`.

# 2. Escopo em duas ondas

| Onda | Entrega |
|---|---|
| **1** | Login (e-mail + código + senha, e Google), evolução, treinos editáveis, modelos prontos, layout celular + tablet, **biblioteca ampliada (mín. 10 exercícios por grupo)** e **catálogo da academia no painel web (ativar/ocultar/acrescentar exercícios)**, já refletido no app |
| **2** | Vídeos próprios da academia, treinos publicados pelo professor para turmas, relatórios |

Fora de escopo agora: pagamento dentro do app, chat, iOS, download offline de vídeos.

# 3. Login

## 3.1 Fluxo

1. Tela inicial pede **e-mail**.
2. O servidor consulta se o e-mail pertence a um aluno ativo de alguma academia.
3. Primeiro acesso: envia **código de 6 dígitos** por e-mail → aluno digita o código → cria a senha.
4. Acessos seguintes: e-mail + senha.
5. **Google:** botão alternativo. Só entra se o e-mail verificado do Google constar no cadastro da academia.
6. Esqueci a senha: refaz o passo 3.

## 3.2 Rotas novas (entram primeiro em `API_CONTRACT.md`)

| Rota | Função |
|---|---|
| `POST /aluno/auth/iniciar` | Recebe `email`. Responde sempre igual (`proximo`: `codigo` ou `senha`), sem revelar se o e-mail existe. |
| `POST /aluno/auth/codigo` | Valida o código. |
| `POST /aluno/auth/definir-senha` | Cria ou troca a senha após código válido. |
| `POST /aluno/auth/entrar` | E-mail + senha → sessão. |
| `POST /aluno/auth/google` | `id_token` do Google → sessão. |
| `POST /aluno/auth/sair` | Encerra a sessão. |
| `GET /aluno/eu` | Perfil e situação de acesso do aluno logado. |

## 3.3 Regras de segurança

- Código: 6 dígitos, validade 10 min, uso único, 5 tentativas, guardado só como hash.
- Limite de pedidos por e-mail e por IP (reaproveitar `rate_limiting.py`).
- Senha com `pwdlib`/Argon2, como o resto do sistema. Mínimo de 8 caracteres.
- Sessão por token de acesso curto + token de renovação; guardados no armazenamento seguro do aparelho (`expo-secure-store`), nunca em texto simples.
- Resposta idêntica para e-mail desconhecido (sem enumeração de contas).
- Google: validar assinatura, `aud`, `exp` e `email_verified` no servidor.
- O código chega por SMTP já existente (`FREQUENCY_SMTP_*`). Em teste, sem SMTP configurado, o servidor devolve erro claro e **não** registra o código no log.

## 3.4 Dados

| Tabela | Campos principais |
|---|---|
| `aluno_credenciais` | `aluno_id`, `senha_hash`, `google_sub` (opcional), `criado_em` |
| `aluno_codigos` | `aluno_id`, `codigo_hash`, `expira_em`, `tentativas`, `usado_em` |
| `aluno_sessoes` | `aluno_id`, `refresh_hash`, `dispositivo`, `expira_em`, `revogada_em` |

# 4. Evolução

| Recurso | Detalhe |
|---|---|
| Peso e medidas | peso, cintura, peito, braço, coxa, quadril, com data; gráfico de linha; meta de peso |
| Cargas | recorde pessoal (PR) por exercício; gráfico da carga ao longo do tempo |
| Constância | calendário de presença (check-in da academia) e sequência de dias |
| Fotos de progresso | antes/depois, privadas, só o próprio aluno vê |
| Resumo semanal | treinos feitos, volume total (séries × reps × carga), novos recordes |

Tabelas: `aluno_medidas`, `aluno_fotos_progresso`, `aluno_series_registradas` (exercício, data, série, reps, carga). Os recordes são calculados, não digitados.

Dados do aluno são sensíveis: a academia **não** vê fotos de progresso; peso e medidas só com consentimento explícito do aluno (campo `compartilhar_com_academia`, desligado por padrão).

# 5. Treinos editáveis

## 5.1 Modelo: dia → blocos → exercícios

Um treino não é uma lista fixa "costas e bíceps". Ele é montado com **blocos**, e cada bloco é um grupo muscular.

- **Dia de treino**: nome opcional ("B"), dias da semana, e uma lista ordenada de **blocos**.
- **Bloco**: um grupo muscular (ex.: Costas) ou um bloco livre (ex.: Aquecimento, Cardio), com sua lista de exercícios.
- **Item**: exercício, séries, repetições (ou segundos), carga, descanso, observação.

Os nomes prontos ("Costas e bíceps") são só **atalhos** que montam dois blocos de uma vez. Depois de criado, nada fica amarrado ao atalho.

## 5.2 Cada bloco funciona sozinho

| Ação | O que acontece |
|---|---|
| Juntar grupos no mesmo dia | O aluno adiciona quantos blocos quiser ao dia (ex.: Costas + Bíceps, ou Peito + Tríceps + Ombros) |
| Separar | Mover um bloco para outro dia, ou arrastá-lo para um dia novo, sem mexer nos demais |
| Editar | Trocar, adicionar, remover e reordenar exercícios só naquele bloco |
| Duplicar ou apagar | Por bloco, não pelo dia inteiro |
| Concluir | Cada bloco tem o seu "concluído", cronômetro de descanso e histórico |
| Progresso | Recordes, volume e gráficos são por exercício e por grupo, então continuam corretos mesmo que o bloco mude de dia |

Na tela do dia, os blocos aparecem juntos como uma sessão única, mas o aluno pode fazer só um deles e deixar o outro para outro momento.

## 5.2b Escolha livre dos grupos

- Ao montar ou editar um dia, o aluno toca em **"+ Grupo no mesmo dia"** e vê todos os grupos (peito, costas, ombros, bíceps, tríceps, antebraço, abdômen, lombar, quadríceps, posteriores, glúteos, panturrilhas) mais blocos livres (aquecimento, cardio, alongamento).
- Pode marcar **quantos quiser, em qualquer combinação** (ex.: tríceps + pernas). Não há pares obrigatórios nem bloqueios.
- Ao confirmar, cada grupo marcado vira um bloco vazio, e o aluno escolhe os exercícios daquele bloco no catálogo liberado pela academia.
- O nome do dia é sugerido pelos grupos ("Tríceps + Quadríceps") e pode ser trocado.

## 5.3 Ações do aluno

Criar, duplicar, renomear, excluir e reordenar dias e blocos; trocar exercício; editar séries, repetições, carga e descanso; anotar; criar exercício próprio (nome, grupo, equipamento, foto opcional).

## 5.4 Modelos prontos

Meta: pelo menos 20 modelos em português (ABC, ABCD, ABCDE, full body 3×, push/pull/legs, superior/inferior, iniciante, emagrecimento, hipertrofia, em casa sem equipamento, só halteres, glúteos, mobilidade). Um modelo é apenas uma combinação de blocos; copiá-lo cria uma cópia editável, e o original não muda.

## 5.5 Dados

`treinos` (o dia), `treino_blocos` (grupo, ordem, concluído), `treino_itens`, `exercicios_custom` e `treinos_modelo` (somente leitura). A cópia guarda `modelo_origem_id`. Mover um bloco só troca o `treino_id` dele.

# 6. Biblioteca e catálogo da academia (app + web)

## 6.1 Biblioteca Frequency ampliada

- Hoje são 8 exercícios por grupo muscular (80 no total). Meta: **no mínimo 12 por grupo** em todos os 10 grupos (peito, costas, ombros, bíceps, tríceps, abdômen, quadríceps, posteriores, glúteos, panturrilhas), mais antebraço e lombar. Exemplo: tríceps com 12 ou mais opções.
- Fonte das fotos: free-exercise-db (Unlicense). A base tem exercícios de sobra em todos os grupos (menor caso: glúteos, 22).
- Cada exercício traz nome em português, grupo, equipamento, nível e série/repetição sugeridas.

## 6.2 Quem controla o quê

| Quem | Pode |
|---|---|
| **Frequency** | Mantém o catálogo global (somente leitura para as academias) |
| **Academia** (dono/gerente, no painel web) | Ativar ou ocultar exercícios do catálogo global para os seus alunos; acrescentar exercícios próprios (nome, grupo, equipamento, foto ou vídeo); editar ou remover os próprios |
| **Aluno** (no app) | Ver o catálogo liberado pela academia; criar exercícios só para si; montar treinos com qualquer um deles |

Regra: o aluno vê **catálogo global − ocultos pela academia + exercícios da academia + os dele**.

## 6.3 App e web trabalham juntos

- Uma única fonte de verdade no servidor; app e painel usam as mesmas rotas.
- O app baixa o catálogo da academia ao abrir e ao puxar para atualizar, e guarda uma cópia local para funcionar sem internet; mudanças da academia aparecem na próxima atualização.
- Se a academia ocultar um exercício que já está num treino do aluno, o exercício continua no treino dele (aparece com aviso "removido pela academia") e não some sem aviso.

| Rota nova (contrato primeiro) | Função |
|---|---|
| `GET /academias/{id}/exercicios` | Catálogo efetivo da academia (usado pelo app e pelo painel) |
| `PUT /academias/{id}/exercicios/{ex}/visibilidade` | Ativar ou ocultar um exercício global |
| `POST/PATCH/DELETE /academias/{id}/exercicios` | Exercícios próprios da academia |
| `POST /academias/{id}/exercicios/{ex}/midia` | Foto ou vídeo do exercício da academia |

Tabelas: `exercicios_catalogo` (global), `academia_exercicios_visibilidade` (ativo/oculto por academia), `exercicios_custom` (com escopo aluno ou academia) e `exercicio_midias`.

## 6.4 Painel web da academia

Tela "Exercícios" com busca e filtro por grupo; interruptor ativar/ocultar em cada exercício; botão "Novo exercício"; contagem por grupo, com aviso quando um grupo ficar com menos de 10 ativos. Só dono/gerente editam; isolamento por `academia_id`.

## 6.5 Vídeos (onda 2)

MP4 enviado pelo painel, guardado no servidor (não no Google Drive), entregue por URL assinada de curta duração; tamanho máximo definido pelo servidor.

# 7. Tablet e telas grandes

Hoje o app trava em retrato (`orientation: portrait` e `screenOrientation="portrait"`) e não tem layout responsivo. Mudanças:

| Item | Decisão |
|---|---|
| Orientação | Liberar (`default`); manter retrato por padrão no celular, girar no tablet |
| Janela redimensionável | Suportar tela dividida e multi-janela (`resizeableActivity`) |
| Faixas de largura | Compacta < 600 dp (celular) · Média 600–839 dp · Expandida ≥ 840 dp |
| Navegação | Compacta: barra inferior. Média/expandida: **barra lateral** (navigation rail) |
| Treino | Expandida: **dois painéis** — lista de treinos/exercícios à esquerda, detalhe à direita |
| Biblioteca | Grade com 2–4 colunas conforme a largura, em vez de lista única |
| Evolução | Gráficos lado a lado em duas colunas |
| Folhas modais | No tablet, painel lateral ou diálogo centralizado, não folha de tela cheia |
| Largura de conteúdo | Limite de ~720 dp em telas muito largas, centralizado |
| Toque e teclado | Alvos de toque ≥ 48 dp; teclado externo e foco visível nos controles |
| Fonte e contraste | Respeitar tamanho de fonte do sistema; contraste AA nos dois temas |

Implementação: um hook `useLayout()` que devolve `compacta | media | expandida` a partir de `useWindowDimensions`, usado por todas as telas, para não espalhar números mágicos.

# 8. Verificação

| O quê | Como |
|---|---|
| Backend | Testes unitários e de banco (PostgreSQL) para cada rota nova, incluindo casos de abuso: código errado, expirado, reutilizado, e-mail inexistente, aluno de outra academia |
| Migrações | Entram numeradas a partir da 043; verificação de impressão digital como as demais; **nenhuma aplicada em banco real sem autorização** |
| App | `tsc --noEmit`; testes dos cálculos (recordes, volume, sequência); renderização em Chromium nas larguras 360, 600, 840 e 1280 dp |
| APK | Build de release arm64, verificação do pacote e da assinatura |
| Limite | Sem celular ou tablet reais nesta sessão: o APK precisa de teste manual do dono em aparelho real |

# 9. Riscos e dependências do dono

| Item | Quem resolve |
|---|---|
| Credencial **Android** do Google Cloud ligada à assinatura (SHA-1) do APK | Dono (passo a passo será entregue) |
| SMTP configurado e testado em produção | Codex/dono |
| APK ainda assinado com chave de debug; para a loja é preciso chave de release | Dono |
| Publicação do backend e da landing | Codex |
| LGPD / dados de saúde: política de privacidade do app e consentimento | Dono |

# 10. Ordem de construção

1. Contrato da API e migrações.
2. Backend de login + testes.
3. Backend de evolução, treinos e modelos + testes.
4. App: login.
5. App: layout responsivo (`useLayout`) e navegação por barra lateral.
6. App: evolução e treinos editáveis.
7. Painel web: tela "Exercícios" da academia (onda 1) e vídeos próprios (onda 2).
8. APK novo e pacote de publicação para o Codex.

## 8. Escopo ampliado da Onda 1 (decisões de 11/10)

| # | Recurso | Como funciona | Tela |
|---|---|---|---|
| 8.1 | Offline + salvar a cada série | Cada série vai para uma fila local (SQLite/AsyncStorage) com id único; sincroniza ao voltar a internet (idempotente por `client_id`). Treino em andamento sobrevive a fechar o app. | 9 |
| 8.2 | Tablet quiosque com check-in facial | Tablet na recepção/salão reconhece o rosto (fluxo facial já existente), libera a entrada e abre o treino do dia com as últimas cargas. Fallback: QR ou e-mail. | 11 |
| 8.3 | Mapa do corpo + sugestão de carga | Cores por grupo muscular nos últimos 7 dias; sugestão de carga por regra simples (completou todas as reps sem falha → +2,5 kg; falhou → manter). Aluno aceita ou mantém. | 9 |
| 8.4 | Pulso de frequência | Forma de onda semanal (assinatura visual da marca) na Evolução e no cartão. | 9, 10 |
| 8.5 | Arte para Instagram (estilo Strava) | Formato 1080×1920 (stories) e 1080×1350 (feed), gerada no aparelho: nome do treino, duração, volume, séries, recordes, pulso, nome do aluno, **logo Frequency + frequencygym.tech**. Fundo escuro de marca, exportada como PNG e aberta na folha de compartilhamento do Android. Aluno escolhe ocultar dados (ex.: volume). | 10 |
| 8.6 | Mensalidade/QR no app | Status da mensalidade, QR de acesso, pagamento via dLocal quando houver credenciais. | futura |
| 8.7 | Desafios com ranking (TV/tablet) | Desafios da academia (ex.: mais treinos no mês); ranking exibido em tela da academia. | futura |
| 8.8 | Agenda de aulas com reserva | Turmas, horários, vagas e reserva pelo app; gestão no painel web. | futura |
| 8.9 | Gerar treino por objetivo e aparelhos | Monta blocos a partir do objetivo e dos aparelhos que a academia marcou como disponíveis (catálogo da seção 6). Regras, sem IA externa. | futura |

**Faseamento:** 8.1–8.5 entram juntos com login, evolução, treinos editáveis e tablet (Onda 1). 8.6–8.9 foram escolhidos pelo dono e entram em sequência logo após (Onda 1B), porque 8.6 depende das credenciais dLocal e 8.7/8.8 pedem telas novas no painel web.

**Privacidade da arte:** o PNG é gerado localmente e só sai do aparelho quando o aluno toca em compartilhar; nada é publicado automaticamente. A foto de progresso nunca entra na arte sem escolha explícita.
