# Problemas e limites observados do backend

Não foram feitas alterações no backend nesta etapa de propriedade exclusiva. Evidências abaixo são contrato/código anteriormente inspecionado, sem execução contra dados reais.

| Endpoint | Esperado / observado | Impacto e sugestão |
|---|---|---|
| POST /admin/academias, /eu | Localização e idioma individual; atualmente sem endereço e país padrão só BR/BO | Não oferecer salvamento falso; criar contrato regional e guardar moeda histórica |
| GET /alunos | Matrículas mensais exigem data real; lista não tem data_inicio | Front não inventa gráfico de matrícula; fornecer agregado autenticado |
| /admin/frequency/* | Exige migração008; instalação atual não verificada | Mostrar 503 amigável, coordenação deve homologar migração em staging |
| PATCH faturas/{id}/cancelar | Backend foi informado pelo tech lead sobre impedir cancelamento da última fatura ativa sem suspensão explícita | Tratar409 e preservar formulário; confirmação desta correção depende do backend |
| /admin/frequency/assinaturas | Vencimento exibido deve coincidir com fatura ativa | Tech lead encaminhou BE-01; validar contrato atualizado antes da entrega |
| /app e recursos estáticos | Novo frontend em frontend/dist; servidor atual serve backend/static | Responsável backend/deploy precisa apontar distribuição nova sem sobrescrever código de API |

Problemas encontrados em testes reais serão adicionados com esperado, observado, impacto e sugestão. Testes frontend usam contratos sintéticos; não comprovam regras internas do servidor.
