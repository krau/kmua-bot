#!/usr/bin/env python
"""Generate a signed initData string for local frontend development.

Telegram normally hands a Mini App its launch parameters, signed with the bot
token. Outside Telegram there is nothing to sign them, and the backend must not
relax that check just because it is a dev build - so instead this script produces
a genuine signature using the token from your settings file.

The result goes into webapp/.env.local (gitignored) and is only ever read under
`import.meta.env.DEV`, so it cannot reach a production bundle.

Usage:
    uv run python scripts/dev_init_data.py                    # write .env.local
    uv run python scripts/dev_init_data.py --print            # print only
    uv run python scripts/dev_init_data.py --user-id 12345    # impersonate
    uv run python scripts/dev_init_data.py --chat-id -1001234 # open a group page
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / "webapp" / ".env.local"

# initData carries an auth_date and the backend rejects anything older than
# webapp_initdata_ttl (300s by default). A dev session lasts longer than that, so
# the generated payload is dated far enough ahead to survive a working session.
# The backend only checks that it is not too *old*.
DEV_VALIDITY_SECONDS = 86400 * 30

# A syntactically valid but meaningless Ed25519 signature: base64url of 64 zero
# bytes. See the note in `build_init_data` for why a placeholder is enough.
DEV_SIGNATURE_PLACEHOLDER = "A" * 86


def load_settings() -> tuple[str, list[int]]:
    """Read the bot token and owner list from the project settings.

    Imports `kmua.config` so the dev payload always matches whatever the bot is
    actually running with, including settings.dev.toml overrides.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from kmua.config import app_config
    except Exception as e:  # pragma: no cover - developer feedback path
        raise SystemExit(f"Could not load settings: {e}") from e

    if not app_config.token:
        raise SystemExit(
            "No bot token configured. Set `token` in settings.toml or settings.dev.toml."
        )
    return app_config.token, list(app_config.owners)


def build_init_data(
    token: str,
    *,
    user_id: int,
    first_name: str,
    last_name: str | None,
    username: str | None,
    language_code: str,
    start_param: str | None,
    auth_date: int,
) -> str:
    """Sign a launch payload exactly the way a Telegram client would."""
    user = {
        "id": user_id,
        "first_name": first_name,
        "language_code": language_code,
        "allows_write_to_pm": True,
    }
    if last_name:
        user["last_name"] = last_name
    if username:
        user["username"] = username

    fields: dict[str, str] = {
        "user": json.dumps(user, separators=(",", ":"), ensure_ascii=False),
        "auth_date": str(auth_date),
        "chat_instance": "-1234567890123456789",
        "chat_type": "sender",
        # `signature` is Telegram's Ed25519 signature for third-party validation.
        # The SDK's launch-param schema requires the field to be present, so a
        # placeholder is needed or the frontend refuses to parse the payload.
        #
        # It is not verified by anything in this project: the backend includes it
        # in the HMAC (as Telegram specifies for bot-token validation) but never
        # checks the Ed25519 signature itself. The SDK only needs it to exist.
        # Producing a real one would require Telegram's private key.
        "signature": DEV_SIGNATURE_PLACEHOLDER,
    }
    if start_param:
        fields["start_param"] = start_param

    # The data check string is every field except `hash`, sorted by key, joined
    # with newlines. See kmua/webapp/auth.py for the verifying side.
    check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    data_hash = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()

    return urlencode({**fields, "hash": data_hash})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--user-id",
        type=int,
        default=None,
        help="User to impersonate. Defaults to the first configured owner.",
    )
    parser.add_argument("--first-name", default="Dev")
    parser.add_argument("--last-name", default=None)
    parser.add_argument("--username", default="dev_user")
    parser.add_argument("--lang", default="zh-CN")
    parser.add_argument(
        "--chat-id",
        type=int,
        default=None,
        help="Group id to deep-link into, as ?startapp=c<id> would.",
    )
    parser.add_argument(
        "--print",
        dest="print_only",
        action="store_true",
        help="Print the value instead of writing webapp/.env.local",
    )
    args = parser.parse_args()

    token, owners = load_settings()

    user_id = args.user_id
    if user_id is None:
        if not owners:
            raise SystemExit(
                "No owners configured and no --user-id given. "
                "Set `owners` in settings, or pass --user-id."
            )
        # Default to an owner so the developer panel is reachable out of the box.
        user_id = owners[0]

    start_param = f"c{abs(args.chat_id)}" if args.chat_id else None

    init_data = build_init_data(
        token,
        user_id=user_id,
        first_name=args.first_name,
        last_name=args.last_name,
        username=args.username,
        language_code=args.lang,
        start_param=start_param,
        auth_date=int(time.time()) + DEV_VALIDITY_SECONDS,
    )

    role = "owner" if user_id in owners else "regular user"
    if args.print_only:
        print(init_data)
        return

    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text(
        "# Generated by scripts/dev_init_data.py - do not commit.\n"
        "# Read only under import.meta.env.DEV; never reaches a production bundle.\n"
        f"VITE_DEV_INIT_DATA={init_data}\n",
        encoding="utf-8",
    )

    print(f"Wrote {ENV_FILE.relative_to(REPO_ROOT)}")
    print(f"  user_id    {user_id} ({role})")
    if start_param:
        print(f"  start_param {start_param} -> chat {args.chat_id}")
    print("\nNext:")
    print("  1. add `webapp = true` and webapp_allow_origins to settings.dev.toml")
    print("  2. uv run python -m kmua")
    print("  3. cd webapp && pnpm dev")


if __name__ == "__main__":
    main()
