"""Download the free DB-IP "IP to City Lite" database: `python -m orgpulse.geoip_update`.

No account needed. Licensed CC BY 4.0 ("IP Geolocation by DB-IP", credited on the
sign-in map). Same .mmdb format as MaxMind GeoLite2, so either works as GEOIP_DB.
DB-IP publishes a new file each month; run this monthly (the worker does).
"""

from __future__ import annotations

import gzip
import logging
import shutil
import sys
import tempfile
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path

from orgpulse.config import get_settings

log = logging.getLogger(__name__)

URL = "https://download.db-ip.com/free/dbip-city-lite-{month}.mmdb.gz"


def _months_to_try(today: date) -> list[str]:
    prev = date(today.year - (today.month == 1), (today.month - 2) % 12 + 1, 1)
    return [today.strftime("%Y-%m"), prev.strftime("%Y-%m")]


def update(target: Path | None = None) -> Path:
    """Fetch the newest monthly file into GEOIP_DB (atomically) and return its path."""
    target = target or get_settings().geoip_db
    target.parent.mkdir(parents=True, exist_ok=True)
    last_err: Exception | None = None
    for month in _months_to_try(datetime.now(UTC).date()):
        url = URL.format(month=month)
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=target.parent, suffix=".mmdb", delete=False
            ) as tmp:
                tmp_path = Path(tmp.name)
                log.info("downloading %s", url)
                # DB-IP refuses Python's default user agent (HTTP 403).
                req = urllib.request.Request(
                    url, headers={"User-Agent": "OrgPlus-GeoIP-Updater/1.0"}
                )
                with (
                    urllib.request.urlopen(req, timeout=120) as resp,
                    gzip.GzipFile(fileobj=resp) as gz,
                ):
                    shutil.copyfileobj(gz, tmp)
            _verify(tmp_path)
            tmp_path.replace(target)
            log.info("GeoIP database updated: %s (%s)", target, month)
            return target
        except Exception as err:
            last_err = err
            log.warning("could not use %s: %s", url, err)
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
    raise RuntimeError(f"GeoIP download failed: {last_err}")


def _verify(path: Path) -> None:
    import geoip2.database

    with geoip2.database.Reader(str(path)) as reader:
        reader.city("8.8.8.8")  # raises if the file isn't a city database


if __name__ == "__main__":
    from orgpulse.logging_setup import setup_logging

    setup_logging()
    try:
        print(update())
    except RuntimeError as err:
        print(err, file=sys.stderr)
        sys.exit(1)
