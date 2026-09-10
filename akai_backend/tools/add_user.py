"""Administrator console for the subscriber database.

Examples
--------
    python tools/add_user.py --username ahmed_01 --password pin1234 \
        --hwid AKAI-98F2-41A7-B800 --days 365
    python tools/add_user.py --username ahmed_01 --password pin1234   # HWID binds on first login
    python tools/add_user.py --list

Only SHA-256 digests are written to ``users.json`` — plaintext secrets never
touch the disk.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.store import UserStore  # noqa: E402

USERS_FILE = Path(__file__).resolve().parents[1] / "users.json"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Akai subscriber manager")
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--hwid", default="", help="AKAI-XXXX-XXXX-XXXX code sent by the client")
    parser.add_argument("--days", type=int, default=30, help="subscription length in days (0 = unlimited)")
    parser.add_argument("--status", default="active")
    parser.add_argument("--renew", type=int, metavar="DAYS",
                        help="only update the expiry of an existing user (0 = unlimited)")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)

    store = UserStore(USERS_FILE)

    if args.renew is not None:
        if not args.username:
            parser.error("--renew requires --username")
        record = store.renew(args.username, args.renew)
        if record is None:
            print(f"user tapılmadı: {args.username}")
            return 1
        print(f"OK: {record['username']} müddəti -> {record['expires_at'] or 'limitsiz'}")
        return 0

    if args.list:
        print(json.dumps(store.list_users(), ensure_ascii=False, indent=2))
        return 0

    if not args.username or not args.password:
        parser.error("--username and --password are required unless --list is used")

    record = store.add_user(
        args.username,
        args.password,
        hwid=args.hwid.strip(),
        days=args.days or None,
        status=args.status,
    )
    print(f"OK: {record['username']} yazıldı (hwid {'bound' if record['hwid'] else 'first-login bind'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
