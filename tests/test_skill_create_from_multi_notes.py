"""Tests for multi-note skill synthesis (`deepvista skill create-from-note`).

Scenarios are inspired by three Lenny's Podcast episodes — April Dunford
(positioning), Shreyas Doshi (PM excellence), and Shishir Mehrotra (product
operating system). The episodes are treated as three separate notes; the
multi-note synthesis should produce a single skill (persona or workflow) that
draws on all three rather than picking one.

Full transcripts live at
https://github.com/ChatPRD/lennys-podcast-transcripts/tree/main/episodes —
we only embed short title + snippet stubs so tests stay hermetic and fast.
"""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from click.testing import CliRunner

from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.commands.skill import (
    _build_create_from_note_prompt,
    _dedupe_pairs,
    _read_ids_from_file,
    _resolve_note_ids,
    skill_create_from_note,
)
from deepvista_cli.config import CLIConfig

# ---------------------------------------------------------------------------
# Fixtures — three Lenny episode stubs treated as notes in the KB
# ---------------------------------------------------------------------------

APRIL_ID = "11111111-1111-4111-8111-111111111111"
SHREYAS_ID = "22222222-2222-4222-8222-222222222222"
SHISHIR_ID = "33333333-3333-4333-8333-333333333333"

LENNY_NOTES: list[dict] = [
    {
        "id": APRIL_ID,
        "type": "note",
        "title": "Lenny × April Dunford — Positioning fixes everything",
        "snippet": (
            "Positioning is the context that makes your product obviously valuable. "
            "Five inputs: competitive alternatives, unique attributes, value, customers, "
            "market category."
        ),
        "tags": ["lenny", "positioning", "marketing"],
    },
    {
        "id": SHREYAS_ID,
        "type": "note",
        "title": "Lenny × Shreyas Doshi — The 3 levels of PM excellence",
        "snippet": (
            "Execution, strategic, and visionary PMs differ in the problems they see. "
            "High-agency PMs exit the bubble and own outcomes, not outputs."
        ),
        "tags": ["lenny", "product-management", "craft"],
    },
    {
        "id": SHISHIR_ID,
        "type": "note",
        "title": "Lenny × Shishir Mehrotra — Rituals + the product operating system",
        "snippet": (
            "DRIs, narratives, and metrics rituals create a company's operating system. "
            "Memos beat slides; prioritization is a language, not an act."
        ),
        "tags": ["lenny", "operating-system", "leadership"],
    },
]

# Fast lookup for the fake client
LENNY_BY_ID = {n["id"]: n for n in LENNY_NOTES}


# ---------------------------------------------------------------------------
# Fake HTTP client — mimics the real DeepVistaClient surface we touch
# ---------------------------------------------------------------------------


class FakeClient:
    """In-memory stand-in for DeepVistaClient.

    Records every call so tests can assert on the requests we made, and returns
    canned responses for the three endpoints the selector resolution uses.
    """

    def __init__(self, cards: list[dict] | None = None) -> None:
        self.cards = cards if cards is not None else list(LENNY_NOTES)
        self.calls: list[tuple[str, dict]] = []
        self.sse_events: list[dict] = []

    def post(self, path: str, body: dict) -> dict:
        self.calls.append((path, dict(body)))
        if path == "/get_context_card":
            cid = body["card_id"]
            return dict(LENNY_BY_ID.get(cid, {"id": cid, "title": "", "snippet": ""}))
        if path == "/get_context_cards":
            # Ignore semantic ranking — return filtered-by-type cards in order.
            results = [c for c in self.cards if body.get("card_type") in (None, c.get("type"))]
            limit = int(body.get("limit", 20))
            return {"cards": results[:limit], "has_more": len(results) > limit}
        if path == "/grep_context_cards":
            # Trivially pretend every card matched, reusing the cards list.
            limit = int(body.get("limit", 20))
            matches = [{"card_id": c["id"], "title": c.get("title", "")} for c in self.cards[:limit]]
            return {"matches": matches}
        raise AssertionError(f"Unexpected POST {path}")

    def stream_sse(self, path: str, body: dict):  # pragma: no cover - unused in tests
        self.calls.append((path, dict(body)))
        yield from self.sse_events


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestDedupePairs:
    def test_preserves_first_seen_order(self) -> None:
        pairs = [("a", ""), ("b", "B"), ("a", "A"), ("c", "C")]
        assert _dedupe_pairs(pairs) == [("a", "A"), ("b", "B"), ("c", "C")]

    def test_later_title_fills_empty(self) -> None:
        # If the positional pass seeded ("id", "") first and the search pass
        # returned a real title later, we should adopt the title.
        assert _dedupe_pairs([("x", ""), ("x", "Real Title")]) == [("x", "Real Title")]

    def test_nonempty_title_is_not_overwritten(self) -> None:
        assert _dedupe_pairs([("x", "Keep"), ("x", "Other")]) == [("x", "Keep")]


