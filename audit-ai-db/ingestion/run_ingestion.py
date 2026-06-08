from __future__ import annotations

"""Legacy compatibility wrapper.

Use ingestion.run_hybrid_ingestion for normal ingestion.
"""

from ingestion.legacy.local_ingestion import (
    _try_log_failure,
    build_parser,
    main,
    run_ingestion,
)


if __name__ == "__main__":
    raise SystemExit(main())
