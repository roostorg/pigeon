from __future__ import annotations

from typing import Optional

from fastapi import FastAPI

from .api import build_router
from .auth import make_auth
from .providers.base import ProviderClient
from .providers.mock import MockProvider
from .registry import Registry
from .settings import Settings
from .store import Store


def _make_provider(settings: Settings) -> ProviderClient:
    if settings.provider == "live":
        from .providers.litellm_provider import LiteLLMProvider

        return LiteLLMProvider(media_max_bytes=settings.media_max_bytes)
    if settings.provider == "local":
        from .providers.transformers_provider import TransformersProvider

        return TransformersProvider()
    return MockProvider()


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = Store(
        settings.db_path,
        seed_dir=settings.modelspecs_dir,
        seed=True,
    )
    if settings.seed_modelspecs:
        store.seed_from_directory(settings.modelspecs_dir)
    registry = Registry(store)
    provider = _make_provider(settings)
    get_org = make_auth(settings)

    app = FastAPI(title="Pigeon", version="0.1.0")
    app.include_router(build_router(registry, provider, get_org))
    return app