class TestReadIdsFromFile:
    def test_reads_one_per_line_skipping_comments_and_blanks(self, tmp_path) -> None:
        f = tmp_path / "ids.txt"
        f.write_text(
            f"""
            # Lenny podcast batch
            {APRIL_ID}

            {SHREYAS_ID}   {SHISHIR_ID}
            # trailing comment
            """
        )
        assert _read_ids_from_file(str(f)) == [APRIL_ID, SHREYAS_ID, SHISHIR_ID]

    def test_stdin_dash(self, monkeypatch) -> None:
        import io

        monkeypatch.setattr("sys.stdin", io.StringIO(f"{APRIL_ID}\n{SHREYAS_ID}\n"))
        assert _read_ids_from_file("-") == [APRIL_ID, SHREYAS_ID]


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


class TestPromptBuilder:
    def test_single_note_prompt_preserves_legacy_wording(self) -> None:
        # Backward-compat guard: the wording here is what agents were trained on
        # for the single-note case. Changing it changes output shape for every
        # existing user, so it's worth pinning.
        prompt = _build_create_from_note_prompt([(APRIL_ID, "")], ("persona",))
        assert f'Look up the note with id "{APRIL_ID}"' in prompt
        assert f'related_context_card_ids=["{APRIL_ID}"]' in prompt
        # Only one note → no multi-note instructions.
        assert "source notes" not in prompt

    def test_multi_note_prompt_lists_every_source(self) -> None:
        notes = [
            (APRIL_ID, LENNY_NOTES[0]["title"]),
            (SHREYAS_ID, LENNY_NOTES[1]["title"]),
            (SHISHIR_ID, LENNY_NOTES[2]["title"]),
        ]
        prompt = _build_create_from_note_prompt(notes, ("persona", "workflow"))
        for nid, title in notes:
            assert nid in prompt
            assert title in prompt
        assert "3 source notes" in prompt
        # Synthesis instructions push the agent to cite + surface tensions
        assert "When they disagree" in prompt
        assert "cite each note" in prompt
        # All three IDs must appear in the related_context_card_ids JSON array
        ids_json = json.dumps([APRIL_ID, SHREYAS_ID, SHISHIR_ID])
        assert f"related_context_card_ids={ids_json}" in prompt

    def test_empty_notes_raises(self) -> None:
        with pytest.raises(ValueError):
            _build_create_from_note_prompt([], ("persona",))


# ---------------------------------------------------------------------------
# Selector resolution
# ---------------------------------------------------------------------------


class TestResolveNoteIds:
    def _resolve(self, client: FakeClient | None = None, **kwargs: Any) -> list[tuple[str, str]]:
        defaults: dict[str, Any] = {
            "positional": (),
            "extra": (),
            "from_file": None,
            "from_search": None,
            "from_similar": None,
            "from_tag": None,
            "from_grep": None,
            "limit": 5,
        }
        defaults.update(kwargs)
        # FakeClient is structurally compatible with DeepVistaClient for the subset
        # of methods the resolver uses — cast to keep pyright happy.
        return _resolve_note_ids(cast(DeepVistaClient | None, client), **defaults)

    def test_positional_only_no_client_needed(self) -> None:
        pairs = self._resolve(positional=(APRIL_ID, SHREYAS_ID))
        assert pairs == [(APRIL_ID, ""), (SHREYAS_ID, "")]

    def test_note_id_flag_merges_with_positional(self) -> None:
        pairs = self._resolve(positional=(APRIL_ID,), extra=(SHREYAS_ID,))
        assert [p[0] for p in pairs] == [APRIL_ID, SHREYAS_ID]

    def test_limit_caps_output(self) -> None:
        pairs = self._resolve(positional=(APRIL_ID, SHREYAS_ID, SHISHIR_ID), limit=2)
        assert len(pairs) == 2

    def test_from_search_hits_hybrid_endpoint(self) -> None:
        client = FakeClient()
        pairs = self._resolve(client, from_search="product management", limit=3)
        assert [p[0] for p in pairs] == [APRIL_ID, SHREYAS_ID, SHISHIR_ID]
        assert client.calls == [
            (
                "/get_context_cards",
                {"query_text": "product management", "card_type": "note", "limit": 3},
            )
        ]

    def test_from_similar_drops_the_seed_itself(self) -> None:
        client = FakeClient()
        pairs = self._resolve(client, from_similar=APRIL_ID, limit=5)
        ids = [p[0] for p in pairs]
        assert APRIL_ID not in ids
        assert SHREYAS_ID in ids and SHISHIR_ID in ids
        # Seed fetch + similarity search ⇒ 2 calls
        assert [c[0] for c in client.calls] == ["/get_context_card", "/get_context_cards"]

    def test_from_tag_filters_client_side(self) -> None:
        client = FakeClient()
        pairs = self._resolve(client, from_tag="operating-system")
        assert [p[0] for p in pairs] == [SHISHIR_ID]

    def test_from_tag_missing_returns_empty(self) -> None:
        pairs = self._resolve(FakeClient(), from_tag="nonexistent-tag")
        assert pairs == []

    def test_positional_and_selector_union(self) -> None:
        """Mixing a manually-pinned seed with a tag selector should merge both."""
        client = FakeClient()
        pairs = self._resolve(client, positional=(APRIL_ID,), from_tag="lenny", limit=10)
        ids = [p[0] for p in pairs]
        # April pinned first, then tag results (which include April — deduped).
        assert ids[0] == APRIL_ID
        assert set(ids) == {APRIL_ID, SHREYAS_ID, SHISHIR_ID}

    def test_client_none_with_api_selector_raises(self) -> None:
        with pytest.raises(RuntimeError):
            self._resolve(client=None, from_search="anything")


