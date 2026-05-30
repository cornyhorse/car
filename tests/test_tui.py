from __future__ import annotations

from types import SimpleNamespace

from car import tui


class _FakeApp:
    def __init__(self, models, selected_model, provider_lock, favorite_models, route_mode):
        self.models = models
        self.selected_model = selected_model
        self.provider_lock = provider_lock
        self.favorite_models = favorite_models
        self.route_mode = route_mode

    def run(self):
        return ("picked/model", "aws-bedrock", "provider", ["picked/model"])


class _FakeNode:
    def __init__(self, label):
        self.label = label
        self.children = []

    def remove_children(self):
        self.children = []

    def add_leaf(self, label):
        node = _FakeNode(label)
        self.children.append(node)
        return node

    def add(self, label):
        node = _FakeNode(label)
        self.children.append(node)
        return node

    def expand(self):
        return None


class _FakeTree:
    def __init__(self):
        self.root = _FakeNode("root")
        self.focused = False

    def focus(self):
        self.focused = True


class _FakeTable:
    def __init__(self):
        self.rows = []
        self.columns = []
        self.cursor_coordinate = SimpleNamespace(row=0)
        self.focused = False

    def clear(self, columns=False):
        if columns:
            self.columns = []
        self.rows = []

    def add_columns(self, *cols):
        self.columns.extend(cols)

    def add_row(self, *row):
        self.rows.append(row)

    def move_cursor(self, row, column):
        self.cursor_coordinate = SimpleNamespace(row=row, column=column)

    def get_row_at(self, row):
        return self.rows[row]

    def focus(self):
        self.focused = True


class _FakeStatic:
    def __init__(self):
        self.value = None

    def update(self, value):
        self.value = value


class _FakeEvent:
    def __init__(self, label):
        self.node = SimpleNamespace(label=label)


def _fake_tui(models, favorites=None, provider_lock=None, selected_model=None, route_mode="model"):
    app = tui.CarTui.__new__(tui.CarTui)
    app.models = models
    app.selected_model = selected_model
    app.provider_lock = provider_lock
    app.favorite_models = favorites or []
    app.route_mode = route_mode
    app.current_provider_filter = provider_lock
    app.selected_provider_for_lock = provider_lock
    app._tree = _FakeTree()
    app._table = _FakeTable()
    app._status = _FakeStatic()

    def query_one(selector, cls=None):
        if selector == "#providers":
            return app._tree
        if selector == "#models":
            return app._table
        if selector == "#status":
            return app._status
        raise AssertionError(selector)

    app.query_one = query_one
    app.call_after_refresh = lambda func: func()
    app._set_status = lambda value: app._status.update(value)
    app._load_models = lambda: tui.CarTui._load_models(app)
    app._setup_table = lambda: tui.CarTui._setup_table(app)
    app._build_provider_tree = lambda: tui.CarTui._build_provider_tree(app)
    return app


def test_fmt_price():
    assert tui._fmt_price(None) == "-"
    assert tui._fmt_price(1.23456) == "1.2346"


def test_run_tui(monkeypatch):
    monkeypatch.setattr(tui, "CarTui", _FakeApp)
    result = tui.run_tui([], "a/b", None, ["a/b"], "model")
    assert result == ("picked/model", "aws-bedrock", "provider", ["picked/model"])


def test_model_picked_message_fields():
    msg = tui.ModelPicked("m/x", "openai")
    assert msg.model_id == "m/x"
    assert msg.provider == "openai"


def test_provider_tree_places_favorites_above_all():
    app = _fake_tui([
        tui.ModelEntry("a/model", "a", None, None, None),
        tui.ModelEntry("b/model", "b", None, None, None),
    ], favorites=["b/model"])

    app._build_provider_tree()

    labels = [node.label for node in app._tree.root.children]
    assert labels == ["Favorites", "all", "a", "b"]
    assert [node.label for node in app._tree.root.children[0].children] == ["b/model"]


def test_escape_focuses_providers_and_all_clears_filter():
    app = _fake_tui([
        tui.ModelEntry("a/model", "a", None, None, None),
    ], provider_lock="a")
    app._build_provider_tree()
    app._setup_table()
    app._load_models()

    app.action_focus_models()
    assert app._table.focused is True

    app.action_focus_providers()
    assert app._tree.focused is True

    app.on_tree_node_selected(_FakeEvent("all"))
    assert app.current_provider_filter is None
    assert app.selected_provider_for_lock is None

    app.on_tree_node_selected(_FakeEvent("Providers"))
    assert app._status.value == "Provider list"


def test_on_tree_node_selected_favorite_and_provider_paths():
    app = _fake_tui([
        tui.ModelEntry("fav/model", "fav", None, None, None),
        tui.ModelEntry("other/model", "other", None, None, None),
    ], favorites=["fav/model"])
    app._build_provider_tree()
    app._setup_table()
    app._load_models()

    app.on_tree_node_selected(_FakeEvent("Favorites"))
    assert app._status.value == "Select a favorite model"

    app.on_tree_node_selected(_FakeEvent("fav/model"))
    assert app.selected_model == "fav/model"
    assert app._status.value == "Favorite selected: fav/model"

    app.on_tree_node_selected(_FakeEvent("other"))
    assert app.current_provider_filter == "other"
    assert app._status.value == "Provider filter: other"


def test_toggle_favorite_and_route_mode(monkeypatch):
    app = _fake_tui([
        tui.ModelEntry("a/model", "a", None, None, None),
    ])
    app._build_provider_tree()
    app._setup_table()
    app._load_models()

    app.action_toggle_favorite()
    assert app.favorite_models == ["a/model"]
    app.action_toggle_favorite()
    assert app.favorite_models == []

    app.action_toggle_route_mode()
    assert app.route_mode == "provider"
    app.action_toggle_route_mode()
    assert app.route_mode == "model"


def test_pick_model_respects_route_modes():
    app = _fake_tui([
        tui.ModelEntry("a/model", "a", None, None, None),
    ], route_mode="provider")
    app._build_provider_tree()
    app._setup_table()
    app._load_models()

    captured = {}
    app.exit = lambda payload: captured.update({"payload": payload})
    app.post_message = lambda message: None
    app.action_pick_model()
    assert captured["payload"][1] == "a"

    app2 = _fake_tui([
        tui.ModelEntry("a/model", "a", None, None, None),
    ], route_mode="model")
    app2._build_provider_tree()
    app2._setup_table()
    app2._load_models()
    captured2 = {}
    app2.exit = lambda payload: captured2.update({"payload": payload})
    app2.post_message = lambda message: None
    app2.action_pick_model()
    assert captured2["payload"][1] is None
