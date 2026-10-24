"""Plain-English descriptions of Google activity events, for timelines and logs.

Google's audit logs use internal codes (event names like "dbsc_key_binding", and for
Gemini a single "feature_utilization" event whose meaning is in its parameters).
`describe()` turns an event into what the person actually did.
"""

from __future__ import annotations

from typing import Any

APP_LABEL: dict[str, str] = {
    "login": "Sign-in",
    "drive": "Drive",
    "meet": "Meet",
    "calendar": "Calendar",
    "chat": "Chat",
    "gmail": "Gmail",
    "token": "Apps",
    "admin": "Admin",
    "saml": "SSO",
    "groups": "Groups",
    "user_accounts": "Account",
    "classroom": "Classroom",
    "gemini_in_workspace_apps": "Gemini",
    "rules": "DLP",
    "context_aware_access": "Access",
}

_PRODUCT = {
    "gmail": "Gmail", "gemini_app": "the Gemini app", "admin_console": "the Admin console",
    "docs": "Docs", "sheets": "Sheets", "slides": "Slides", "drive": "Drive", "meet": "Meet",
    "calendar": "Calendar", "chat": "Chat", "forms": "Forms", "vids": "Vids",
}  # fmt: skip

_GEMINI = {
    "summarize_proactive": "Gemini summarised an email in {app}",
    "summarize_card": "Gemini summarised an email in {app}",
    "auto_proofread": "Gemini proofread a draft in {app}",
    "proofread": "Gemini proofread a draft in {app}",
    "generate_text": "Gemini helped write in {app}",
    "classic_use_case_gemini_app": "Chatted with Gemini",
    "conversation": "Asked Gemini in {app}",
    "search_answer": "Asked Gemini a question in {app}",
    "generate_search_ai_overview": "Gemini summarised search results in {app}",
    "generate_starter_tile_prompts": "Opened Gemini in {app}",
    "add_to_calendar": "Gemini added an event to Calendar",
}

_DRIVE = {
    "create": "Created", "edit": "Edited", "view": "Viewed", "preview": "Previewed",
    "download": "Downloaded", "upload": "Uploaded", "print": "Printed", "copy": "Copied",
    "rename": "Renamed", "move": "Moved", "add_to_folder": "Added to a folder:",
    "remove_from_folder": "Removed from a folder:", "trash": "Moved to trash:",
    "untrash": "Restored from trash:", "delete": "Deleted",
    "change_user_access": "Changed sharing on", "change_document_access_scope": "Changed link sharing on",
    "change_document_visibility": "Changed visibility of", "change_acl_editors": "Changed editors on",
    "change_owner": "Transferred ownership of", "change_user_access_hierarchy_reconciled": "Sharing updated (inherited) on",
    "approval_requested": "Requested approval for", "search": "Searched Drive",
}  # fmt: skip

