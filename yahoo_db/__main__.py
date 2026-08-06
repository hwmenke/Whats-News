"""Entry point so `python -m yahoo_db …` works."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
