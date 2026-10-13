# Keys.so jobs: semantics, clustering, monitoring

Opt-in toolsets: `KEYSSO_TOOLSETS=default,jobs,monitoring` (or `all`). Every start spends plan limits:
call `keysso_limits`, show phrase count + remaining limit, and pass `confirm=true` only after an
explicit OK. Without `confirm` the tool returns a free preview (`needs_confirmation`).

| Step | Tool call | Notes |
|---|---|---|
| Expand seeds | `keysso_keyword_job(kind="extended_keywords", action="start", phrases=[...], base)` | returns `uid` |
| Mass check | `keysso_keyword_job(kind="keywords_by_list", action="start", phrases=[...])` | frequencies `ws`/`wsk` |
| Competitor share | `keysso_keyword_job(kind="concurents_by_keywords", action="start", phrases, top=10)` | `view=domains|urls` |
| Poll | `action="status", uid` | wait until done; then `action="result", page, per_page, sort="wsk|desc"` |
| Cluster | `keysso_clustering(action="create", phrases, base)` -> `action="build", uid, top_number=10` | `strength` %, `min_frequency` |
| Read clusters | `action="status"` -> `action="folders"` -> `action="keywords", folder_id` | folders = clusters |
| Track positions | `keysso_monitoring(action="create", tracking_item=domain, cluster_uid=uid, region_id=213)` | engine 0 Yandex, 1 Google |
| Refresh / read | `action="limits"` -> `action="start", project_id` -> `action="report"/"compare", date_from, date_to` | |
| Existing projects | `keysso_monitoring(action="projects")`, `action="dates"`, `action="chart"` | read-only |

Limits: up to 1000 phrases per call, 100 chars per phrase. Region IDs: 213 Москва, 2 СПб (Yandex).
Not exposed: deleting projects, moving phrases between folders, editing monitoring settings.
Saved group reports (read): `keys_so_query("/report/group/list")`, `/report/group/<section>/<rid>`.
