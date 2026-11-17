"""Validated, versioned wire models for the local-to-cloud event stream."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PayloadBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: UUID


class PlanoPayload(PayloadBase):
    nome: str = Field(min_length=1, max_length=100)
    valor: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    moeda: Literal["BRL", "BOB"] | None = None
    duracao_dias: int = Field(ge=1, le=3660)


class AlunoPayload(PayloadBase):
    nome: str = Field(min_length=1, max_length=160)
    bairro: str | None = Field(default=None, max_length=160)
    status: Literal["ativo", "inativo"]
    plano_id: UUID | None
    data_inicio: date | None = None


class PagamentoPayload(PayloadBase):
    aluno_id: UUID
    valor: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    moeda: Literal["BRL", "BOB"] | None = None
    vencimento: date
    data_pagamento: date | None
    status: Literal["em_aberto", "pago"]


class PresencaPayload(PayloadBase):
    aluno_id: UUID | None
    data_hora_local: datetime
    liberado: bool
    motivo: str | None = Field(default=None, max_length=120)


class SyncEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    academia_sync_id: UUID
    revision: int = Field(ge=1)
    entity_type: Literal["plano", "aluno", "pagamento", "presenca"]
    entity_sync_id: UUID
    operation: Literal["upsert", "delete"]
    schema_version: Literal[1]
    payload: dict[str, Any]


PAYLOAD_MODELS = {
    "plano": PlanoPayload,
    "aluno": AlunoPayload,
    "pagamento": PagamentoPayload,
    "presenca": PresencaPayload,
}


def validar_payload(evento: SyncEvent) -> PayloadBase:
    if evento.operation == "delete":
        payload = PayloadBase.model_validate(evento.payload)
        if payload.id != evento.entity_sync_id:
            raise ValueError("O ID da entidade não corresponde ao evento.")
        return payload
    model = PAYLOAD_MODELS[evento.entity_type]
    payload = model.model_validate(evento.payload)
    if payload.id != evento.entity_sync_id:
        raise ValueError("O ID da entidade não corresponde ao evento.")
    if (
        evento.entity_type == "presenca"
        and payload.data_hora_local.tzinfo is not None
    ):
        raise ValueError("A data da presença precisa manter o horário local original.")
    return payload
