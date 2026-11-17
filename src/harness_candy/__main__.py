"""Permite ``python -m harness_candy ...`` (igual que el entry point ``harness-candy``)."""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
