# Frequency — mapa do produto e inventário

Inventário inicial: 29/09/2026. Reutiliza análise da interface existente; não será repetido para cada alteração.

## Produto e papéis

Frequency atende academias: matrícula, mensalidade, recepção e acesso físico. Administrador da plataforma vende assinaturas às academias; dono administra academia/equipe; recepção opera alunos/pagamentos; monitor mostra somente o resultado recente de uma entrada.

Jornadas: login → operação por perfil → formulário validado → confirmação → atualização; dono → mensalidade Frequency → QR/contato → confirmação por administrador; leitor → decisão backend → monitor por 8,5 segundos → limpeza. Cobrança por imagem QR exige conferência manual. Bloqueio de alunos e assinaturas é decisão da API.

## Inventário técnico

| Item | Situação inicial |
|---|---|
| Framework / linguagem | JavaScript nativo e HTML5, sem framework/TypeScript |
| Package manager / build | `frontend/package.json`; build estático sem dependências de runtime |
| Componentes / estado / router | PARTIAL; funções DOM, objeto state, páginas por data-view |
| Autenticação | PARTIAL; JWT sessionStorage, sem refresh previsto na API |
| HTTP | PARTIAL; fetch com api(), faltavam timeout e tratamento 402 |
| Estilos / assets | PARTIAL; CSS responsivo, SVG locais, fontes do sistema |
| Páginas | Login, alunos, pagamentos, planos, acessos, equipe, academias e monitor existentes; SaaS em montagem |
| Testes frontend | `frontend/tests/`, incluindo contrato de notificações faciais |
| PWA / offline | MISSING; serviço local+PostgreSQL é arquitetura de dados existente |
| Integração | RISK; cobrança exige migração008 e contratos em validação; não testar no banco real |
| Diretório original | backend/static contém frontend e alterações parciais anteriores; congelado por nova instrução |
| Propriedade atual | frontend/** e docs/frontend/**; demais arquivos não serão alterados |

## Telas e contratos

| Tela / perfil | Dados e ações | Estado inicial |
|---|---|---|
| Login / público | POST /login, GET /eu; sair/expirar sessão | PARTIAL |
| Visão geral / dono,recepção | /alunos, /alunos/situacao | PARTIAL |
| Alunos / dono,recepção | lista, busca, cadastro, foto opcional, edição; /alunos* | PARTIAL |
| Pagamentos / dono,recepção | filtros, baixa, QR da academia; /pagamentos*, /academia/qr | PARTIAL |
| Resultados / dono | agrupar pagamentos por moeda/data_pagamento; sem lucro fictício | TODO |
| Planos / dono,recepção | consulta; criação só dono | PARTIAL |
| Acessos / dono,recepção | /presencas, histórico limitado e notificações faciais incrementais na lateral do /app | PARTIAL |
| Equipe / dono | /usuarios/recepcao*, criar/suspender | PARTIAL |
| Tela do aluno / dono | chave, logo, abrir monitor | PARTIAL |
| Monitor / chave restrita | /monitor/*, foto, ícones, sons | PARTIAL |
| Meu negócio / admin | /admin/frequency/resumo e academias | TODO |
| Cobranças / admin | faturas, confirmar, cancelar, auditoria, exportar | TODO |
| Pacotes / admin | preços configuráveis, 3 sugestões de nomes, assinaturas | TODO |
| QR e contato / admin | /admin/frequency/qr/{moeda}, configuracao | TODO |
| Academias / admin | cadastro, logo opcional, suspender/reativar | PARTIAL |
| Assinatura / dono,recepção | dono vê /assinatura-frequency; recepção somente /eu | TODO |
| Preferências | idioma neste navegador, país/moeda conhecidos; endereço pendente | TODO |
| Instalar / todos | PWA, instruções reais, disponibilidade de serviço | TODO |

Todas as telas carregam dados com feedback, erro e tentativa novamente; listas vazias explícitas; bloqueio/401 e somente consulta controlam navegação. Layout testado em 320,390,768,1366 e1920px. Sem serviço acessível, não criar fila de pagamentos offline: API atual não oferece idempotência/reconciliação para isso.
