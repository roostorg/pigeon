from __future__ import annotations

import pytest

from pigeon.urls import validate_inference_endpoint, validate_media_url


def test_https_endpoint_ok():
    assert validate_inference_endpoint("https://infer.example.com/v1") == (
        "https://infer.example.com/v1"
    )


def test_http_loopback_endpoint_ok():
    assert validate_inference_endpoint("http://127.0.0.1:8000/v1").startswith("http://")


def test_rejects_credentials_and_metadata():
    with pytest.raises(ValueError, match="credentials"):
        validate_inference_endpoint("https://user:pass@infer.example.com")
    with pytest.raises(ValueError, match="not allowed"):
        validate_media_url("http://169.254.169.254/latest/meta-data")
    with pytest.raises(ValueError, match="not allowed"):
        validate_media_url("https://metadata.google.internal/")


def test_rejects_plain_http_to_public_host():
    with pytest.raises(ValueError, match="https"):
        validate_media_url("http://evil.example.com/img.png")
