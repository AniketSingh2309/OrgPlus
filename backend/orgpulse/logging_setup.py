"""One place to configure logging for the API, worker and CLIs."""

from __future__ import annotations

import logging

from orgpulse.config import get_settings


def setup_logging(level: str | None = None) -> None:
    logging.basicConfig(
        level=(level or get_settings().log_level).upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # googleapiclient logs every discovery/cache detail at INFO; keep it quiet.
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)
