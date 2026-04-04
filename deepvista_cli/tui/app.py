"""DeepVista Terminal UI.

Launch with: deepvista ui
Requires:    pip install 'deepvista-cli[ui]'

Four modules: Chat · Notes · Recipes · Memory
"""

from __future__ import annotations

import json
from typing import Any

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Markdown,
    Static,
    TabbedContent,
    TabPane,
)

from deepvista_cli.client.http import DeepVistaClient
from deepvista_cli.config import CLIConfig


# ---------------------------------------------------------------------------
# TUI-safe client: raises exceptions instead of calling sys.exit()
# ---------------------------------------------------------------------------


class _TUIClient(DeepVistaClient):
    """DeepVistaClient that raises RuntimeError instead of calling sys.exit().

    The base client calls sys.exit() on auth/API/network errors, which would
    kill the entire TUI process. This subclass raises exceptions that the TUI
    workers catch and display as inline error messages.
    """

    def _auth_headers(self) -> dict[str, str]:
        from deepvista_cli.auth.tokens import get_valid_token
        from deepvista_cli.config import credentials_path

        headers: dict[str, str] = {"Content-Type": "application/json"}
        tokens = get_valid_token(credentials_path(self.config.profile))
        if tokens is not None and tokens.access_token:
            headers["Authorization"] = f"Bearer {tokens.access_token}"
            return headers
        raise RuntimeError("Not authenticated — run: deepvista auth login")

    def _handle_network_error(self, exc: Any) -> None:  # type: ignore[override]
        import httpx
        if isinstance(exc, httpx.ConnectError):
            raise RuntimeError(f"Cannot connect to {self.config.api_url}") from exc
        raise RuntimeError(f"Request timed out: {self.config.api_url}") from exc

    def _handle_error(self, resp: Any) -> None:  # type: ignore[override]
        try:
            body = resp.json()
            detail = body.get("detail", body.get("message", resp.text))
        except Exception:
            detail = resp.text
        raise RuntimeError(f"API {resp.status_code}: {detail}")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _short(text: str, max_len: int = 60) -> str:
    """Truncate text to max_len characters."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


# ---------------------------------------------------------------------------
# Notes panel
# ---------------------------------------------------------------------------


class NotesPanel(Container):
    """Notes panel — explicit knowledge managed by the user."""

    DEFAULT_CSS = """
    NotesPanel {
        layout: horizontal;
        height: 1fr;
    }
    NotesPanel #notes-list-pane {
        width: 35;
        border-right: solid $panel;
    }
    NotesPanel #notes-content-pane {
        width: 1fr;
        padding: 1 2;
    }
    NotesPanel .panel-title {
        background: $panel;
        padding: 0 1;
        text-style: bold;
    }
    NotesPanel #notes-search {
        margin: 0 1 1 1;
    }
    """

    selected_note: reactive[dict | None] = reactive(None)

    def __init__(self, cli_config: CLIConfig, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._config = cli_config
        self._notes: list[dict] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="notes-list-pane"):
            yield Static("  Notes", classes="panel-title")
            yield Input(placeholder="Search notes…", id="notes-search")
            yield ListView(id="notes-listview")
        with ScrollableContainer(id="notes-content-pane"):
            yield Markdown("*Select a note to view its content.*", id="notes-content-md")

    def on_mount(self) -> None:
        self.load_notes()

    @work(thread=True)
    def load_notes(self, query: str = "") -> None:
        client = _TUIClient(self._config)
        body: dict = {"card_type": "note", "limit": 50, "page_number": 1}
        if query:
            body["query_text"] = query
        try:
            data = client.post("/get_context_cards", body)
            self._notes = data.get("cards", [])
        except BaseException as e:
            self._notes = []
            self.app.call_from_thread(
                self.query_one("#notes-content-md", Markdown).update,
                f"*Error loading notes: {e}*",
            )
        self.app.call_from_thread(self._refresh_list)

    def _refresh_list(self) -> None:
        lv = self.query_one("#notes-listview", ListView)
        lv.remove_children()
        if not self._notes:
            lv.append(ListItem(Label("No notes found.")))
            return
        for note in self._notes:
            item = ListItem(Label(_short(note.get("title", "(untitled)"), 30)))
            item._note_id = note["id"]  # type: ignore[attr-defined]
            lv.append(item)

    @on(Input.Submitted, "#notes-search")
    def search_notes(self, event: Input.Submitted) -> None:
        self.load_notes(query=event.value)

    @on(ListView.Selected, "#notes-listview")
    def note_selected(self, event: ListView.Selected) -> None:
        note_id = getattr(event.item, "_note_id", None)
        if not note_id:
            return
        note = next((n for n in self._notes if n["id"] == note_id), None)
        if note:
            self.selected_note = note
            self._show_note(note)

    def _show_note(self, note: dict) -> None:
        title = note.get("title", "")
        content = note.get("description", note.get("snippet", ""))
        updated = note.get("updated_at", "")
        tags = ", ".join(note.get("tags", []))
        md = f"# {title}\n\n"
        if tags:
            md += f"**Tags:** {tags}\n\n"
        if updated:
            md += f"*Updated: {updated}*\n\n---\n\n"
        md += content or "*No content.*"
        self.query_one("#notes-content-md", Markdown).update(md)


# ---------------------------------------------------------------------------
# Recipes panel
# ---------------------------------------------------------------------------


class RecipesPanel(Container):
    """Recipes panel — structured executable workflows."""

    DEFAULT_CSS = """
    RecipesPanel {
        layout: horizontal;
        height: 1fr;
    }
    RecipesPanel #recipes-list-pane {
        width: 35;
        border-right: solid $panel;
    }
    RecipesPanel #recipes-detail-pane {
        width: 1fr;
        padding: 1 2;
    }
    RecipesPanel .panel-title {
        background: $panel;
        padding: 0 1;
        text-style: bold;
    }
    RecipesPanel #run-btn {
        margin-top: 1;
        width: 20;
    }
    RecipesPanel #run-output {
        height: 1fr;
        border: solid $panel;
        padding: 1;
        margin-top: 1;
        overflow-y: scroll;
    }
    """

    def __init__(self, cli_config: CLIConfig, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._config = cli_config
        self._recipes: list[dict] = []
        self._selected_recipe: dict | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="recipes-list-pane"):
            yield Static("  Recipes", classes="panel-title")
            yield ListView(id="recipes-listview")
        with Vertical(id="recipes-detail-pane"):
            yield Markdown("*Select a recipe to view details.*", id="recipe-detail-md")
            yield Button("▶  Run Recipe", id="run-btn", variant="success", disabled=True)
            yield Static("", id="run-output")

    def on_mount(self) -> None:
        self.load_recipes()

    @work(thread=True)
    def load_recipes(self) -> None:
        client = _TUIClient(self._config)
        try:
            data = client.post("/get_context_cards", {"card_type": "vistabook", "limit": 50, "page_number": 1})
            self._recipes = data.get("cards", [])
        except BaseException as e:
            self._recipes = []
            self.app.call_from_thread(
                self.query_one("#recipe-detail-md", Markdown).update,
                f"*Error loading recipes: {e}*",
            )
        self.app.call_from_thread(self._refresh_list)

    def _refresh_list(self) -> None:
        lv = self.query_one("#recipes-listview", ListView)
        lv.remove_children()
        if not self._recipes:
            lv.append(ListItem(Label("No recipes found.")))
            return
        for recipe in self._recipes:
            item = ListItem(Label(_short(recipe.get("title", "(untitled)"), 30)))
            item._recipe_id = recipe["id"]  # type: ignore[attr-defined]
            lv.append(item)

    @on(ListView.Selected, "#recipes-listview")
    def recipe_selected(self, event: ListView.Selected) -> None:
        recipe_id = getattr(event.item, "_recipe_id", None)
        if not recipe_id:
            return
        recipe = next((r for r in self._recipes if r["id"] == recipe_id), None)
        if recipe:
            self._selected_recipe = recipe
            title = recipe.get("title", "")
            content = recipe.get("description", recipe.get("snippet", ""))
            updated = recipe.get("updated_at", "")
            md = f"# {title}\n\n"
            if updated:
                md += f"*Updated: {updated}*\n\n---\n\n"
            md += content or "*No description.*"
            self.query_one("#recipe-detail-md", Markdown).update(md)
            self.query_one("#run-btn", Button).disabled = False
            self.query_one("#run-output", Static).update("")

    @on(Button.Pressed, "#run-btn")
    def run_recipe(self) -> None:
        if not self._selected_recipe:
            return
        recipe_id = self._selected_recipe["id"]
        self.query_one("#run-btn", Button).disabled = True
        self.query_one("#run-output", Static).update("Running…")
        self._run_recipe_worker(recipe_id)

    @work(thread=True)
    def _run_recipe_worker(self, recipe_id: str) -> None:
        client = _TUIClient(self._config)
        lines: list[str] = []
        try:
            body = {"user_instruction": f"[vistabook:{recipe_id}] Run this recipe"}
            for event in client.stream_sse("/imagine", body):
                text = event.get("text", event.get("content", ""))
                if text:
                    lines.append(text)
                    self.app.call_from_thread(
                        self.query_one("#run-output", Static).update, "\n".join(lines[-30:])
                    )
        except BaseException as e:
            lines.append(f"Error: {e}")
            self.app.call_from_thread(self.query_one("#run-output", Static).update, "\n".join(lines))
        self.app.call_from_thread(self.query_one("#run-btn", Button).__setattr__, "disabled", False)


# ---------------------------------------------------------------------------
# Memory panel
# ---------------------------------------------------------------------------


class MemoryPanel(Container):
    """Memory panel — implicit context automatically accumulated from Chat."""

    DEFAULT_CSS = """
    MemoryPanel {
        layout: vertical;
        height: 1fr;
        padding: 1 2;
    }
    MemoryPanel .panel-title {
        text-style: bold;
        margin-bottom: 1;
    }
    MemoryPanel .memory-note {
        color: $text-muted;
        margin-bottom: 1;
        text-style: italic;
    }
    MemoryPanel #memory-search {
        margin-bottom: 1;
    }
    MemoryPanel #memory-results {
        height: 1fr;
        overflow-y: scroll;
    }
    MemoryPanel .memory-entry {
        border: solid $panel;
        padding: 1;
        margin-bottom: 1;
    }
    """

    def __init__(self, cli_config: CLIConfig, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._config = cli_config

    def compose(self) -> ComposeResult:
        yield Static("Memory Context", classes="panel-title")
        yield Static(
            "Memory is automatically built from your Chat conversations — read-only.",
            classes="memory-note",
        )
        yield Input(placeholder="Search memory…", id="memory-search")
        yield ScrollableContainer(id="memory-results")

    def on_mount(self) -> None:
        self.load_memory()

    @work(thread=True)
    def load_memory(self, query: str = "") -> None:
        client = _TUIClient(self._config)
        entries: list[dict] = []
        try:
            if query:
                data = client.post("/memory/search", {"query": query, "limit": 20})
                entries = data.get("entries", data.get("results", []))
            else:
                data = client.get("/memory/summary", params={"limit": 20})
                entries = data.get("entries", data.get("items", []))
        except RuntimeError as e:
            err = str(e)
            if "404" in err or "Not Found" in err:
                # Memory API not yet available — fall back to recent chat sessions
                try:
                    data = client.post("/get_chat_sessions", {"limit": 20, "offset": 0})
                    for s in data.get("sessions", []):
                        summary = s.get("summary", "")
                        if summary:
                            entries.append({
                                "summary": summary,
                                "source": "chat",
                                "created_at": s.get("created_at", ""),
                            })
                except BaseException:
                    pass
                if not entries:
                    entries = [{"summary": "Memory will appear here as you use Chat.", "source": "info"}]
            else:
                entries = [{"summary": f"Error: {err}", "source": "error"}]
        except BaseException as e:
            entries = [{"summary": f"Error: {e}", "source": "error"}]
        self.app.call_from_thread(self._render_entries, entries, query)

    def _render_entries(self, entries: list[dict], query: str) -> None:
        container = self.query_one("#memory-results", ScrollableContainer)
        container.remove_children()
        if not entries:
            container.mount(Static("No memory entries found.", classes="memory-note"))
            return
        for entry in entries:
            source = entry.get("source", "")
            summary = entry.get("summary", entry.get("title", entry.get("content", "")))
            created = entry.get("created_at", "")

            if source == "info":
                container.mount(Static(summary, classes="memory-note"))
                continue

            text = f"**{_short(summary, 80)}**"
            if source and source not in ("error",):
                text += f"\n*{source}*"
            if created:
                text += f"  ·  {created[:10]}"
            container.mount(Markdown(text, classes="memory-entry"))

    @on(Input.Submitted, "#memory-search")
    def search_memory(self, event: Input.Submitted) -> None:
        self.load_memory(query=event.value)


# ---------------------------------------------------------------------------
# Chat panel
# ---------------------------------------------------------------------------


class ChatPanel(Container):
    """Chat panel — main conversational entry point."""

    DEFAULT_CSS = """
    ChatPanel {
        layout: horizontal;
        height: 1fr;
    }
    ChatPanel #chat-sessions-pane {
        width: 32;
        border-right: solid $panel;
    }
    ChatPanel #chat-main-pane {
        width: 1fr;
        layout: vertical;
    }
    ChatPanel .panel-title {
        background: $panel;
        padding: 0 1;
        text-style: bold;
    }
    ChatPanel #chat-messages {
        height: 1fr;
        overflow-y: scroll;
        padding: 1 2;
    }
    ChatPanel .message-user {
        background: $primary 20%;
        padding: 0 1;
        margin: 0 0 1 4;
        border-left: solid $primary;
    }
    ChatPanel .message-agent {
        background: $surface;
        padding: 0 1;
        margin: 0 4 1 0;
        border-left: solid $secondary;
    }
    ChatPanel #chat-input-bar {
        height: auto;
        layout: horizontal;
        padding: 1;
        border-top: solid $panel;
    }
    ChatPanel #chat-input {
        width: 1fr;
    }
    ChatPanel #send-btn {
        width: 10;
        margin-left: 1;
    }
    """

    def __init__(self, cli_config: CLIConfig, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._config = cli_config
        self._sessions: list[dict] = []
        self._current_chat_id: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="chat-sessions-pane"):
            yield Static("  Sessions", classes="panel-title")
            yield ListView(id="sessions-listview")
        with Vertical(id="chat-main-pane"):
            yield ScrollableContainer(id="chat-messages")
            with Horizontal(id="chat-input-bar"):
                yield Input(placeholder="Type a message… (Enter to send)", id="chat-input")
                yield Button("Send", id="send-btn", variant="primary")

    def on_mount(self) -> None:
        self.load_sessions()
        self._append_message("agent", "Hello! Start a new conversation or select a session from the left.")

    @work(thread=True)
    def load_sessions(self) -> None:
        client = _TUIClient(self._config)
        try:
            data = client.post("/get_chat_sessions", {"limit": 30, "offset": 0})
            self._sessions = data.get("sessions", [])
        except BaseException as e:
            self._sessions = []
            self.app.call_from_thread(self._append_message, "agent", f"Could not load sessions: {e}")
        self.app.call_from_thread(self._refresh_sessions)

    def _refresh_sessions(self) -> None:
        lv = self.query_one("#sessions-listview", ListView)
        lv.remove_children()
        new_item = ListItem(Label("+ New Chat"), classes="new-chat-item")
        lv.append(new_item)
        for s in self._sessions:
            summary = _short(s.get("summary", "(no summary)"), 26)
            item = ListItem(Label(summary))
            item._session_id = s["id"]  # type: ignore[attr-defined]
            lv.append(item)

    @on(ListView.Selected, "#sessions-listview")
    def session_selected(self, event: ListView.Selected) -> None:
        if event.item.has_class("new-chat-item"):
            self._current_chat_id = None
            msgs = self.query_one("#chat-messages", ScrollableContainer)
            msgs.remove_children()
            self._append_message("agent", "New conversation started. Say something!")
        else:
            chat_id = getattr(event.item, "_session_id", None)
            if chat_id:
                self._current_chat_id = chat_id
                self.load_chat(chat_id)

    @work(thread=True)
    def load_chat(self, chat_id: str) -> None:
        client = _TUIClient(self._config)
        try:
            data = client.get(f"/chat_sessions/{chat_id}")
            session = data.get("session", data)
            summary = session.get("summary", "")
            created = (session.get("created_at", "") or "")[:10]
            msgs: list[dict] = [
                {
                    "role": "agent",
                    "content": f"**{summary}**\n\n*Session {chat_id[:8]}…  ·  {created}*\n\nContinue this conversation below.",
                }
            ]
        except BaseException as e:
            msgs = [{"role": "agent", "content": f"Error loading chat: {e}"}]
        self.app.call_from_thread(self._render_messages, msgs)

    def _render_messages(self, msgs: list[dict]) -> None:
        container = self.query_one("#chat-messages", ScrollableContainer)
        container.remove_children()
        for msg in msgs:
            role = msg.get("role", "agent")
            content = msg.get("content", "")
            css_class = "message-user" if role == "user" else "message-agent"
            container.mount(Markdown(content, classes=css_class))
        container.scroll_end(animate=False)

    def _append_message(self, role: str, content: str) -> None:
        container = self.query_one("#chat-messages", ScrollableContainer)
        css_class = "message-user" if role == "user" else "message-agent"
        container.mount(Markdown(content, classes=css_class))
        container.scroll_end(animate=False)

    @on(Button.Pressed, "#send-btn")
    def send_message_btn(self) -> None:
        self._send()

    @on(Input.Submitted, "#chat-input")
    def send_message_input(self, event: Input.Submitted) -> None:
        self._send()

    def _send(self) -> None:
        inp = self.query_one("#chat-input", Input)
        message = inp.value.strip()
        if not message:
            return
        inp.value = ""
        self._append_message("user", message)
        self.query_one("#send-btn", Button).disabled = True
        self._stream_response(message)

    @work(thread=True)
    def _stream_response(self, message: str) -> None:
        client = _TUIClient(self._config)
        body: dict = {"user_instruction": message}
        if self._current_chat_id:
            body["chat_id"] = self._current_chat_id

        latest_text = ""
        try:
            for event in client.stream_sse("/imagine", body):
                event_type = event.get("type", "")

                # Capture session ID from the first event
                if event_type == "chat_session" and not self._current_chat_id:
                    self._current_chat_id = event.get("id")

                # page_delta carries the streamed response text
                elif event_type == "page_delta":
                    for part in event.get("parts", []):
                        if part.get("type") == "tool_result":
                            output = part.get("output", "")
                            if output and output != latest_text:
                                latest_text = output
                                self.app.call_from_thread(self._update_streaming, latest_text)
        except BaseException as e:
            latest_text = latest_text or f"*Error: {e}*"
            self.app.call_from_thread(self._update_streaming, latest_text or f"*Error: {e}*")

        self.app.call_from_thread(self._finalize_response)

    def _update_streaming(self, text: str) -> None:
        container = self.query_one("#chat-messages", ScrollableContainer)
        children = list(container.children)
        if children and getattr(children[-1], "_is_streaming", False):
            children[-1].update(text)  # type: ignore[union-attr]
        else:
            md = Markdown(text, classes="message-agent")
            md._is_streaming = True  # type: ignore[attr-defined]
            container.mount(md)
        container.scroll_end(animate=False)

    def _finalize_response(self) -> None:
        container = self.query_one("#chat-messages", ScrollableContainer)
        children = list(container.children)
        if children and getattr(children[-1], "_is_streaming", False):
            children[-1]._is_streaming = False  # type: ignore[attr-defined]
        self.query_one("#send-btn", Button).disabled = False
        self.load_sessions()


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------


class DeepVistaApp(App[None]):
    """DeepVista Terminal UI — Chat · Notes · Recipes · Memory."""

    TITLE = "DeepVista"
    SUB_TITLE = "chat · notes · recipes · memory"

    CSS = """
    Screen {
        background: $background;
    }
    TabbedContent {
        height: 1fr;
    }
    TabPane {
        padding: 0;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("1", "switch_tab('chat')", "Chat", show=True),
        Binding("2", "switch_tab('notes')", "Notes", show=True),
        Binding("3", "switch_tab('recipes')", "Recipes", show=True),
        Binding("4", "switch_tab('memory')", "Memory", show=True),
        Binding("r", "refresh", "Refresh", show=True),
    ]

    def __init__(self, cli_config: CLIConfig, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._config = cli_config

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(id="main-tabs"):
            with TabPane("💬 Chat  [1]", id="chat"):
                yield ChatPanel(self._config, id="chat-panel")
            with TabPane("📝 Notes  [2]", id="notes"):
                yield NotesPanel(self._config, id="notes-panel")
            with TabPane("⚡ Recipes  [3]", id="recipes"):
                yield RecipesPanel(self._config, id="recipes-panel")
            with TabPane("🧠 Memory  [4]", id="memory"):
                yield MemoryPanel(self._config, id="memory-panel")
        yield Footer()

    def action_switch_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id

    def action_refresh(self) -> None:
        active = self.query_one(TabbedContent).active
        if active == "notes":
            self.query_one("#notes-panel", NotesPanel).load_notes()
        elif active == "recipes":
            self.query_one("#recipes-panel", RecipesPanel).load_recipes()
        elif active == "memory":
            self.query_one("#memory-panel", MemoryPanel).load_memory()
        elif active == "chat":
            self.query_one("#chat-panel", ChatPanel).load_sessions()
