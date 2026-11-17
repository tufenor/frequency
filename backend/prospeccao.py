"""Regras locais de prospecção; nenhum provedor externo é ativado aqui."""

from __future__ import annotations

from typing import Protocol


TEMPLATE_WHATSAPP_PADRAO = "Hola {academia} de {cidade}, quería presentarte Frequency. ¿Te gustaría ver una demostración breve?"
TEMPLATE_EMAIL_ASSUNTO_PADRAO = "¿Administras un gimnasio? Prueba Frequency Gym gratis durante 7 días"
TEMPLATE_EMAIL_CORPO_PADRAO = "Hola, {academia}.\n\n¿Administras un gimnasio en {cidade}? Frequency Gym te ayuda a gestionar socios, membresías, pagos, accesos y asistencias desde un solo lugar, con una operación más simple y profesional.\n\nPuedes probarlo gratis durante 7 días, sin compromiso. Si te interesa, responde a este correo y coordinamos una demostración breve.\n\nSi prefieres no recibir más información, responde “BAJA” y no volveremos a contactar.\n\nSaludos,\nEquipo Frequency Gym\nTecnología para tu evolución"


class FonteFuturaDeLeads(Protocol):
    """Contrato para futura integração licenciada (Maps, Apify ou CRM).

    A primeira versão não instancia este contrato nem faz requisições para
    provedores. Toda origem externa precisa de autorização própria.
    """

    def coletar(self, consulta: str) -> list[dict[str, object]]:
        """Retorna dados sujeitos à revisão humana antes da importação."""


def email_prospeccao_espanhol(nome: str, cidade: str) -> tuple[str, str]:
    return (
        renderizar_template(TEMPLATE_EMAIL_ASSUNTO_PADRAO, nome, cidade),
        renderizar_template(TEMPLATE_EMAIL_CORPO_PADRAO, nome, cidade),
    )


def mensagem_whatsapp_espanhol(nome: str, cidade: str) -> str:
    return renderizar_template_whatsapp(TEMPLATE_WHATSAPP_PADRAO, nome, cidade)


def renderizar_template_whatsapp(template: str, nome: str, cidade: str) -> str:
    return renderizar_template(template, nome, cidade)


def renderizar_template(template: str, nome: str, cidade: str) -> str:
    return template.replace("{academia}", nome).replace("{cidade}", cidade or "tu ciudad")
