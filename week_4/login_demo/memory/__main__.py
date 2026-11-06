"""允许 `python -m memory ...` 直接调用 CLI。"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
