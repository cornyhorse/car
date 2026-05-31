from __future__ import annotations

import json
from io import BytesIO
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from car import openrouter


class _Resp:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def test_provider_for_model():
    assert openrouter._provider_for_model("aws-bedrock/model") == "aws-bedrock"
    assert openrouter._provider_for_model("nomarker") == "unknown"


def test_parse_models_and_sorting():
    payload = {
        "data": [
            {
                "id": "z/model",
                "pricing": {"prompt": "0.1", "completion": "0.2"},
                "context_length": "4096",
                "top_provider": {"max_completion_tokens": "1024"},
            },
            {
                "id": "a/model",
                "pricing": {"prompt": "", "completion": None},
                "context_length": "",
            },
            {"id": ""},
        ]
    }

    rows = openrouter.parse_models(payload)

    assert [r.model_id for r in rows] == ["a/model", "z/model"]
    assert rows[0].prompt_per_million is None
    assert rows[1].prompt_per_million == 100000.0
    assert rows[1].completion_per_million == 200000.0
    assert rows[1].context_length == 4096
    assert rows[1].max_output_tokens == 1024
    assert rows[1].max_prompt_tokens == 3072


def test_refresh_models_success(monkeypatch, tmp_path):
    cache = tmp_path / "models.json"
    payload = {
        "data": [
            {
                "id": "openai/gpt-4o-mini",
                "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                "context_length": 8192,
            }
        ]
    }

    monkeypatch.setattr(openrouter, "urlopen", lambda *a, **k: _Resp(payload))
    monkeypatch.setattr(openrouter, "ensure_dirs", lambda: None)

    rows = openrouter.refresh_models("https://openrouter.ai/api/v1", cache)

    assert len(rows) == 1
    saved = json.loads(cache.read_text(encoding="utf-8"))
    assert saved["models"][0]["model_id"] == "openai/gpt-4o-mini"
    assert "refreshed_at" in saved


def test_refresh_models_http_error(monkeypatch):
    req = HTTPError("u", 401, "bad", hdrs=None, fp=BytesIO(b""))
    monkeypatch.setattr(openrouter, "urlopen", lambda *a, **k: (_ for _ in ()).throw(req))

    with pytest.raises(openrouter.OpenRouterError, match="HTTP error"):
        openrouter.refresh_models("https://example", Path("/tmp/x"))


def test_refresh_models_url_error(monkeypatch):
    monkeypatch.setattr(
        openrouter,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(URLError("no network")),
    )

    with pytest.raises(openrouter.OpenRouterError, match="network error"):
        openrouter.refresh_models("https://example", Path("/tmp/x"))


def test_refresh_models_timeout(monkeypatch):
    monkeypatch.setattr(
        openrouter,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(TimeoutError()),
    )

    with pytest.raises(openrouter.OpenRouterError, match="timed out"):
        openrouter.refresh_models("https://example", Path("/tmp/x"))


def test_load_cached_models_missing(tmp_path):
    rows, refreshed = openrouter.load_cached_models(tmp_path / "missing.json")
    assert rows == []
    assert refreshed is None


def test_load_cached_models_invalid_json(tmp_path):
    p = tmp_path / "models.json"
    p.write_text("{broken", encoding="utf-8")
    rows, refreshed = openrouter.load_cached_models(p)
    assert rows == []
    assert refreshed is None


def test_load_cached_models_valid_and_sorted(tmp_path):
    p = tmp_path / "models.json"
    p.write_text(
        json.dumps(
            {
                "refreshed_at": "now",
                "models": [
                    {"model_id": "z/m", "provider": "z", "prompt_per_million": "1", "completion_per_million": "2", "context_length": "3", "max_prompt_tokens": "2", "max_output_tokens": "1"},
                    {"model_id": "a/m", "provider": "a", "prompt_per_million": None, "completion_per_million": None, "context_length": None},
                    {"model_id": "", "provider": "a"},
                ],
            }
        ),
        encoding="utf-8",
    )

    rows, refreshed = openrouter.load_cached_models(p)

    assert refreshed == "now"
    assert [r.model_id for r in rows] == ["a/m", "z/m"]
    assert rows[1].prompt_per_million == 1.0
    assert rows[1].context_length == 3
    assert rows[1].max_prompt_tokens == 2
    assert rows[1].max_output_tokens == 1


def test_filter_models_case_insensitive():
    rows = [
        openrouter.ModelEntry("a/x", "aws-bedrock", None, None, None),
        openrouter.ModelEntry("o/y", "openai", None, None, None),
    ]

    filtered = openrouter.filter_models(rows, "AWS-BEDROCK")
    passthrough = openrouter.filter_models(rows, None)

    assert [r.provider for r in filtered] == ["aws-bedrock"]
    assert passthrough == rows


def test_conversion_helpers():
    assert openrouter._to_float("1.5") == 1.5
    assert openrouter._to_float("") is None
    assert openrouter._to_float("bad") is None

    assert openrouter._to_int("2") == 2
    assert openrouter._to_int("") is None
    assert openrouter._to_int("bad") is None

    assert openrouter._cost_per_million(None) is None
    assert openrouter._cost_per_million(0.000001) == 1.0


def test_derive_max_prompt_tokens():
    assert openrouter._derive_max_prompt_tokens(None, 100) is None
    assert openrouter._derive_max_prompt_tokens(4096, None) == 4096
    assert openrouter._derive_max_prompt_tokens(4096, 1024) == 3072
    assert openrouter._derive_max_prompt_tokens(100, 1000) == 1


def test_cache_is_stale_behaviors():
    now = datetime.now(UTC)
    fresh = (now - timedelta(hours=2)).isoformat()
    stale = (now - timedelta(hours=30)).isoformat()

    assert openrouter.cache_is_stale(fresh, max_age_hours=24) is False
    assert openrouter.cache_is_stale(stale, max_age_hours=24) is True
    assert openrouter.cache_is_stale("2020-01-01T00:00:00", max_age_hours=24) is True
    assert openrouter.cache_is_stale(None, max_age_hours=24) is True
    assert openrouter.cache_is_stale("not-a-date", max_age_hours=24) is True
