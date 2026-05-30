from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from car.paths import ensure_dirs, models_cache_file


@dataclass
class ModelEntry:
    model_id: str
    provider: str
    prompt_per_million: float | None
    completion_per_million: float | None
    context_length: int | None


class OpenRouterError(RuntimeError):
    pass


def _provider_for_model(model_id: str) -> str:
    if "/" in model_id:
        return model_id.split("/", 1)[0]
    return "unknown"


def parse_models(payload: dict[str, Any]) -> list[ModelEntry]:
    rows: list[ModelEntry] = []
    for item in payload.get("data", []):
        model_id = str(item.get("id", "")).strip()
        if not model_id:
            continue

        pricing = item.get("pricing") or {}
        prompt = _to_float(pricing.get("prompt"))
        completion = _to_float(pricing.get("completion"))
        context = _to_int(item.get("context_length"))

        rows.append(
            ModelEntry(
                model_id=model_id,
                provider=_provider_for_model(model_id),
                prompt_per_million=_cost_per_million(prompt),
                completion_per_million=_cost_per_million(completion),
                context_length=context,
            )
        )
    rows.sort(key=lambda x: (x.provider, x.model_id))
    return rows


def refresh_models(
    base_url: str,
    cache_path: Path | None = None,
) -> list[ModelEntry]:
    cache_path = cache_path or models_cache_file()
    ensure_dirs()
    url = f"{base_url.rstrip('/')}/models"
    req = Request(url, headers={"Accept": "application/json"})

    try:
        with urlopen(req, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise OpenRouterError(f"OpenRouter HTTP error: {exc.code}") from exc
    except URLError as exc:
        raise OpenRouterError(
            f"OpenRouter network error: {exc.reason}"
        ) from exc
    except TimeoutError as exc:
        raise OpenRouterError("OpenRouter request timed out") from exc

    rows = parse_models(payload)
    serialized = {
        "refreshed_at": datetime.now(UTC).isoformat(),
        "models": [row.__dict__ for row in rows],
    }
    cache_path.write_text(
        json.dumps(serialized, indent=2) + "\n",
        encoding="utf-8",
    )
    return rows


def load_cached_models(
    cache_path: Path | None = None,
) -> tuple[list[ModelEntry], str | None]:
    cache_path = cache_path or models_cache_file()
    if not cache_path.exists():
        return [], None

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [], None

    rows = [
        ModelEntry(
            model_id=str(item.get("model_id", "")),
            provider=str(item.get("provider", "unknown")),
            prompt_per_million=_to_float(item.get("prompt_per_million")),
            completion_per_million=_to_float(
                item.get("completion_per_million")
            ),
            context_length=_to_int(item.get("context_length")),
        )
        for item in payload.get("models", [])
        if item.get("model_id")
    ]
    rows.sort(key=lambda x: (x.provider, x.model_id))
    return rows, payload.get("refreshed_at")


def filter_models(
    rows: list[ModelEntry],
    provider_lock: str | None,
) -> list[ModelEntry]:
    if not provider_lock:
        return rows
    needle = provider_lock.strip().lower()
    return [row for row in rows if row.provider.lower() == needle]


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _cost_per_million(unit_cost: float | None) -> float | None:
    if unit_cost is None:
        return None
    return unit_cost * 1_000_000
