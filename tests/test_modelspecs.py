from __future__ import annotations

from pigeon.modelspecs import load_modelspecs

from .conftest import MODELSPECS_DIR


def test_load_examples():
    mfs = load_modelspecs(MODELSPECS_DIR)
    assert set(mfs) >= {"shieldgemma-2b", "shieldstral", "cope-b"}


def test_classifier_kind():
    mfs = load_modelspecs(MODELSPECS_DIR)
    assert mfs["shieldgemma-2b"].kind == "classifier"
    assert mfs["shieldgemma-2b"].version == "3"  # coerced from YAML
    assert (
        mfs["shieldgemma-2b"].model_card_url
        == "https://huggingface.co/google/shieldgemma-2b"
    )


def test_multimodal_byop_kind():
    mfs = load_modelspecs(MODELSPECS_DIR)
    assert mfs["shieldstral"].kind == "byop"
    assert mfs["shieldstral"].policy_argument is True
    assert set(mfs["shieldstral"].input_types) == {"text", "image"}


def test_byop_kind():
    mfs = load_modelspecs(MODELSPECS_DIR)
    assert mfs["cope-b"].kind == "byop"
    assert mfs["cope-b"].policy_argument is True
