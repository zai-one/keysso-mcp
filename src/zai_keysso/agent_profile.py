"""Keys.so agent profile: router, compact descriptions, toolsets and prompts."""

from __future__ import annotations

from zai_keysso.agent_layer import Profile, Prompt

ROUTER = """Keys.so MCP: read-only competitive SEO/PPC research (domains, keywords, pages, ads, AI answers).
Toolsets: meta, reports, ai_tracker (see keysso://toolsets). Report paths and params: keysso://reports.
Use Keys.so for market/competitor data on any domain; use Topvisor for your own tracked positions and
Arsenkin for SERP parsing/clustering jobs.
Quota: every report page spends plan requests; start with max_pages=1, small page_size and fields=[...];
check keysso_limits before large pulls. Base defaults to msk; ask the user for region if unclear.
Partial results carry stop_reason: never call them a complete audit.
Playbooks: skills keysso-competitor-research, keysso-phrase-report, keysso-content-gap; or keysso://playbook,
keysso://guide/{metrics-glossary,ai-tracker,errors}.
Errors: on 429 wait Retry-After; retry only when retryable."""

DESCRIPTIONS = {
    "keysso_limits": "Read remaining Keys.so plan limits per tool. Use before large multi-page pulls. "
    "Cost: free (no report quota).",
    "keysso_domain_report": "Read a domain report: keywords, competitors, pages or backlinks (≤5 pages). Use "
    "for one domain; for overlaps use `keysso_compare_domains`. Cost: 1 request per page. fields=[...] "
    "trims columns; output=csv.",
    "keysso_compare_domains": "Compare domains: keywords of include minus exclude (keyword gap). Use for "
    "content gap vs competitors; for one domain use `keysso_domain_report`. Cost: 1 request per page.",
    "keys_so_query": "Run any allowlisted Keys.so report (dashboards, ads, phrase, lost keywords) by path. "
    "Use when typed tools don't cover it; read keysso://reports for paths/params. Cost: 1 request.",
    "keysso_ai_tracker": "Read Keys.so AI-tracker (GEO) data: projects, mentions, citations, competitors, "
    "prompts. Use for brand visibility in AI answers; system IDs in keysso://guide/ai-tracker. Read-only. "
    "Cost: 1 request.",
    "keysso_check_update": "Check for a newer server release; never installs. Cost: free, 24h cache.",
}

TOOLSETS = {
    "meta": ("keysso_check_update", "keysso_limits"),
    "reports": ("keysso_domain_report", "keysso_compare_domains", "keys_so_query"),
    "ai_tracker": ("keysso_ai_tracker",),
}

PROMPTS = (
    Prompt(
        "competitor_research",
        "Competitor research for a domain with Keys.so (quota-aware).",
        ("domain", "base"),
        "Research competitors of {domain} in Keys.so base {base}. Follow skill keysso-competitor-research: "
        "dashboard, competitors, keyword gap vs top 3, top pages, ads. "
        "Use max_pages=1 and fields to save quota.",
    ),
    Prompt(
        "content_gap",
        "Keyword/content gap between my site and competitors.",
        ("my_domain", "competitors"),
        "Find keywords where {competitors} rank and {my_domain} does not. Follow skill keysso-content-gap "
        "(keysso_compare_domains include=competitors exclude=my_domain) and group the gap by topic.",
    ),
    Prompt(
        "phrase_report",
        "Report on one search phrase: volume, similar phrases, who ranks and advertises.",
        ("phrase", "base"),
        "Build a Keys.so report for phrase '{phrase}' (base {base}) following skill keysso-phrase-report.",
    ),
)

PROFILE = Profile(
    service="keysso",
    package="zai_keysso",
    router=ROUTER,
    descriptions=DESCRIPTIONS,
    toolsets=TOOLSETS,
    prompts=PROMPTS,
    titles={"keys_so_query": "Keys.so: query report"},
)
