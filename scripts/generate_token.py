#!/usr/bin/env python3
"""
Generate JWT tokens for local testing.

Usage (inside Docker):
    docker compose run --rm --entrypoint python app scripts/generate_token.py

Or directly (if calllens is installed locally):
    python scripts/generate_token.py

Prints one token per persona. Copy the token you want and set it as a
Bearer token in your MCP client or in curl:

    curl -H "Authorization: Bearer <token>" http://localhost:8000/health
"""

from __future__ import annotations

import json
import sys

# Allow running from the project root without installing
sys.path.insert(0, "src")

from calllens.mcp.auth import make_token

PERSONAS = [
    {
        "sub": "alice@aegiscloud.io",
        "role": "sales_manager",
        # Restrict Alice to three accounts; remove this key for unrestricted
        "account_names": [],
        "label": "Sales Manager (all accounts)",
    },
    {
        "sub": "bob@aegiscloud.io",
        "role": "sales_manager",
        "account_names": ["Acme Corp", "TechFlow Inc"],
        "label": "Sales Manager (Acme Corp + TechFlow only)",
    },
    {
        "sub": "carol@aegiscloud.io",
        "role": "support_lead",
        "account_names": [],
        "label": "Support Lead",
    },
    {
        "sub": "dave@aegiscloud.io",
        "role": "product_manager",
        "account_names": [],
        "label": "Product Manager",
    },
    {
        "sub": "eve@aegiscloud.io",
        "role": "eng_lead",
        "account_names": [],
        "label": "Engineering Lead",
    },
]


def main() -> None:
    print("\n" + "=" * 70)
    print("  CallLens — Test JWT Tokens (valid 24 h)")
    print("=" * 70)

    tokens: dict[str, str] = {}
    for p in PERSONAS:
        token = make_token(
            sub=p["sub"],
            role=p["role"],
            account_names=p.get("account_names"),
        )
        tokens[p["label"]] = token
        print(f"\n[{p['label']}]")
        print(f"  sub  : {p['sub']}")
        print(f"  role : {p['role']}")
        if p.get("account_names"):
            print(f"  accs : {p['account_names']}")
        print(f"  token: {token}")

    print("\n" + "=" * 70)
    print("  Quick smoke test (requires jq):")
    print("=" * 70)
    sales_token = tokens["Sales Manager (all accounts)"]
    support_token = tokens["Support Lead"]
    print(f"""
  # Should return churn risks:
  curl -s -H "Authorization: Bearer {sales_token}" \\
       http://localhost:8000/mcp/sse | head -30

  # Should return "Access denied":
  curl -s -H "Authorization: Bearer {support_token}" \\
       http://localhost:8000/mcp/sse | head -5
""")


if __name__ == "__main__":
    main()
