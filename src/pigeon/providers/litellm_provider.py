from __future__ import annotations

from typing import Any, Optional

import httpx

from ..modelspecs import ModelSpec
from ..urls import validate_inference_endpoint, validate_media_url

# LiteLLM model-name prefixes per runtime. See https://docs.litellm.ai/docs/providers
_RUNTIME_PREFIX = {
    "ollama": "ollama_chat",
    "vllm": "openai",  # vLLM serves an OpenAI-compatible endpoint
    "hf-inference": "huggingface",
    "endpoint": "openai",  # any OpenAI-compatible base URL
}


def _litellm_model(mf: ModelSpec) -> str:
    prefix = _RUNTIME_PREFIX.get(mf.model.runtime, "openai")
    return f"{prefix}/{mf.model.id}"


class LiteLLMProvider:
    """Live provider. Chat/completion goes through LiteLLM; fixed-label classifiers hit an
    HF-style text-classification endpoint directly (LiteLLM targets generative APIs)."""

    def __init__(self, timeout_s: float = 30.0, media_max_bytes: int = 10_000_000):
        self._timeout = timeout_s
        self._media_max_bytes = media_max_bytes

    async def run_chat(self, mf: ModelSpec, messages: list[dict]) -> str:
        import litellm

        kwargs: dict[str, Any] = {
            "model": _litellm_model(mf),
            "messages": messages,
            "temperature": 0,
            "timeout": self._timeout,
        }
        if mf.model.endpoint:
            kwargs["api_base"] = validate_inference_endpoint(mf.model.endpoint)
        response = await litellm.acompletion(**kwargs)
        return response.choices[0].message.content or ""

    async def run_chat_top_logprobs(
        self, mf: ModelSpec, messages: list[dict]
    ) -> list[tuple[str, float]]:
        import litellm

        kwargs: dict[str, Any] = {
            "model": _litellm_model(mf),
            "messages": messages,
            "temperature": 0,
            "max_tokens": 1,
            "logprobs": True,
            "top_logprobs": 20,
            "timeout": self._timeout,
        }
        if mf.model.endpoint:
            kwargs["api_base"] = validate_inference_endpoint(mf.model.endpoint)
        response = await litellm.acompletion(**kwargs)
        entries = response.choices[0].logprobs.content[0].top_logprobs
        return [(entry.token, entry.logprob) for entry in entries]

    async def run_classifier(
        self, mf: ModelSpec, *, text: Optional[str], media_url: Optional[str]
    ) -> Any:
        url = mf.model.endpoint
        if not url:
            raise ValueError(
                f"classifier model spec '{mf.name}' requires model.endpoint"
            )
        url = validate_inference_endpoint(url)
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as client:
            if media_url is not None:
                safe_media = validate_media_url(media_url)
                media = await client.get(safe_media)
                media.raise_for_status()
                # Cap downloaded media to avoid unbounded memory use.
                if len(media.content) > self._media_max_bytes:
                    raise ValueError(
                        f"mediaUrl response exceeds {self._media_max_bytes} bytes"
                    )
                response = await client.post(
                    url,
                    content=media.content,
                    headers={
                        "Content-Type": media.headers.get(
                            "content-type", "application/octet-stream"
                        )
                    },
                )
            else:
                response = await client.post(url, json={"inputs": text or ""})
            response.raise_for_status()
            return response.json()
