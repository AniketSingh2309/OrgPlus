from __future__ import annotations

from orgpulse.roles import role_label, roles_for


def test_built_in_and_custom_role_labels() -> None:
    assert role_label("_SEED_ADMIN_ROLE") == "Super Admin"
    assert role_label("_HELP_DESK_ADMIN_ROLE") == "Help Desk Admin"
    assert role_label("_SOME_FUTURE_ADMIN_ROLE") == "Some Future Admin"  # unknown built-in
    assert role_label("Finance Auditors") == "Finance Auditors"  # custom roles untouched


def test_roles_for_orders_and_dedupes() -> None:
    raw = "_GROUPS_ADMIN_ROLE, _SEED_ADMIN_ROLE, _HELP_DESK_ADMIN_ROLE"
    assert roles_for(raw, is_admin=True) == ["Super Admin", "Groups Admin", "Help Desk Admin"]
    assert roles_for(None, is_admin=True) == ["Super Admin"]
    assert roles_for(None) == []
