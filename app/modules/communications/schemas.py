"""Communications DTOs (API_V2_CONTRACT §11 N2-N5, N8-N11).

Wave 3.1: every DTO here now comes from ``app/contracts/dto.py`` - A7 kept module copies while the integrator
moved them into the contract, and this module re-exports them so the API layer keeps importing from one place.
Nothing is redefined; a change belongs in the contract (AGENTS §1, §4).
"""

from __future__ import annotations

from app.contracts.dto import (
    ChatHideRequest,
    ChatMessageAdminDTO,
    ChatMessageCreate,
    ChatMessageDTO,
    ContractModel,
    DeviceDTO,
    EventDTO,
    NotificationDTO,
    OutboxEventAdminDTO,
    OutboxRetryRequest,
    PushTokenRegister,
    UtcDateTime,
)
from app.contracts.dto import PUSH_TOKEN_MAX_LENGTH, REASON_MAX_LENGTH

__all__ = [
    "PUSH_TOKEN_MAX_LENGTH",
    "REASON_MAX_LENGTH",
    "ChatHideRequest",
    "ChatMessageAdminDTO",
    "ChatMessageCreate",
    "ChatMessageDTO",
    "ContractModel",
    "DeviceDTO",
    "EventDTO",
    "NotificationDTO",
    "OutboxEventAdminDTO",
    "OutboxRetryRequest",
    "PushTokenRegister",
    "UtcDateTime",
]
