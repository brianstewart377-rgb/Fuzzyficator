"""Single entry point for the bundled Fuzzyficator desktop application."""

from __future__ import annotations

import sys
from typing import Optional, Sequence

import Fuzzyficator
import Fuzzyficator_configurator


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        return Fuzzyficator.main(arguments)
    return Fuzzyficator_configurator.main()


if __name__ == "__main__":
    raise SystemExit(main())
