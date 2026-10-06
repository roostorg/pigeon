from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    # Default bind is loopback; do not expose without an explicit host.
    uvicorn.run(
        "pigeon.main:create_app",
        factory=True,
        host=os.environ.get("PIGEON_HOST", "127.0.0.1"),
        port=int(os.environ.get("PIGEON_PORT", "8900")),
    )
