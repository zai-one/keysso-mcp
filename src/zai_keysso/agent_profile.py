"""Keys.so agent profile: router, compact descriptions, toolsets and prompts."""

from __future__ import annotations

from zai_keysso.agent_layer import Profile, Prompt, Route, build_router

ROUTES = (
    Route("competitors", "конкуренты сайта, competitors, видимость, трафик", "keysso_domain_report",
          "keysso-competitor-research", "metrics-glossary"),
    Route("gap", "контент-гэп, чего нет у нас, gap, сравнить", "keysso_compare_domains",
          "keysso-content-gap", "metrics-glossary"),
    Route("phrase", "фраза, запрос, phrase, кто в топе, похожие", "keys_so_query", "keysso-phrase-report",
          "metrics-glossary"),
    Route("ads", "реклама, объявления, ads, РСЯ, архив, ссылки, доноры, анкоры, Дзен", "keys_so_query", "",
          "tool-map"),
    Route("semantics", "семантика, ядро, кластеры, кластеризация, мониторинг, cluster", "keysso_clustering",
          "keysso-semantic-core", "jobs"),
    Route("geo", "нейросети, ИИ-ответы, AI, ChatGPT, GEO, бренд", "keysso_ai_tracker", "", "ai-tracker"),
    Route("limits", "лимиты, квота, ошибка, limits, error, 429", "keysso_limits", "", "errors"),
)  # fmt: skip

ROUTER = build_router(
    "keysso",
    "Keys.so MCP: competitor SEO/PPC research; keysso://toolsets. Pages spend quota: max_pages=1, "
    "keysso_limits first, base msk unless told. stop_reason = partial, never complete.",
    ROUTES,
    "Opt-in jobs/monitoring spend limits: confirm=true only after user OK. Paths: keysso://reports.",
)

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
    "keysso_keyword_job": "Run a keyword tool job: mass phrase check, semantic expansion, "
    "competitor share by phrases. Flow start -> status -> result. "
    "Cost: start spends limits, needs confirm=true.",
    "keysso_clustering": "Cluster phrases by SERP overlap: create -> build -> status -> folders -> "
    "keywords. Use after collecting semantics. "
    "Cost: create/build spend limits, need confirm=true.",
    "keysso_monitoring": "Read or start Keys.so position monitoring. Reads: projects, report, "
    "compare, chart, dates, limits; create from clusters, start refresh. "
    "Cost: create/start need confirm=true.",
    "keysso_api": "Documented tools/*, wordstat, serp, clustering import/frequency, monitoring "
    "PATCH/DELETE. Cost: non-GET needs operator approval_id.",
    "keysso_check_update": "Check for a newer server release; never installs. Cost: free, 24h cache.",
}

TOOLSETS = {
    "meta": ("keysso_check_update", "keysso_limits"),
    "reports": ("keysso_domain_report", "keysso_compare_domains", "keys_so_query"),
    "ai_tracker": ("keysso_ai_tracker",),
    "jobs": ("keysso_keyword_job", "keysso_clustering"),
    "monitoring": ("keysso_monitoring",),
    "api": ("keysso_api",),
}
OPTIN = ("jobs", "monitoring", "api")

PROMPTS = (
    Prompt(
        "semantic_core",
        "Semantics -> clusters -> positions for a site with Keys.so jobs (limit-aware).",
        ("domain", "seeds", "base"),
        "Build a semantic core for {domain} from seeds {seeds} (base {base}) following skill "
        "keysso-semantic-core: expand, check frequencies, cluster, then monitor positions. "
        "Show keysso_limits and ask before every confirm=true.",
    ),
    Prompt(
        "competitor_research",
        "Competitor research for a domain with Keys.so (quota-aware).",
        ("domain", "base"),
        "Research competitors of {domain} in Keys.so base {base}. Follow skill keysso-competitor-research: "
        "dashboard, competitors, keyword gap vs top 3, top pages, ads. "
        "Use max_pages=1 to save quota and fields to trim columns.",
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
    routes=ROUTES,
    optin=OPTIN,
    titles={"keys_so_query": "Keys.so: query report"},
)
