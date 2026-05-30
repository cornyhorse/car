from __future__ import annotations

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import DataTable, Footer, Header, Static, Tree

from car.openrouter import ModelEntry


class ModelPicked(Message):
    def __init__(self, model_id: str, provider: str) -> None:
        self.model_id = model_id
        self.provider = provider
        super().__init__()


class CarTui(App[tuple[str, str | None] | None]):  # pragma: no cover
    CSS = """
    Screen { layout: vertical; }
    #content { height: 1fr; }
    #providers { width: 30%; border: solid #666; }
    #models { width: 70%; border: solid #666; }
    #status { height: 3; content-align: left middle; border-top: solid #444; }
    """

    BINDINGS = [
        Binding("enter", "pick_model", "Select Model"),
        Binding("l", "toggle_lock", "Toggle Provider Lock"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        models: list[ModelEntry],
        selected_model: str | None,
        provider_lock: str | None,
    ) -> None:
        super().__init__()
        self.models = models
        self.selected_model = selected_model
        self.provider_lock = provider_lock
        self.current_provider_filter = provider_lock
        self.selected_provider_for_lock: str | None = provider_lock

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="content"):
            yield Tree("Providers", id="providers")
            table = DataTable(id="models")
            table.cursor_type = "row"
            yield table
        yield Static("Ready", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self._build_provider_tree()
        self._setup_table()
        self._load_models()
        self._set_status(
            "Use arrow keys. Enter selects model. L toggles provider lock."
        )

    def _build_provider_tree(self) -> None:
        tree = self.query_one("#providers", Tree)
        root = tree.root
        root.remove_children()
        root.add_leaf("all")

        providers = sorted({m.provider for m in self.models})
        for provider in providers:
            root.add_leaf(provider)
        root.expand()

    def _setup_table(self) -> None:
        table = self.query_one("#models", DataTable)
        table.clear(columns=True)
        table.add_columns(
            "Model", "Provider", "Prompt/$1M", "Complete/$1M", "Context"
        )

    def _load_models(self) -> None:
        table = self.query_one("#models", DataTable)
        table.clear()

        filtered = self.models
        if self.current_provider_filter:
            filtered = [
                m for m in self.models
                if m.provider == self.current_provider_filter
            ]

        for model in filtered:
            table.add_row(
                model.model_id,
                model.provider,
                _fmt_price(model.prompt_per_million),
                _fmt_price(model.completion_per_million),
                str(model.context_length or "-"),
            )

        if filtered:
            idx = 0
            for i, model in enumerate(filtered):
                if model.model_id == self.selected_model:
                    idx = i
                    break
            table.move_cursor(row=idx, column=0)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        label = str(event.node.label)
        self.current_provider_filter = None if label == "all" else label
        self.selected_provider_for_lock = self.current_provider_filter
        self._load_models()
        self._set_status(f"Provider filter: {label}")

    def action_pick_model(self) -> None:
        table = self.query_one("#models", DataTable)
        coord = table.cursor_coordinate
        if coord.row is None:
            self._set_status("No model selected")
            return

        row_key = table.get_row_at(coord.row)
        model_id = str(row_key[0])
        provider = str(row_key[1])
        self.selected_model = model_id
        self.post_message(ModelPicked(model_id, provider))
        self.exit((model_id, self.provider_lock))

    def action_toggle_lock(self) -> None:
        provider = self.selected_provider_for_lock
        if not provider:
            self.provider_lock = None
            self._set_status("Provider lock cleared")
            return

        if self.provider_lock == provider:
            self.provider_lock = None
            self._set_status(f"Provider lock removed: {provider}")
        else:
            self.provider_lock = provider
            self._set_status(f"Provider lock enabled: {provider}")

    def _set_status(self, value: str) -> None:
        self.query_one("#status", Static).update(Text(value))


def _fmt_price(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.4f}"


def run_tui(
    models: list[ModelEntry],
    selected_model: str | None,
    provider_lock: str | None,
) -> tuple[str, str | None] | None:
    app = CarTui(
        models=models,
        selected_model=selected_model,
        provider_lock=provider_lock,
    )
    return app.run()
