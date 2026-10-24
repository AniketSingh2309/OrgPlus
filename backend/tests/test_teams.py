from __future__ import annotations

from orgpulse.teams import ROOT_TEAM, team_of


def test_department_wins_else_org_unit() -> None:
    assert team_of("Sales", "/Technical") == "Sales"
    assert team_of(None, "/Technical") == "Technical"
    assert team_of("  ", "/Ops/Mumbai/") == "Mumbai"  # blank department, nested OU
    assert team_of(None, "/") == ROOT_TEAM
    assert team_of(None, None) == ROOT_TEAM
