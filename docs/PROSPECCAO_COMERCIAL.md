# Prospecção comercial

## Acesso

1. Aplique as migrations `029_prospeccao_comercial.sql` e `030_configuracao_prospeccao.sql` na ordem, após um backup verificado.
2. Entre no Frequency com uma conta `admin_plataforma` e abra **Prospecção** no menu lateral. Donos, recepção e academias clientes não veem esta área.

## Uso

- Cadastre um lead manualmente ou importe um CSV com cabeçalho. O mínimo é `nome`; as colunas aceitas estão na tela de importação.
- Em **Mensagens e imagem da campanha**, salve os modelos de WhatsApp, assunto/corpo de e-mail e uma imagem comercial. `{academia}` e `{cidade}` são preenchidos automaticamente para cada lead.
- Use os filtros e o funil para priorizar os contatos. **Preparar e-mail** abre o cliente de e-mail com texto preenchido; **Abrir WhatsApp** abre uma conversa com texto preenchido. Confirme e anexe a imagem no aplicativo antes de enviar.
- Atualize o status e o último contato após o envio. Excluir arquiva logicamente o lead e mantém a auditoria.

## Limite da primeira versão

O módulo não coleta contatos de sites, não raspa Google Maps/Apify e não faz disparos automáticos ou em massa. A interface `FonteFuturaDeLeads` existe apenas como ponto de integração futuro, sujeito a autorização e regras do provedor.
