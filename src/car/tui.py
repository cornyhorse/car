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


class CarTui(App[tuple[str, str | None, str, list[str]] | None]):  # pragma: no cover
    CSS = """
    Screen { layout: vertical; }
    #content { height: 1fr; }
    #providers { width: 30%; border: solid #666; }
    #models { width: 70%; border: solid #666; }
    #status { height: 3; content-align: left middle; border-top: solid #444; }
    """

    BINDINGS = [
        Binding("enter", "pick_model", "Select Model"),
        Binding("escape", "focus_providers", "Providers"),
        Binding("f", "toggle_favorite", "Toggle Favorite"),
        Binding("l", "toggle_lock", "Toggle Provider Lock"),
        Binding("r", "toggle_route_mode", "Toggle Route Mode"),
        Binding("a", "clear_provider_filter", "All Providers"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        models: list[ModelEntry],
        selected_model: str | None,
        provider_lock: str | None,
        favorite_models: list[str],
        route_mode: str,
    ) -> None:
        super().__init__()
        self.models = models
        self.selected_model = selected_model
        self.provider_lock = provider_lock
        self.favorite_models = list(dict.fromkeys(favorite_models))
        self.route_mode = route_mode if route_mode in {"model", "provider"} else "model"
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
        self.call_after_refresh(self.action_focus_providers)
        self._set_status(
            "Esc=providers Enter=select F=favorite L=provider lock R=route mode A=all"
        )

    def _build_provider_tree(self) -> None:
        tree = self.query_one("#providers", Tree)
        root = tree.root
        root.remove_children()

        favorite_models = [
            model_id for model_id in self.favorite_models
            if any(m.model_id == model_id for m in self.models)
        ]
        if favorite_models:
            favorites_branch = root.add("Favorites")
            for model_id in favorite_models:
                favorites_branch.add_leaf(model_id)
            favorites_branch.expand()

        root.add_leaf("all")

        providers = sorted({m.provider for m in self.models})
        for provider in providers:
            root.add_leaf(provider)
        root.expand()

    def _setup_table(self) -> None:
        table = self.query_one("#models", DataTable)
        table.clear(columns=True)
        table.add_columns(
            "Fav", "Model", "Provider", "Prompt/$1M", "Complete/$1M", "Context"
        )

    def _sorted_models(self, filtered: list[ModelEntry]) -> list[ModelEntry]:
        return sorted(
            filtered,
            key=lambda m: (
                m.model_id not in self.favorite_models,
                m.provider,
                m.model_id,
            ),
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

        filtered = self._sorted_models(filtered)

        for model in filtered:
            table.add_row(
                "*" if model.model_id in self.favorite_models else "",
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
        if label == "Providers":
            self.query_one("#providers", Tree).root.expand()
            self._set_status("Provider list")
            return
        if label == "all":
            self.current_provider_filter = None
            self.selected_provider_for_lock = None
            self._load_models()
            self._set_status("Provider filter: all")
            self.query_one("#models", DataTable).focus()
            return

        if label == "Favorites":
            self._set_status("Select a favorite model")
            return

        if label in self.favorite_models:
            self.current_provider_filter = None
            self.selected_model = label
            self._load_models()
            self._set_status(f"Favorite selected: {label}")
            self.query_one("#models", DataTable).focus()
            return

        self.current_provider_filter = label
        self.selected_provider_for_lock = self.current_provider_filter
        self._load_models()
        self._set_status(f"Provider filter: {label}")
        self.query_one("#models", DataTable).focus()

    def action_focus_providers(self) -> None:
        self.query_one("#providers", Tree).focus()

    def action_focus_models(self) -> None:
        self.query_one("#models", DataTable).focus()

    def action_pick_model(self) -> None:
        table = self.query_one("#models", DataTable)
        coord = table.cursor_coordinate
        if coord.row is None:
            self._set_status("No model selected")
            return

        row_key = table.get_row_at(coord.row)
        model_id = str(row_key[1])
        provider = str(row_key[2])
        self.selected_model = model_id
        provider_lock = self.provider_lock
        if self.route_mode == "model":
            provider_lock = None
        elif self.route_mode == "provider" and not provider_lock:
            provider_lock = provider

        self.post_message(ModelPicked(model_id, provider))
        self.exit((model_id, provider_lock, self.route_mode, self.favorite_models))

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

    def action_toggle_route_mode(self) -> None:
        if self.route_mode == "model":
            self.route_mode = "provider"
            self._set_status("Route mode: provider+model")
        else:
            self.route_mode = "model"
            self._set_status("Route mode: model-only")

    def action_clear_provider_filter(self) -> None:
        self.current_provider_filter = None
        self.selected_provider_for_lock = None
        self._load_models()
        self._set_status("Provider filter: all")

    def action_toggle_favorite(self) -> None:
        table = self.query_one("#models", DataTable)
        coord = table.cursor_coordinate
        if coord.row is None:
            self._set_status("No model selected")
            return

        row_key = table.get_row_at(coord.row)
        model_id = str(row_key[1])

        if model_id in self.favorite_models:
            self.favorite_models = [m for m in self.favorite_models if m != model_id]
            self._set_status(f"Removed favorite: {model_id}")
        else:
            self.favorite_models.append(model_id)
            self._set_status(f"Added favorite: {model_id}")

        self._load_models()

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
    favorite_models: list[str],
    route_mode: str,
) -> tuple[str, str | None, str, list[str]] | None:
    app = CarTui(
        models=models,
        selected_model=selected_model,
        provider_lock=provider_lock,
        favorite_models=favorite_models,
        route_mode=route_mode,
    )
    return app.run()