# ---------------------------------------------------------------------------
# CLI integration — dry-run so we never need to stream SSE
# ---------------------------------------------------------------------------


def _make_ctx_obj(client: FakeClient) -> CLIConfig:
    cfg = CLIConfig()
    cfg.output_format = "json"
    # Stash the fake client where the command helper expects it.
    cfg._client = client  # type: ignore[attr-defined]
    return cfg


def _invoke_dry_run(client: FakeClient, args: list[str]) -> dict:
    runner = CliRunner()
    result = runner.invoke(
        skill_create_from_note,
        [*args, "--dry-run"],
        obj=_make_ctx_obj(client),
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


class TestCliDryRun:
    def test_single_positional_backward_compat(self) -> None:
        """A single positional ID still goes through the legacy single-note path."""
        payload = _invoke_dry_run(FakeClient(), [APRIL_ID])
        assert payload["dry_run"] is True
        assert payload["note_ids"] == [APRIL_ID]
        assert f'Look up the note with id "{APRIL_ID}"' in payload["payload"]["user_instruction"]

    def test_multiple_positionals_trigger_multi_note_prompt(self) -> None:
        payload = _invoke_dry_run(FakeClient(), [APRIL_ID, SHREYAS_ID, SHISHIR_ID])
        assert payload["note_ids"] == [APRIL_ID, SHREYAS_ID, SHISHIR_ID]
        instruction = payload["payload"]["user_instruction"]
        assert "3 source notes" in instruction
        # Multi-note prompt includes the synthesis instructions.
        assert "When they disagree" in instruction

    def test_from_search_dry_run_resolves_via_fake_client(self) -> None:
        client = FakeClient()
        payload = _invoke_dry_run(client, ["--from-search", "strategic pm", "--limit", "2"])
        assert [n["id"] for n in payload["resolved_notes"]] == [APRIL_ID, SHREYAS_ID]
        # Search endpoint was called exactly once with the expected body.
        assert ("/get_context_cards", {"query_text": "strategic pm", "card_type": "note", "limit": 2}) in client.calls

    def test_from_tag_lenny_picks_up_all_three_episodes(self) -> None:
        client = FakeClient()
        payload = _invoke_dry_run(client, ["--from-tag", "lenny", "--limit", "5"])
        assert {n["id"] for n in payload["resolved_notes"]} == {APRIL_ID, SHREYAS_ID, SHISHIR_ID}

    def test_from_file_reads_ids(self, tmp_path) -> None:
        f = tmp_path / "episodes.txt"
        f.write_text(f"{APRIL_ID}\n{SHREYAS_ID}\n")
        payload = _invoke_dry_run(FakeClient(), ["--from-file", str(f)])
        assert payload["note_ids"] == [APRIL_ID, SHREYAS_ID]

    def test_from_stdin_reads_ids_via_dash(self) -> None:
        runner = CliRunner()
        client = FakeClient()
        result = runner.invoke(
            skill_create_from_note,
            ["--from-file", "-", "--dry-run"],
            obj=_make_ctx_obj(client),
            input=f"{APRIL_ID}\n{SHREYAS_ID}\n",
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["note_ids"] == [APRIL_ID, SHREYAS_ID]

    def test_no_sources_errors(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            skill_create_from_note,
            ["--dry-run"],
            obj=_make_ctx_obj(FakeClient()),
            catch_exceptions=False,
        )
        # output_error exits with the code it was passed (3).
        assert result.exit_code == 3
        err = json.loads(result.output)
        assert err["error"]["message"] == "No source notes resolved"

    def test_invalid_uuid_errors(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            skill_create_from_note,
            ["not-a-uuid", "--dry-run"],
            obj=_make_ctx_obj(FakeClient()),
            catch_exceptions=False,
        )
        assert result.exit_code == 3
        err = json.loads(result.output)
        assert err["error"]["message"] == "Invalid note ID"

    def test_kind_filter_is_respected(self) -> None:
        payload = _invoke_dry_run(FakeClient(), [APRIL_ID, SHREYAS_ID, "--kind", "workflow"])
        assert payload["kinds"] == ["workflow"]
        instruction = payload["payload"]["user_instruction"]
        assert "workflow skill" in instruction
        assert "persona skill" not in instruction
