"""Module entrypoint for the Codex Feishu controller."""

from __future__ import annotations

import sys
from pathlib import Path


def _bootstrap() -> None:
    if __package__:
        return
    src_dir = Path(__file__).resolve().parents[1]
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


_bootstrap()

from codex_feishu_link.bootstrap import bootstrap, parse_args  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return bootstrap(config_path=args.config_path, mode=args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
