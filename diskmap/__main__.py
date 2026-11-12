"""Allow `python -m diskmap` as well as `python -m diskmap.cli`."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
