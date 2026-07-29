from __future__ import annotations

import json

from agent_workflow.migration.redaction import redact_json, redact_text


def test_redacts_sensitive_json_keys_recursively() -> None:
    source = {
        "mcpServers": {
            "demo": {
                "command": "server",
                "env": {"API_TOKEN": "secret-value", "MODE": "safe"},
            }
        },
        "permissions": {"allow": ["Read"]},
    }

    redacted = redact_json(source)

    assert redacted["mcpServers"]["demo"]["env"]["API_TOKEN"] == "<redacted>"
    assert redacted["mcpServers"]["demo"]["env"]["MODE"] == "safe"
    assert "secret-value" not in json.dumps(redacted)


def test_blocks_private_key_material() -> None:
    text = "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"

    result = redact_text(text)

    assert result.blocked
    assert result.text is None
    assert "private-key" in result.reasons


def test_redacts_unambiguous_labeled_scalar_without_retaining_value() -> None:
    result = redact_text("mode=safe\ntoken=top-secret-value\n")

    assert result.blocked is False
    assert result.text == "mode=safe\ntoken=<redacted>\n"
    assert "top-secret-value" not in result.text
    assert result.reasons == ("labeled-secret",)


def test_blocks_ambiguous_labeled_secret() -> None:
    result = redact_text("password: this value contains spaces\n")

    assert result.blocked
    assert result.text is None
    assert result.reasons == ("ambiguous-secret",)
