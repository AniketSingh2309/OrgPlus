"""Runtime settings, read from the environment / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root: secrets/ and data/ live here, wherever the process is started from.
ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # Looks in the cwd first, then the repo root when run from backend/.
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "postgresql://orgpulse:orgpulse@localhost:5432/orgpulse"

    # --- Multi-organisation mode (one database per organisation) -----------------------
    # Set CONTROL_DATABASE_URL to turn it on. All three use passwordless roles that may
    # only connect from this machine (localhost); see README "Database security".
    control_database_url: str = (
        ""  # e.g. postgresql://orgplus_control@localhost:5432/orgplus_control
    )
    # Provisioning role: postgresql://orgplus_admin@localhost:5432/postgres. Give it to the
    # worker only (it creates each new sign-up's database) and the `orgs` CLI, never the API.
    admin_database_url: str = ""
    org_database_url_template: str = "postgresql://{role}@localhost:5432/{db}"
    # Organisations to create with `python -m orgpulse.orgs sync-allowed` (comma-separated).
    allowed_domains: str = ""

    # Fallback Google credential (the /connect screen stores an encrypted one in the DB).
    google_service_account_json: Path = ROOT / "secrets" / "orgpulse-sync.json"
    google_admin_impersonate: str = ""
    google_customer_id: str = "my_customer"
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    allowed_domain: str = ""
    # On by default: Classroom is free on every edition and the feature switches itself on
    # when the Classroom scopes are granted. Set false to hide it entirely.
    enable_classroom: bool = True

    # Fernet key for stored service-account JSON: python -m orgpulse.crypto --new-key
    credential_enc_key: str = ""

    # Shared with the web app; the web proxy signs a short-lived JWT with it.
    nextauth_secret: str = ""
    # Comma-separated emails with full (head-of-org) access. Workspace super admins
    # always have it. Everyone else gets the manager view (own OU + reports).
    org_admins: str = ""
    # Browser origins allowed to open the real-time socket (comma-separated).
    web_origins: str = "http://localhost:3000"
    # Local development only: lets the web app sign requests without signing in.
    dev_auth_bypass: bool = False

    # --- Accounts (email + password) ---------------------------------------------------
    # The web app's public address: links in verification / password-reset emails.
    app_url: str = "http://localhost:3000"
    # Development only: with no SMTP configured, write those links to the API log instead
    # of refusing to sign people up. Never enable in production.
    auth_email_log_links: bool = False
    # Wrong passwords before an account is locked, and for how long.
    login_max_failures: int = 5
    login_lock_minutes: int = 15

    # City-level IP database for the sign-in map: free DB-IP City Lite, fetched by
    # `python -m orgpulse.geoip_update` (monthly, by the worker). A MaxMind GeoLite2
    # City .mmdb works here too.
    geoip_db: Path = ROOT / "data" / "dbip-city-lite.mmdb"

    # Weekly digest over SMTP (Gmail API send is used instead if DIGEST_VIA_GMAIL=true).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    # SMTP_PASSWORD, or SMTP_PASS as many providers name it.
    smtp_password: str = Field(
        default="", validation_alias=AliasChoices("smtp_password", "smtp_pass")
    )
    smtp_from: str = ""
    digest_via_gmail: bool = False

    # Run the APScheduler worker with an initial backfill when the DB is empty.
    backfill_days: int = 180
    # Near-real-time event polling (Google itself publishes login events minutes late,
    # Drive/Meet/etc. up to a few hours late, usage 2-3 days late).
    events_live_seconds: int = 60  # every activity app, short look-back
    events_deep_minutes: int = 360  # every app, days of look-back (late events)

    log_level: str = "INFO"

    @property
    def sqlalchemy_url(self) -> str:
        """DATABASE_URL with the psycopg 3 driver made explicit."""
        return psycopg_url(self.database_url)

    @property
    def domains(self) -> list[str]:
        """Every domain allowed to sign in (ALLOWED_DOMAINS, plus ALLOWED_DOMAIN)."""
        items = [d.strip().lower() for d in self.allowed_domains.split(",") if d.strip()]
        if self.allowed_domain.strip() and self.allowed_domain.strip().lower() not in items:
            items.append(self.allowed_domain.strip().lower())
        return items

    @property
    def org_admin_emails(self) -> set[str]:
        return {e.strip().lower() for e in self.org_admins.split(",") if e.strip()}


def psycopg_url(url: str) -> str:
    """postgresql:// URL -> SQLAlchemy URL with the psycopg 3 driver."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
