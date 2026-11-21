from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI

from .api import build_router
from .auth import make_auth
from .providers.base import ProviderClient
from .providers.mock import MockProvider
from .registry import Registry
from .settings import Settings
from .store import create_store


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
    store = create_store(
        backend=settings.db_backend,
        db_path=settings.db_path,
        database_url=settings.database_url,
        seed_dir=settings.modelspecs_dir,
        seed=True,
        pool_min=settings.db_pool_min,
        pool_max=settings.db_pool_max,
        pool_timeout=settings.db_pool_timeout,
    )
    registry = Registry(store)
    provider = _make_provider(settings)
    if not store.list_api_tokens() and settings.bootstrap_tokens:
        store.seed_tokens_from_map(settings.bootstrap_tokens, settings.token_pepper)
    if settings.seed_modelspecs:
        for org in store.list_orgs():
            store.seed_from_directory(settings.modelspecs_dir, org["id"])
    get_auth = make_auth(settings, store)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            store.close()

    app = FastAPI(title="Pigeon", version="0.1.0", lifespan=lifespan)
    app.include_router(build_router(registry, provider, get_auth, settings.token_pepper))
    return app