_SIMPLE: dict[str, dict[str, str]] = {
    "login": {
        "login_success": "Signed in", "logout": "Signed out", "login_failure": "Failed sign-in",
        "login_verification": "Completed 2-Step Verification", "login_challenge": "Was asked to verify a sign-in",
        "password_edit": "Changed password", "dbsc_key_binding": "Secured sign-in to this device",
        "risky_sensitive_action_allowed": "Sensitive action allowed after a risk check",
        "suspicious_login": "Suspicious sign-in flagged by Google", "account_disabled_password_leak": "Account locked: leaked password",
    },
    "user_accounts": {
        "password_edit": "Changed password", "2sv_enroll": "Turned on 2-Step Verification",
        "2sv_disable": "Turned off 2-Step Verification", "recovery_email_edit": "Changed recovery email",
        "recovery_phone_edit": "Changed recovery phone", "titanium_enroll": "Turned on Advanced Protection",
    },
    "calendar": {
        "create_event": "Created event", "change_event": "Edited event", "delete_event": "Deleted event",
        "add_event_guest": "Invited guests to", "remove_event_guest": "Removed a guest from",
        "change_event_guest_response": "Responded to", "change_event_start_time": "Rescheduled",
        "notification_triggered": "Reminder for", "add_subscription": "Subscribed to a calendar",
        "change_event_title": "Renamed event",
    },
    "chat": {
        "message_posted": "Posted a message", "message_edited": "Edited a message", "message_deleted": "Deleted a message",
        "conversation_read": "Read a conversation", "room_created": "Created a space", "add_room_member": "Added someone to a space",
        "remove_room_member": "Removed someone from a space", "attachment_upload": "Shared a file in Chat",
        "attachment_download": "Downloaded a Chat attachment", "invite_send": "Sent a Chat invite",
        "invite_accept": "Accepted a Chat invite", "app_added": "Added an app to Chat", "reaction_added": "Reacted to a message",
    },
    "meet": {
        "presentation_started": "Presented in a meeting", "send_chat_everyone": "Messaged everyone in a meeting",
        "hand_raised": "Raised hand in a meeting", "reaction_sent": "Reacted in a meeting",
        "knocking_accepted": "Let someone into a meeting", "knocking_denied": "Declined someone's request to join",
        "streaming_session_explicit_consent": "Agreed to a recording or livestream",
        "speech_translation_disallowed": "Speech translation unavailable in a meeting",
        "recording_activity": "Recorded a meeting", "transcription_activity": "Turned on transcription",
    },
    "groups": {"request_to_join": "Asked to join a group", "join": "Joined a group", "leave": "Left a group"},
    "classroom": {
        "created_course": "Created class", "user_joined_course": "Joined class", "published_course_work": "Posted classwork",
        "created_course_work": "Created classwork", "updated_course_work": "Edited classwork",
        "published_announcement": "Posted an announcement", "updated_announcement": "Edited an announcement",
    },
}  # fmt: skip


def _human(code: str) -> str:
    """'CHANGE_APPLICATION_SETTING' / 'add_to_folder' -> 'Change application setting'."""
    words = code.replace("_", " ").strip().lower()
    return words[:1].upper() + words[1:] if words else "Activity"


def _with(text: str, obj: Any) -> str:
    obj = str(obj).strip() if obj else ""
    return f"{text} {obj}".strip() if obj else text


def describe(
    app: str, event: str, params: dict[str, Any] | None, doc_title: str | None = None
) -> str:
    p = params or {}
    if app == "gemini_in_workspace_apps":
        product = _PRODUCT.get(
            str(p.get("app_name") or ""), _human(str(p.get("app_name") or "Workspace"))
        )
        template = _GEMINI.get(str(p.get("action") or ""))
        if template:
            return template.format(app=product)
        return f"Used Gemini in {product}: {_human(str(p.get('action') or p.get('feature_source') or 'feature'))}"
    if app == "drive":
        verb = _DRIVE.get(event, _human(event))
        return verb if event == "search" else _with(verb, doc_title or p.get("doc_title"))
    if app == "meet" and event == "call_ended":
        minutes = round(int(p.get("duration_seconds") or 0) / 60)
        return f"Was in a call · {minutes} min" if minutes else "Joined a call briefly"
    if app == "token":
        name = p.get("app_name") or p.get("client_id") or "an app"
        return {"authorize": f"Authorised {name}", "revoke": f"Revoked access for {name}"}.get(
            event, _with(_human(event), name)
        )
    if app == "saml":
        return _with(
            {"login_success": "Signed in to", "login_failure": "Failed sign-in to"}.get(
                event, _human(event)
            ),
            p.get("application_name"),
        )
    if app == "admin":
        target = (
            p.get("USER_EMAIL")
            or p.get("GROUP_EMAIL")
            or p.get("ORG_UNIT_NAME")
            or p.get("SETTING_NAME")
            or p.get("APPLICATION_NAME")
        )
        return _with(_human(event), f"· {target}" if target else None)
    text = _SIMPLE.get(app, {}).get(event)
    if text:
        obj = (
            p.get("event_title")
            or p.get("room_name")
            or p.get("course_title")
            or p.get("course_work_title")
        )
        if app == "calendar" and event in ("add_subscription",):
            obj = None
        return _with(text, obj)
    return _with(_human(event), doc_title)
