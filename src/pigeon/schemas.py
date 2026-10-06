from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .modelspecs import ModelSpec

# ---- Discover (GET /v1/modelspecs) ----


class LabelSpec(BaseModel):
    id: str
    display: str
    valueType: Literal["score"] = "score"


class ModelSpecSummary(BaseModel):
    id: str
    version: str
    kind: Literal["classifier", "byop", "completion"]
    base: Optional[str] = None
    # Underlying model id (e.g. a HuggingFace "owner/repo"), so consumers can load
    # the real model card. For BYOP customs this is the base spec's model id.
    modelId: Optional[str] = None
    inputTypes: list[str]
    labels: list[LabelSpec]


class ModelSpecsResponse(BaseModel):
    modelspecs: list[ModelSpecSummary]


class ModelSpecCreate(ModelSpec):
    model_config = ConfigDict(extra="forbid")


class ModelSpecEnable(BaseModel):
    version: str
    endpoint: Optional[str] = None
    credential_ref: Optional[str] = None


class ModelSpecImport(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)
    dry_run: bool = False


# ---- Classify (POST /v1/classify) ----


class ClassifyInput(BaseModel):
    text: Optional[str] = None
    mediaUrl: Optional[str] = None


class ClassifyRequest(BaseModel):
    model: str
    input: ClassifyInput
    policy: Optional[str] = None


class ClassifyResult(BaseModel):
    label: str
    score: float


class ClassifyResponse(BaseModel):
    model: str
    results: list[ClassifyResult]


# ---- Policy management (BYOP custom models) ----


class PolicyCreate(BaseModel):
    name: str
    base: str  # base model spec name; must be policy-steerable (BYOP)
    policyText: str
    display: Optional[str] = None


class PolicyResponse(BaseModel):
    id: str  # the custom model id (== name)
    version: str
    base: str
    display: str
