from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from .urls import validate_inference_endpoint

Runtime = Literal["ollama", "vllm", "hf-inference", "endpoint"]
Mode = Literal["signal", "completion"]
Format = Literal["chat", "chat-harmony", "classifier"]
InputType = Literal["text", "image", "audio"]


class ModelRef(BaseModel):
    id: str
    runtime: Runtime
    endpoint: Optional[str] = None  # base URL (chat) or full inference URL (classifier)

    @field_validator("endpoint")
    @classmethod
    def _validate_endpoint(cls, value: Optional[str]) -> Optional[str]:
        if value is None or value == "":
            return None
        return validate_inference_endpoint(value)


class PromptSpec(BaseModel):
    system: Optional[str] = None
    user: str = "{{content}}"


class ParserSpec(BaseModel):
    # classifier: HF label/score array; verdict: chat text -> single score; json: JSON body ->
    # scores; logprob_yesno: softmax over the yes/no first-token logprobs (Shieldstral).
    type: Literal["classifier", "json", "verdict", "logprob_yesno"] = "verdict"
    response_path: Optional[str] = None  # dot-path into the response before parsing


class ModelSpec(BaseModel):
    name: str
    version: str
    model: ModelRef
    mode: Mode = "signal"
    format: Format = "chat"
    policy_argument: bool = False
    input_types: list[InputType] = Field(default_factory=lambda: ["text"])
    prompt: PromptSpec = Field(default_factory=PromptSpec)
    parser: ParserSpec = Field(default_factory=ParserSpec)
    labels: list[str] = Field(default_factory=list)
    languages_validated: list[str] = Field(default_factory=list)

    @field_validator("version", mode="before")
    @classmethod
    def _stringify_version(cls, v: object) -> str:
        return str(v)

    @property
    def kind(self) -> str:
        """Consumer-facing classification: what a caller can do with this model."""
        if self.mode == "completion":
            return "completion"
        return "byop" if self.policy_argument else "classifier"


def load_modelspecs(directory: Path) -> dict[str, ModelSpec]:
    """Load and validate every *.yaml/*.yml model spec in a directory, keyed by name."""
    result: dict[str, ModelSpec] = {}
    if not directory.exists():
        return result
    for path in sorted(directory.glob("*.y*ml")):
        raw = yaml.safe_load(path.read_text())
        try:
            mf = ModelSpec.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(f"invalid model spec {path.name}: {exc}") from exc
        result[mf.name] = mf
    return result
