"""Host-mode runs are recorded on a run card, never on the workflow card (DV-2895).

`skill run` opens the run and prints its `run_id`; every `skill phase ...` and
`skill complete` call carries it. Without one (a packet from an older CLI) the
commands keep their pre-run-card calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from deepvista_cli.main import cli

SKILL_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
RUN_ID = "11111111-2222-3333-4444-555555555555"

BODY = """## Node Description

<accordion-plain>
Phase 1: Research

1. look around
</accordion-plain>

<accordion-plain open="true">
Phase 2: Draft

1. write it
</accordion-plain>
"""


class _RecordingClient:
    def __init__(self) -> None:
        self.responses: dict[str, Any] = {}
        self.calls: list[tuple[str, dict | None]] = []

    def answer(self, path: str, response: Any) -> None:
        self.responses[path] = response

    def post(self, path: str, body: dict | None = None) -> Any:
        self.calls.append((path, body))
        if path not in self.responses:
            raise AssertionError(f"unexpected POST {path}")
        return self.responses[path]

    def bodies(self, path: str) -> list[dict]:
        return [b or {} for p, b in self.calls if p == path]

    def paths(self) -> list[str]:
        return [p for p, _ in self.calls]


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _RecordingClient:
    monkeypatch.setenv("DEEPVISTA_CONFIG_DIR", str(tmp_path / ".config" / "deepvista"))
    monkeypatch.delenv("DEEPVISTA_RUN_ID", raising=False)
    import importlib

    import deepvista_cli.config as cfg_module

    importlib.reload(cfg_module)

    stub = _RecordingClient()
    stub.answer("/get_context_card", {"id": SKILL_ID, "title": "Demo", "description": BODY, "status": ""})
    stub.answer("/workflow_phase", {"id": SKILL_ID, "title": "Demo"})
    stub.answer("/update_context_card", {"id": SKILL_ID})

    from deepvista_cli.client import http as http_module

    monkeypatch.setattr(http_module.DeepVistaClient, "__init__", lambda self, config: setattr(self, "config", config))
    monkeypatch.setattr(
        http_module.DeepVistaClient,
        "post",
        lambda self, path, body=None, extra_headers=None: stub.post(path, body),
    )
    return stub


def _open_answer(stub: _RecordingClient, *, active_node: str = "Input", resumed: bool = False) -> None:
    stub.answer(
        "/open_workflow_run",
        {
            "run": {"id": RUN_ID, "workflow_id": SKILL_ID, "status": "running", "active_node": active_node},
            "resumed": resumed,
        },
    )


def _header(output: str) -> dict:
    return json.loads(output.splitlines()[0])


# ── skill run ────────────────────────────────────────────────────────────────


def test_run_opens_a_run_and_never_writes_the_workflow_card(client: _RecordingClient) -> None:
    _open_answer(client)
    result = CliRunner().invoke(cli, ["skill", "run", SKILL_ID, "--input", "Focus on Q4"])

    assert result.exit_code == 0, result.output
    assert "/update_context_card" not in client.paths()
    assert client.bodies("/open_workflow_run") == [{"card_id": SKILL_ID, "user_input": "Focus on Q4"}]
    header = _header(result.output)
    assert header["run_id"] == RUN_ID
    assert header["resume_with"] == f"deepvista skill run {SKILL_ID} --run-id {RUN_ID}"
    # A fresh run starts at the first phase, whatever the body's accordions say.
    assert header["active_phase"] == "Phase 1: Research"
    assert [p["state"] for p in header["phases"]] == ["active", "pending"]


def test_run_records_the_machine_driving_it(client: _RecordingClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import deepvista_cli.commands.skill as skill_module

    monkeypatch.setenv("DEEPVISTA_PROJECT_ID", "proj-1")
    monkeypatch.setattr(skill_module, "_load_machine_id", lambda project_id: f"machine-of-{project_id}")
    _open_answer(client)
    result = CliRunner().invoke(cli, ["skill", "run", SKILL_ID])

    assert result.exit_code == 0, result.output
    assert client.bodies("/open_workflow_run")[0]["agent_id"] == "machine-of-proj-1"


def test_run_with_a_run_id_resumes_where_the_run_stands(client: _RecordingClient) -> None:
    _open_answer(client, active_node="Phase 2: Draft", resumed=True)
    result = CliRunner().invoke(cli, ["skill", "run", SKILL_ID, "--run-id", RUN_ID])

    assert result.exit_code == 0, result.output
    assert client.bodies("/open_workflow_run")[0]["run_id"] == RUN_ID
    header = _header(result.output)
    assert (header["active_phase"], header["resumed"]) == ("Phase 2: Draft", True)
    assert [p["state"] for p in header["phases"]] == ["done", "active"]


def test_run_dry_run_opens_nothing(client: _RecordingClient) -> None:
    result = CliRunner().invoke(cli, ["skill", "run", SKILL_ID, "--dry-run"])

    assert result.exit_code == 0, result.output
    assert client.paths() == ["/get_context_card"]


# ── skill phase ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["open", SKILL_ID, "Phase 1: Research"], {"action": "open", "phase_label": "Phase 1: Research"}),
        (
            ["done", SKILL_ID, "Phase 1: Research", "--next-phase", "Phase 2: Draft", "--artifact-card-id", "art-1"],
            {"action": "done", "next_phase": "Phase 2: Draft", "artifact_card_ids": ["art-1"]},
        ),
        (["note", SKILL_ID, "Phase 1: Research", "halfway"], {"action": "note", "note_text": "halfway"}),
    ],
)
def test_phase_commands_record_on_the_run(client: _RecordingClient, argv: list[str], expected: dict) -> None:
    result = CliRunner().invoke(cli, ["skill", "phase", *argv, "--run-id", RUN_ID])

    assert result.exit_code == 0, result.output
    (body,) = client.bodies("/workflow_phase")
    assert body["run_id"] == RUN_ID
    assert expected.items() <= body.items()
    assert "/update_context_card" not in client.paths()


def test_the_run_id_can_come_from_the_environment(client: _RecordingClient) -> None:
    result = CliRunner().invoke(
        cli, ["skill", "phase", "open", SKILL_ID, "Phase 1: Research"], env={"DEEPVISTA_RUN_ID": RUN_ID}
    )

    assert result.exit_code == 0, result.output
    assert client.bodies("/workflow_phase")[0]["run_id"] == RUN_ID


def test_without_a_run_id_the_legacy_call_is_kept_and_flagged(client: _RecordingClient) -> None:
    result = CliRunner().invoke(cli, ["skill", "phase", "open", SKILL_ID, "Phase 1: Research"])

    assert result.exit_code == 0, result.output
    (body,) = client.bodies("/workflow_phase")
    assert "run_id" not in body
    assert "without --run-id" in result.stderr


def test_a_run_has_no_phase_to_reset(client: _RecordingClient) -> None:
    result = CliRunner().invoke(cli, ["skill", "phase", "reset", SKILL_ID, "Phase 1: Research", "--run-id", RUN_ID])

    assert result.exit_code != 0
    assert "/workflow_phase" not in client.paths()


def test_pause_marks_the_run_waiting_without_reading_the_body(client: _RecordingClient) -> None:
    result = CliRunner().invoke(
        cli, ["skill", "phase", "pause", SKILL_ID, "--reason", "Gmail down", "--run-id", RUN_ID]
    )

    assert result.exit_code == 2
    assert client.paths() == ["/workflow_phase"]
    body = client.bodies("/workflow_phase")[0]
    assert (body["action"], body["phase_label"], body["note_text"], body["run_id"]) == (
        "need_input",
        "",
        "Gmail down",
        RUN_ID,
    )
    assert f"--run-id {RUN_ID}" in result.output


def test_need_input_marks_the_phase_on_the_run(client: _RecordingClient) -> None:
    result = CliRunner().invoke(
        cli,
        ["skill", "phase", "need-input", SKILL_ID, "Phase 2: Draft", "--reason", "which audience?", "--run-id", RUN_ID],
    )

    assert result.exit_code == 2
    body = client.bodies("/workflow_phase")[0]
    assert (body["action"], body["phase_label"], body["note_text"]) == (
        "need_input",
        "Phase 2: Draft",
        "which audience?",
    )


# ── skill complete ───────────────────────────────────────────────────────────


def test_complete_finishes_the_run_and_leaves_the_workflow_card_alone(client: _RecordingClient) -> None:
    client.answer("/finish_workflow_run", {"run": {"id": RUN_ID, "status": "done"}})
    result = CliRunner().invoke(cli, ["skill", "complete", SKILL_ID, "--review", "- shipped", "--run-id", RUN_ID])

    assert result.exit_code == 0, result.output
    assert client.paths() == ["/finish_workflow_run"]
    assert client.bodies("/finish_workflow_run")[0] == {
        "card_id": SKILL_ID,
        "run_id": RUN_ID,
        "outcome": "done",
        "summary": "- shipped",
    }
    assert json.loads(result.output)["done"] is True


def test_complete_can_close_a_run_as_failed(client: _RecordingClient) -> None:
    client.answer("/finish_workflow_run", {"run": {"id": RUN_ID, "status": "error"}})
    result = CliRunner().invoke(
        cli, ["skill", "complete", SKILL_ID, "--review", "no creds", "--outcome", "error", "--run-id", RUN_ID]
    )

    assert result.exit_code == 0, result.output
    assert client.bodies("/finish_workflow_run")[0]["outcome"] == "error"
    assert json.loads(result.output) == {"done": False, "skill_id": SKILL_ID, "run_id": RUN_ID, "status": "error"}


def test_only_a_run_can_end_in_error(client: _RecordingClient) -> None:
    result = CliRunner().invoke(cli, ["skill", "complete", SKILL_ID, "--review", "x", "--outcome", "error"])

    assert result.exit_code != 0
    assert client.paths() == []


def test_complete_without_a_run_id_keeps_the_legacy_release(client: _RecordingClient) -> None:
    result = CliRunner().invoke(cli, ["skill", "complete", SKILL_ID, "--review", "- shipped"])

    assert result.exit_code == 0, result.output
    (body,) = client.bodies("/update_context_card")
    assert body["status"] == "completed"
    assert "/finish_workflow_run" not in client.paths()
