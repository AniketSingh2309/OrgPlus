"""What "team" means: the Directory department when set, otherwise the org unit.

Many domains never fill in Department but do organise people into org units, so
an empty department falls back to the OU's name (people in the top-level OU are
grouped as ROOT_TEAM).
"""

from __future__ import annotations

ROOT_TEAM = "Top-level org unit"


def team_of(department: str | None, org_unit_path: str | None) -> str:
    if department and department.strip():
        return department.strip()
    path = (org_unit_path or "").rstrip("/")
    return path.rsplit("/", 1)[-1] if path else ROOT_TEAM


def team_sql(alias: str = "u") -> str:
    """The same rule as a SQL expression over a users row."""
    return (
        f"COALESCE(NULLIF(TRIM({alias}.department), ''), "
        f"NULLIF(regexp_replace(rtrim(COALESCE({alias}.org_unit_path, ''), '/'), '^.*/', ''), ''), "
        f"'{ROOT_TEAM}')"
    )
