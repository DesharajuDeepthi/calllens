"""
Role-based permission matrix for MCP tools.

Rules:
- support_lead   : see support-call data, no financials
- sales_manager  : see churn/renewal data, own accounts only
- product_manager: see feature gaps and pain points, no financials
- eng_lead       : see technical issues, internal + support calls only
"""

from __future__ import annotations


# Memory tools available to every authenticated role
_MEMORY_TOOLS = {"remember_context", "recall_context", "forget_context"}

# Which tools each role may call
ALLOWED_TOOLS: dict[str, set[str]] = {
    "support_lead": {
        "get_my_insights", "get_topic_trends", "get_account_health", "search_calls",
        *_MEMORY_TOOLS,
    },
    "sales_manager": {
        "get_my_insights", "get_topic_trends", "get_account_health",
        "get_churn_risks", "search_calls",
        *_MEMORY_TOOLS,
    },
    "product_manager": {
        "get_my_insights", "get_topic_trends", "get_account_health", "search_calls",
        *_MEMORY_TOOLS,
    },
    "eng_lead": {
        "get_my_insights", "get_topic_trends", "search_calls",
        *_MEMORY_TOOLS,
    },
}

# Fields stripped from get_account_health per role
ACCOUNT_HEALTH_REDACTED: dict[str, set[str]] = {
    "support_lead":     {"contract_value", "renewal_date", "arr", "csm_owner"},
    "product_manager":  {"contract_value", "renewal_date", "arr", "csm_owner"},
    "sales_manager":    set(),   # full access
    "eng_lead":         set(),   # denied at tool level; this is never reached
}

# Which call types each role may search
SEARCH_CALL_TYPES: dict[str, list[str]] = {
    "support_lead":     ["support"],
    "sales_manager":    ["external", "support"],
    "product_manager":  ["support", "external", "internal"],
    "eng_lead":         ["internal", "support"],
}


def can_call(role: str, tool: str) -> bool:
    return tool in ALLOWED_TOOLS.get(role, set())


def redact_account_health(role: str, data: dict) -> dict:
    fields = ACCOUNT_HEALTH_REDACTED.get(role, set())
    return {k: v for k, v in data.items() if k not in fields}


def allowed_call_types(role: str) -> list[str]:
    return SEARCH_CALL_TYPES.get(role, [])


def owns_account(claims: dict, account_name: str) -> bool:
    """
    Returns True if the caller may access this account.
    Empty account_names list = no restriction (dev / admin token).
    """
    allowed = claims.get("account_names", [])
    if not allowed:
        return True
    return account_name in allowed
