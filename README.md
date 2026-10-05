# Pigeon

Prototyping open-weight safety models as Coop signals and Osprey rule functions.
This repo is being used to prototype and plan; see [issues] and [discussions] for more!

## Get involved

> [!CAUTION]
> **Pigeon is a prototype!**
> It is not production-ready, and should not be considered usable or stable in any way.

Prototyping is happening under the [`prototype` branch](https://github.com/roostorg/pigeon/tree/prototype). To discuss and help plan what shape Pigeon will eventually take, join us in [#pigeon] in the ROOST Discord server, check the open [issues], or chime in on the [discussions]. We're excited to build this together with the open source community!

[issues]: https://github.com/roostorg/pigeon/issues
[discussions]: https://github.com/roostorg/pigeon/discussions
[#pigeon]: https://discord.gg/JkSpezAnp6

---

Pigeon aims to makes open-weight safety models usable inside [Coop](https://github.com/roostorg/coop)
and [Osprey](https://github.com/roostorg/osprey) with the same effort as adding a hosted API.
A model is described by a **model spec** (a small YAML recipe), not a per-model integration
package. Pigeon is a service: consumers call it over HTTP; it holds the model specs, the
provider credentials, and the response-parsing logic.

It also runs standalone, as a way to manage and send requests to open weights across any
inference provider, without Coop or Osprey.

> Status: prototype. The contracts and flows are working end to end against a mock provider;
> the eng team takes it forward from here (hardening, real inference, persistence, UI).

## What it does

- **Discover** (`GET /v1/modelspecs`): lists the signals an org can use. Fixed-label
  classifiers fan out to one label each; policy-bound BYOP custom models appear as a single
  verdict signal.
- **Classify** (`POST /v1/classify`): input in, normalized `[{label, score}]` out. The caller
  never sees prompts, wire formats, or response paths.
- **Policy management** (`POST /v1/policies`): author a policy against a policy-steerable base
  (CoPE-B) to mint a versioned custom model. This is the "build a custom
  model from an open-weight base" path.

## Model kinds

| Kind | model spec | Signals | Policy |
| --- | --- | --- | --- |
| `classifier` | `format: classifier`, fixed `labels` | one per label | none |
| `byop` | `format: chat`, `policy_argument: true` | one per bound policy | pre-bound (Coop) or per-call (Osprey) |
| `completion` | `mode: completion` | not a Coop signal | Osprey-only |

## Quickstart

```bash
uv sync --extra dev
uv run pytest                 # runs against the mock provider, no network

cp .env.example .env
uv run pigeon                 # serves on http://127.0.0.1:8900
```

Try it (dev token from `.env.example`):

```bash
TOKEN="dev-token"
curl -s localhost:8900/v1/modelspecs -H "Authorization: Bearer $TOKEN"

curl -s localhost:8900/v1/classify -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"model":"shieldgemma-2b","input":{"text":"you are worthless"}}'

# Author a policy -> custom model, then classify against it
curl -s localhost:8900/v1/policies -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"my-harassment-policy","base":"cope-b","policyText":"Flag harassment.","display":"Harassment policy"}'
```

## Providers

The inference backend is a swappable seam, selected by `PIGEON_PROVIDER`. All three run the
same model specs and the same `/v1/classify` contract.

| `PIGEON_PROVIDER` | Backend | Use for |
| --- | --- | --- |
| `mock` (default) | none | tests, wiring, local dev; keyword-based scores, no network |
| `live` | LiteLLM | any OpenAI-compatible endpoint: **Ollama**, vLLM, HF TGI, hosted APIs |
| `local` | transformers | in-process models on MPS/CUDA/CPU (needs the `local` extra) |

### `live` — hosted or self-served endpoints (verified with Ollama)

`live` routes chat/completion through LiteLLM and HF-style classifiers over HTTP. Point each
model spec's `model.endpoint` at your runtime. Verified end to end against **Ollama** on macOS
(Apple Silicon): a BYOP `verdict` model spec with `runtime: ollama`, `model.id: <ollama model>`,
`endpoint: http://localhost:11434` scores real content through the full Pigeon path.

```bash
PIGEON_PROVIDER=live uv run pigeon
```

### `local` — in-process transformers (verified with Shieldstral on MPS)

For models you run in-process rather than behind a server. Install the extra and set the
provider; models load lazily and are cached per id.

```bash
uv sync --extra local           # torch, transformers>=5.0
PIGEON_PROVIDER=local uv run pigeon
```

Verified end to end with **Shieldstral 1.0-3B** loaded via `AutoModelForImageTextToText` on
Apple MPS (bfloat16), scored in a single forward pass — the continuous score is the softmax
over the max single-token yes/no logits (parser `logprob_yesno`). The provider mirrors the
reference loader in `ROOST/vibecheck/eval/models/shieldstral.py`. The bound policy is the yes/no
`<Query>` the model judges (e.g. "Does this content harass a person?").

Shieldstral can also be served OpenAI-compatible via vLLM (`vllm serve mistralai/Shieldstral-1.0-3B
--max-model-len 32768`) and reached through the `live` provider on a CUDA GPU.

Text-only for now on both providers; image input on a BYOP model returns 422 until the vision
path lands.

## Layout

- `src/pigeon/modelspecs.py` - model spec schema + loader
- `src/pigeon/registry.py` - model specs + policies -> the signal list; model-ref resolution
- `src/pigeon/parsing.py` - response normalization (ported from Coop's `modelClient.ts`)
- `src/pigeon/classify.py` - the classify orchestration
- `src/pigeon/providers/` - the inference seam (`mock`, `litellm_provider`, `transformers_provider`)
- `src/pigeon/api.py` - the HTTP endpoints
- `modelspecs/` - example model specs (`shieldgemma-2b` classifier, `shieldstral`/`cope-b` BYOP)

## Known gaps (for the eng team)

- Image/multimodal input on BYOP models returns 422; the vision path (Shieldstral is
  multimodal) is not wired yet.
- Response caching (one model call serving every label) is not yet ported from Coop.
- `chat-harmony` format is declared but not yet implemented.
- Auth is a static token->org map; wire to real per-org credentials.
- `local` provider runs one model instance sequentially; no batching or concurrency control.
- `live` provider calls LiteLLM directly; a LiteLLM-proxy adapter is a likely next step.
