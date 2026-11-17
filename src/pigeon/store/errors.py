from __future__ import annotations


class DuplicateError(Exception):
    """Raised when inserting a row that violates a uniqueness constraint."""
