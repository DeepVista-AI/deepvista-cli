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
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    LoadingIndicator,
    Markdown,
    Static,
    TabbedContent,
    TabPane,
)

from deepvista_cli.config import CLIConfig

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
    NotesPanel .empty-hint {
        color: $text-muted;
        padding: 1 2;
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
            yield Markdown("", id="notes-content-md")

    def on_mount(self) -> None:
        self.load_notes()

    @work(thread=True)
    def load_notes(self, query: str = "") -> None:
        from deepvista_cli.client.http import DeepVistaClient

        client = DeepVistaClient(self._config)
        body: dict = {"card_type": "note", "limit": 50, "page_number": 1}
        if query:
            body["query_text"] = query
        try:
            data = client.post("/get_context_cards", body)
            self._notes = data.get("cards", [])
        except Exception:
            self._notes = []
        self.app.call_from_thread(self._refresh_list)

    def _refresh_list(self) -> None:
        lv = self.query_one("#notes-listview", ListView)
        lv.clear()
        for note in self._notes:
            lv.append(ListItem(Label(_short(note.get("title", "(untitled)"), 30)), id=f"note-{note['id']}"))
        if not self._notes:
            lv.append(ListItem(Label("No notes found."), id="note-empty"))

    @on(Input.Submitted, "#notes-search")
    def search_notes(self, event: Input.Submitted) -> None:
        self.load_notes(query=event.value)

    @on(ListView.Selected, "#notes-listview")
    def note_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        if not item_id.startswith("note-"):
            return
        note_id = item_id[5:]
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
        from deepvista_cli.client.http import DeepVistaClient

        client = DeepVistaClient(self._config)
        try:
            data = client.post("/get_context_cards", {"card_type": "vistabook", "limit": 50, "page_number": 1})
            self._recipes = data.get("cards", [])
        except Exception:
            self._recipes = []
        self.app.call_from_thread(self._refresh_list)

    def _refresh_list(self) -> None:
        lv = self.query_one("#recipes-listview", ListView)
        lv.clear()
        for recipe in self._recipes:
            lv.append(ListItem(Label(_short(recipe.get("title", "(untitled)"), 30)), id=f"recipe-{recipe['id']}"))
        if not self._recipes:
            lv.append(ListItem(Label("No recipes found."), id="recipe-empty"))

    @on(ListView.Selected, "#recipes-listview")
    def recipe_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        if not item_id.startswith("recipe-"):
            return
        recipe_id = item_id[7:]
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
        from deepvista_cli.client.http import DeepVistaClient

        client = DeepVistaClient(self._config)
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
        except Exception as e:
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
        from deepvista_cli.client.http import DeepVistaClient

        client = DeepVistaClient(self._config)
        try:
            if query:
                data = client.post("/memory/search", {"query": query, "limit": 20})
                entries = data.get("entries", data.get("results", []))
            else:
                data = client.get("/memory/summary", params={"limit": 20})
                entries = data.get("entries", data.get("items", []))
        except Exception as e:
            entries = [{"summary": f"Could not load memory: {e}", "source": "error"}]
        self.app.call_from_thread(self._render_entries, entries, query)

    def _render_entries(self, entries: list[dict], query: str) -> None:
        container = self.query_one("#memory-results", ScrollableContainer)
        container.remove_children()
        if not entries:
            container.mount(Static("No memory entries found.", classes="memory-note"))
            return
        for entry in entries:
            summary = entry.get("summary", entry.get("title", entry.get("content", "")))
            source = entry.get("source", "")
            created = entry.get("created_at", "")
            text = f"**{_short(summary, 80)}**"
            if source:
                text += f"\n*Source: {source}*"
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
        self._messages: list[dict] = []

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
        # Show welcome hint
        self._append_message("agent", "Hello! Start a new conversation or select a session from the left.")

    @work(thread=True)
    def load_sessions(self) -> None:
        from deepvista_cli.client.http import DeepVistaClient

        client = DeepVistaClient(self._config)
        try:
            data = client.post("/get_chat_sessions", {"limit": 30, "offset": 0})
            self._sessions = data.get("sessions", [])
        except Exception:
            self._sessions = []
        self.app.call_from_thread(self._refresh_sessions)

    def _refresh_sessions(self) -> None:
        lv = self.query_one("#sessions-listview", ListView)
        lv.clear()
        lv.append(ListItem(Label("+ New Chat"), id="session-new"))
        for s in self._sessions:
            summary = _short(s.get("summary", "(no summary)"), 26)
            lv.append(ListItem(Label(summary), id=f"session-{s['id']}"))

    @on(ListView.Selected, "#sessions-listview")
    def session_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        if item_id == "session-new":
            self._current_chat_id = None
            self._messages = []
            msgs = self.query_one("#chat-messages", ScrollableContainer)
            msgs.remove_children()
            self._append_message("agent", "New conversation started. Say something!")
        elif item_id.startswith("session-"):
            chat_id = item_id[8:]
            self._current_chat_id = chat_id
            self.load_chat(chat_id)

    @work(thread=True)
    def load_chat(self, chat_id: str) -> None:
        from deepvista_cli.client.http import DeepVistaClient

        client = DeepVistaClient(self._config)
        try:
            data = client.get(f"/chat_sessions/{chat_id}")
            session = data.get("session", data)
            pages = session.get("pages", [])
            msgs: list[dict] = []
            for page in pages:
                for msg in page.get("messages", []):
                    msgs.append(msg)
        except Exception as e:
            msgs = [{"role": "system", "content": f"Error loading chat: {e}"}]
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
        from deepvista_cli.client.http import DeepVistaClient

        client = DeepVistaClient(self._config)
        body: dict = {"user_instruction": message}
        if self._current_chat_id:
            body["chat_id"] = self._current_chat_id

        accumulated = ""
        try:
            for event in client.stream_sse("/imagine", body):
                # Track chat_id from response
                if "chat_id" in event and not self._current_chat_id:
                    self._current_chat_id = event["chat_id"]
                text = event.get("text", event.get("content", event.get("delta", "")))
                if text:
                    accumulated += text
                    self.app.call_from_thread(self._update_streaming, accumulated)
        except Exception as e:
            accumulated = f"Error: {e}"
            self.app.call_from_thread(self._update_streaming, accumulated)

        # Finalize
        self.app.call_from_thread(self._finalize_response, accumulated)

    def _update_streaming(self, text: str) -> None:
        """Update the last agent message while streaming."""
        container = self.query_one("#chat-messages", ScrollableContainer)
        children = list(container.children)
        # Check if last child is a streaming placeholder
        if children and hasattr(children[-1], "_is_streaming"):
            children[-1].update(text)
        else:
            md = Markdown(text, classes="message-agent")
            md._is_streaming = True  # type: ignore[attr-defined]
            container.mount(md)
        container.scroll_end(animate=False)

    def _finalize_response(self, text: str) -> None:
        container = self.query_one("#chat-messages", ScrollableContainer)
        children = list(container.children)
        if children and hasattr(children[-1], "_is_streaming"):
            del children[-1]._is_streaming  # type: ignore[attr-defined]
        self.query_one("#send-btn", Button).disabled = False
        # Reload sessions to pick up the new/updated one
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
        """Refresh the active panel."""
        active = self.query_one(TabbedContent).active
        if active == "notes":
            self.query_one("#notes-panel", NotesPanel).load_notes()
        elif active == "recipes":
            self.query_one("#recipes-panel", RecipesPanel).load_recipes()
        elif active == "memory":
            self.query_one("#memory-panel", MemoryPanel).load_memory()
        elif active == "chat":
            self.query_one("#chat-panel", ChatPanel).load_sessions()
