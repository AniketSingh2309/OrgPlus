"""Readable admin role names.

roles.list returns Google's built-in roles as internal ids (e.g. "_SEED_ADMIN_ROLE");
custom roles keep the name the admin gave them.
"""

from __future__ import annotations

BUILT_IN: dict[str, str] = {
    "_SEED_ADMIN_ROLE": "Super Admin",
    "_DAR_RESOLD_CUSTOMER_MANAGEMENT_ROLE": "Reseller Customer Management",
    "_DIRECTORY_SYNC_ADMIN_ROLE": "Directory Sync Admin",
    "_GROUPS_ADMIN_ROLE": "Groups Admin",
    "_GROUPS_EDITOR_ROLE": "Groups Editor",
    "_GROUPS_READER_ROLE": "Groups Reader",
    "_HELP_DESK_ADMIN_ROLE": "Help Desk Admin",
    "_INVENTORY_REPORTING_ADMIN_ROLE": "Inventory Reporting Admin",
    "_MIGRATION_DRIVE_ADMIN_ROLE": "Drive Migration Admin",
    "_MOBILE_ADMIN_ROLE": "Mobile Admin",
    "_MULTI_PARTY_APPROVAL_ADMIN_ROLE": "Multi-party Approval Admin",
    "_SERVICE_ADMIN_ROLE": "Services Admin",
    "_STORAGE_ADMIN_ROLE": "Storage Admin",
    "_USER_MANAGEMENT_ADMIN_ROLE": "User Management Admin",
}
SUPER_ADMIN = "Super Admin"


def role_label(raw: str) -> str:
    raw = raw.strip()
    if raw in BUILT_IN:
        return BUILT_IN[raw]
    if raw.startswith("_") and raw.endswith("_ROLE"):  # a built-in role we haven't named yet
        return raw.strip("_").removesuffix("_ROLE").replace("_", " ").title()
    return raw  # custom role: the admin's own name


def roles_for(admin_role: str | None, is_admin: bool = False) -> list[str]:
    """Readable, de-duplicated roles; Super Admin first, then alphabetical."""
    labels = {role_label(r) for r in (admin_role or "").split(", ") if r.strip()}
    if is_admin:
        labels.add(SUPER_ADMIN)
    return sorted(labels, key=lambda r: (r != SUPER_ADMIN, r.lower()))
