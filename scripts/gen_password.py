"""Generate a strong random password for DASHBOARD_PASSWORD.

Usage:
    python scripts/gen_password.py            # 24 chars (default)
    python scripts/gen_password.py 32         # custom length
"""
import secrets
import string
import sys

ALPHABET = string.ascii_letters + string.digits + "-_.~"  # URL/env-safe symbols


def generate(length: int = 24) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


if __name__ == "__main__":
    length = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    if length < 16:
        sys.exit("Use at least 16 characters for a public-facing dashboard.")
    print(generate(length))
