from __future__ import annotations

import json
from pathlib import Path

from agent_workflow.cli import main

from tests.migration.helpers import (
    write_inventory_fixture,
    write_request_fixture,
    write_response_fixture,
)


def test_classify_request_contains_redacted_ambiguous_artifacts(
    tmp_path: Path,
) -> None:
    inventory, home = write_inventory_fixture(tmp_path)
    output = tmp_path / "request.json"

    code = main(
        [
            "migrate",
            "classify-request",
            "--inventory",
            str(inventory),
            "--output",
            str(output),
            "--home",
            str(home),
        ]
    )

    serialized = output.read_text(encoding="utf-8")
    payload = json.loads(serialized)
    assert code == 0
    assert payload["artifacts"]
    assert "secret-value" not in serialized
    assert "<redacted>" in serialized
    assert str(home) not in serialized


def test_classify_request_rejects_source_outside_selected_home(
    tmp_path: Path,
) -> None:
    inventory, _ = write_inventory_fixture(tmp_path)
    other_home = tmp_path / "other-home"
    other_home.mkdir()
    output = tmp_path / "request.json"

    code = main(
        [
            "migrate",
            "classify-request",
            "--inventory",
            str(inventory),
            "--output",
            str(output),
            "--home",
            str(other_home),
        ]
    )

    assert code == 2
    assert not output.exists()


def test_valid_response_is_accepted(tmp_path: Path, capsys) -> None:
    request = write_request_fixture(tmp_path)
    response = write_response_fixture(tmp_path)

    code = main(
        [
            "migrate",
            "validate-response",
            "--request",
            str(request),
            "--response",
            str(response),
        ]
    )

    assert code == 0
    assert "1 decisions" in capsys.readouterr().out


def test_invalid_response_never_reaches_planning(tmp_path: Path) -> None:
    request = write_request_fixture(tmp_path)
    response = write_response_fixture(
        tmp_path,
        request_id="migration-wrong-request",
    )

    code = main(
        [
            "migrate",
            "validate-response",
            "--request",
            str(request),
            "--response",
            str(response),
        ]
    )

    assert code == 2


def test_tampered_request_is_rejected_before_response_validation(
    tmp_path: Path,
) -> None:
    request = write_request_fixture(tmp_path)
    payload = json.loads(request.read_text(encoding="utf-8"))
    payload["artifacts"][0]["text"] = "Tampered instructions."
    request.write_text(json.dumps(payload), encoding="utf-8")
    response = write_response_fixture(tmp_path)

    code = main(
        [
            "migrate",
            "validate-response",
            "--request",
            str(request),
            "--response",
            str(response),
        ]
    )

    assert code == 2
