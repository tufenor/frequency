# ADR-015: confirmação automática de assinaturas por gateway

**Status:** Proposto para homologação

## Contexto

O Frequency já gera a fatura da assinatura da academia, mas a baixa atual é
manual. Um QR estático não informa ao sistema quem pagou, qual fatura foi paga
ou se o valor está correto. A assinatura não pode ser liberada por comprovante
enviado pelo navegador.

## Decisão

Usar um gateway de pay-in com checkout hospedado e webhook assinado. A primeira
implementação é o dLocal Payins porque a documentação oficial cobre Bolívia,
BOB, QR/transferência/cartão e notificações de mudança de status. O Frequency
envia uma referência única para cada fatura, guarda o checkout no servidor e
aceita a baixa somente quando o webhook assinado no cabeçalho `Authorization`
confere referência, valor e moeda. Repetições são deduplicadas por hash do evento.

O QR manual permanece disponível como fallback, mas nunca dispara liberação
automática. Credenciais ficam nas variáveis de ambiente do servidor; nenhum
segredo chega ao frontend.

## Alternativa avaliada

O Tigo Money possui botão de pagamento empresarial e conciliação imediata, mas
exige adesão comercial e a documentação pública consultada não define um
contrato de webhook que possamos homologar sem contato comercial. Ele pode ser
adicionado depois pelo mesmo adaptador, sem alterar a regra de liquidação.

## Consequências

- É necessário criar uma conta comercial dLocal, obter credenciais de sandbox e
  produção e publicar o webhook em HTTPS.
- A primeira cobrança pede o documento do pagador exigido pela operação
  boliviana; o documento não é salvo no checkout nem no payload de auditoria.
- A assinatura só muda para `pago` no banco depois da confirmação do gateway.
- A liberação depende da aplicação da migração 015 em cada ambiente.

## Próximos passos de homologação

1. Criar credenciais sandbox no Merchant Dashboard dLocal.
2. Configurar `PAYMENT_PUBLIC_BASE_URL`, `DLOCAL_X_LOGIN`, `DLOCAL_X_TRANS_KEY`
   e `DLOCAL_SECRET_KEY` no servidor, fora do repositório.
3. Testar uma fatura sintética com QR em BOB e reenviar o mesmo webhook para
   confirmar idempotência.
4. Só depois trocar para produção e liberar o botão aos clientes.
