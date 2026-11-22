"""Allow `python -m gleanly`, which works even when pip's Scripts folder is not on PATH."""

from gleanly.cli import main

raise SystemExit(main())
