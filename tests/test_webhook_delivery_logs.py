import json
import logging
import sys

import pytest

from src.common.logging import StructuredFormatter
from src.common.redaction import REDACTED
from src.webhooks.delivery import WebhookDeliveryLog, WebhookDeliveryRejected


def test_delivery_payload_is_redacted_before_callback_payload():
    delivery_log = WebhookDeliveryLog()

    record = delivery_log.record_delivery(
        workspace_id="workspace-a",
        endpoint_id="endpoint-1",
        delivery_id="delivery-1",
        status="failed",
        payload={
            "event": "agent.failed",
            "authorization": "Bearer abcdefghijklmnopqrstuvwxyz",
            "nested": {
                "webhook_secret": "sk_live_supersecret123456",
                "safe": "visible",
            },
        },
        error="delivery failed with token=sk_live_errorsecret123456",
    )
    callback = delivery_log.callback_payload(record)

    rendered = json.dumps(callback)
    assert REDACTED in rendered
    assert "abcdefghijklmnopqrstuvwxyz" not in rendered
    assert "supersecret" not in rendered
    assert "errorsecret" not in rendered
    assert callback["payload"]["nested"]["safe"] == "visible"
    assert "workspace_id" not in callback


def test_disabled_or_rotated_endpoint_is_rejected_before_recording():
    delivery_log = WebhookDeliveryLog()

    with pytest.raises(WebhookDeliveryRejected):
        delivery_log.record_delivery(
            workspace_id="workspace-a",
            endpoint_id="endpoint-1",
            delivery_id="delivery-1",
            status="failed",
            payload={},
            endpoint_enabled=False,
        )

    with pytest.raises(WebhookDeliveryRejected):
        delivery_log.record_delivery(
            workspace_id="workspace-a",
            endpoint_id="endpoint-1",
            delivery_id="delivery-2",
            status="failed",
            payload={},
            endpoint_version=2,
            expected_endpoint_version=1,
        )

    assert delivery_log.records_for_workspace("workspace-a") == []


def test_retry_attempts_are_idempotent_per_delivery_attempt():
    delivery_log = WebhookDeliveryLog()

    first = delivery_log.record_delivery(
        workspace_id="workspace-a",
        endpoint_id="endpoint-1",
        delivery_id="delivery-1",
        attempt=2,
        status="failed",
        payload={"token": "sk_live_firstsecret123456"},
    )
    duplicate = delivery_log.record_delivery(
        workspace_id="workspace-a",
        endpoint_id="endpoint-1",
        delivery_id="delivery-1",
        attempt=2,
        status="success",
        payload={"token": "sk_live_secondsecret123456"},
    )

    assert duplicate is first
    assert duplicate.status == "failed"
    assert len(delivery_log.records_for_workspace("workspace-a")) == 1


def test_delivery_records_are_isolated_by_workspace():
    delivery_log = WebhookDeliveryLog()
    delivery_log.record_delivery(
        workspace_id="workspace-a",
        endpoint_id="endpoint-1",
        delivery_id="delivery-a",
        status="success",
        payload={"event": "agent.completed"},
    )
    delivery_log.record_delivery(
        workspace_id="workspace-b",
        endpoint_id="endpoint-1",
        delivery_id="delivery-b",
        status="success",
        payload={"event": "agent.completed"},
    )

    workspace_a_records = delivery_log.records_for_workspace("workspace-a")

    assert len(workspace_a_records) == 1
    assert workspace_a_records[0].delivery_id == "delivery-a"


def test_structured_formatter_redacts_secret_text_in_logs_and_exceptions():
    formatter = StructuredFormatter()
    logger_name = "tests.webhook"
    record = logging.LogRecord(
        logger_name,
        logging.ERROR,
        __file__,
        1,
        "dispatch failed token=%s",
        ("sk_live_message_secret123456",),
        None,
    )

    try:
        raise RuntimeError("webhook_secret=sk_live_exception_secret123456")
    except RuntimeError:
        record.exc_info = sys.exc_info()

    formatted = json.loads(formatter.format(record))

    assert REDACTED in formatted["message"]
    assert "message_secret" not in formatted["message"]
    assert REDACTED in formatted["exception"]
    assert "exception_secret" not in formatted["exception"]
