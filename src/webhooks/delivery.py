"""Webhook delivery log shaping with redaction and idempotency."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from src.common.redaction import redact_sensitive, redact_text


class WebhookDeliveryRejected(ValueError):
    """Raised when a delivery should be rejected before work is recorded."""


@dataclass(frozen=True)
class DeliveryRecord:
    workspace_id: str
    endpoint_id: str
    delivery_id: str
    attempt: int
    status: str
    payload: Dict[str, Any]
    error: str


class WebhookDeliveryLog:
    """In-memory delivery log used to shape safe webhook callback records."""

    def __init__(self) -> None:
        self._records: Dict[Tuple[str, str, str, int], DeliveryRecord] = {}

    def record_delivery(
        self,
        *,
        workspace_id: str,
        endpoint_id: str,
        delivery_id: str,
        status: str,
        payload: Dict[str, Any],
        attempt: int = 1,
        endpoint_enabled: bool = True,
        endpoint_version: int = 1,
        expected_endpoint_version: int = 1,
        error: str = "",
    ) -> DeliveryRecord:
        """Record after endpoint checks and return the safe record."""

        if not endpoint_enabled:
            raise WebhookDeliveryRejected("endpoint is disabled")
        if endpoint_version != expected_endpoint_version:
            raise WebhookDeliveryRejected("endpoint version changed")
        if attempt < 1:
            raise WebhookDeliveryRejected("attempt must be positive")

        key = (workspace_id, endpoint_id, delivery_id, attempt)
        existing = self._records.get(key)
        if existing:
            return existing

        record = DeliveryRecord(
            workspace_id=workspace_id,
            endpoint_id=endpoint_id,
            delivery_id=delivery_id,
            attempt=attempt,
            status=status,
            payload=redact_sensitive(payload),
            error=redact_text(error),
        )
        self._records[key] = record
        return record

    def callback_payload(self, record: DeliveryRecord) -> Dict[str, Any]:
        """Return a callback-safe payload without internal workspace fields."""

        return {
            "endpoint_id": record.endpoint_id,
            "delivery_id": record.delivery_id,
            "attempt": record.attempt,
            "status": record.status,
            "payload": redact_sensitive(record.payload),
            "error": redact_text(record.error),
        }

    def records_for_workspace(self, workspace_id: str) -> List[DeliveryRecord]:
        """Return only records owned by the requested workspace."""

        return [
            record
            for record in self._records.values()
            if record.workspace_id == workspace_id
        ]
