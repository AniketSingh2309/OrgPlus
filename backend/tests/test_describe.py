from __future__ import annotations

import pytest

from orgpulse.describe import APP_LABEL, describe


@pytest.mark.parametrize(
    ("app", "event", "params", "title", "expected"),
    [
        # Gemini: one event name, meaning in the parameters (real values from a live domain)
        (
            "gemini_in_workspace_apps",
            "feature_utilization",
            {"app_name": "gmail", "action": "summarize_proactive", "feature_source": "side_panel"},
            None,
            "Gemini summarised an email in Gmail",
        ),
        (
            "gemini_in_workspace_apps",
            "feature_utilization",
            {"app_name": "gemini_app", "action": "classic_use_case_gemini_app"},
            None,
            "Chatted with Gemini",
        ),
        (
            "gemini_in_workspace_apps",
            "feature_utilization",
            {"app_name": "gmail", "action": "auto_proofread"},
            None,
            "Gemini proofread a draft in Gmail",
        ),
        (
            "gemini_in_workspace_apps",
            "feature_utilization",
            {"app_name": "admin_console", "action": "search_answer"},
            None,
            "Asked Gemini a question in the Admin console",
        ),
        (
            "gemini_in_workspace_apps",
            "feature_utilization",
            {"app_name": "docs", "action": "brand_new_thing"},
            None,
            "Used Gemini in Docs: Brand new thing",
        ),
        ("login", "dbsc_key_binding", {}, None, "Secured sign-in to this device"),
        ("login", "login_success", {}, None, "Signed in"),
        ("user_accounts", "2sv_enroll", {}, None, "Turned on 2-Step Verification"),
        ("drive", "change_acl_editors", {}, "Q3 Roadmap", "Changed editors on Q3 Roadmap"),
        ("drive", "search", {}, None, "Searched Drive"),
        ("drive", "download", {}, "key5.pem", "Downloaded key5.pem"),
        ("token", "authorize", {"app_name": "Slack"}, None, "Authorised Slack"),
        ("meet", "call_ended", {"duration_seconds": 1830}, None, "Was in a call · 30 min"),
        ("meet", "send_chat_everyone", {}, None, "Messaged everyone in a meeting"),
        ("calendar", "create_event", {"event_title": "Standup"}, None, "Created event Standup"),
        ("admin", "CREATE_USER", {"USER_EMAIL": "new@x.com"}, None, "Create user · new@x.com"),
        ("some_new_app", "brand_new_event", {}, None, "Brand new event"),  # never shows raw codes
    ],
)
def test_describe(
    app: str, event: str, params: dict[str, object], title: str | None, expected: str
) -> None:
    assert describe(app, event, params, title) == expected


def test_short_app_labels() -> None:
    assert APP_LABEL["gemini_in_workspace_apps"] == "Gemini"
    assert APP_LABEL["user_accounts"] == "Account"
    assert all(len(label) <= 10 for label in APP_LABEL.values())  # fits the timeline column
