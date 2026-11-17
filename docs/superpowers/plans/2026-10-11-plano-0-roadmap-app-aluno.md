# Roadmap de implementação — App do aluno, painel e lutas

**Spec:** `docs/superpowers/specs/2026-10-11-app-aluno-login-evolucao-treinos-design.md`

A especificação cobre subsistemas independentes. Cada plano abaixo entrega software testável sozinho e é escrito só depois que o anterior passou nos testes (as interfaces reais podem mudar o que vem depois).

| Plano | Marco | Entrega | Depende de |
|---|---|---|---|
| 1 | M0+M1 | Contrato da API, migrações 043–045, login do aluno no backend (e-mail+código, senha, sessão, Google) | — |
| 2 | M2 | App: login, armazenamento seguro, layout responsivo celular/tablet | 1 |
| 3 | M3 | Catálogo ≥12/grupo, treinos em blocos, painel web "Exercícios" | 1 |
| 4 | M4 | Evolução, offline por série, pulso, mapa do corpo, carga, arte Instagram | 2,3 |
| 5 | M5 | Quiosque do tablet com check-in facial | 2 |
| 6 | M6 | Chave de produção, OTA, atualizador | 2 |
| 7 | M7 | Lutas (backend, painel, app) | 1,3 |
| 8 | M8 | Mensalidade/QR, desafios, agenda de aulas, gerador de treino | 1–7 |

**Regras de todos os planos:** sem deploy, sem migração em banco real, sem apagar dados, sem segredos em log; migrações aditivas numeradas a partir da 043 (042 reservada ao patch 031→042 pendente); cada recurso atrás de flag por academia; relatório final com arquivos alterados, testes, resultado e riscos.
