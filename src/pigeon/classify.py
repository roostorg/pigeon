from __future__ import annotations

import json
from typing import Optional

from .modelspecs import ModelSpec
from .parsing import (
    parse_chat_verdict,
    parse_classifier_scores,
    resolve_response_path,
    score_from_yesno_logprobs,
)
from .providers.base import ProviderClient
from .registry import Registry
from .schemas import ClassifyContext, ClassifyResult


def _merge_thread_context(
    text: Optional[str], context: Optional[ClassifyContext]
) -> Optional[str]:
    if (
        text is None
        or context is None
        or context.thread is None
        or not context.thread.messages
    ):
        return text

    thread = "\n".join(
        f"{message.role}: {message.text}" if message.role else message.text
        for message in context.thread.messages
    )
    return f"{thread}\n{text}"


def build_prompt(mf: ModelSpec, text: Optional[str], policy: Optional[str]) -> list[dict]:
    user = mf.prompt.user.replace("{{content}}", text or "").replace(
        "{{policy}}", policy or ""
    )
    messages: list[dict] = []
    if mf.prompt.system:
        messages.append({"role": "system", "content": mf.prompt.system})
    messages.append({"role": "user", "content": user})
    return messages


def _apply_chat_parser(mf: ModelSpec, content: str) -> dict[str, float]:
    if mf.parser.type == "json":
        data = json.loads(content)
        return parse_classifier_scores(resolve_response_path(data, mf.parser.response_path))
    # verdict: single-value BYOP / safety verdict
    label = mf.labels[0] if mf.labels else "verdict"
    return {label: parse_chat_verdict(content)}


def _apply_classifier_parser(mf: ModelSpec, raw: object) -> dict[str, float]:
    return parse_classifier_scores(resolve_response_path(raw, mf.parser.response_path))


async def classify(
    *,
    org_id: str,
    model_ref: str,
    text: Optional[str],
    media_url: Optional[str],
    policy: Optional[str],
    registry: Registry,
    provider: ProviderClient,
    context: Optional[ClassifyContext] = None,
) -> tuple[str, list[ClassifyResult]]:
    """Resolve a model reference and return (resolved_version, normalized results)."""
    resolved = registry.resolve(org_id, model_ref)
    mf = resolved.modelspec
    effective_policy = resolved.bound_policy if resolved.bound_policy is not None else policy
    text = _merge_thread_context(text, context)

    if mf.format == "classifier":
        raw = await provider.run_classifier(mf, text=text, media_url=media_url)
        scores = _apply_classifier_parser(mf, raw)
        wanted = mf.labels or list(scores.keys())
        results = [
            ClassifyResult(label=lbl, score=scores[lbl]) for lbl in wanted if lbl in scores
        ]
    else:
        if media_url is not None:
            # Shieldstral and other multimodal BYOP models are declared image-capable,
            # but Pigeon's chat/BYOP path is text-only today. Fail loudly rather than
            # scoring on empty content.
            raise ValueError(
                f"model '{mf.name}': image input is not yet supported for chat/BYOP models"
            )
        messages = build_prompt(mf, text=text, policy=effective_policy)
        if mf.parser.type == "logprob_yesno":
            top_logprobs = await provider.run_chat_top_logprobs(mf, messages)
            label = mf.labels[0] if mf.labels else "verdict"
            scores = {label: score_from_yesno_logprobs(top_logprobs)}
        else:
            content = await provider.run_chat(mf, messages)
            scores = _apply_chat_parser(mf, content)
        results = [ClassifyResult(label=lbl, score=score) for lbl, score in scores.items()]

    if not results:
        raise ValueError("model returned no usable labels")
    return resolved.version, results
