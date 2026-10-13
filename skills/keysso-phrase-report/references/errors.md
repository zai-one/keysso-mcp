# Keys.so errors

| Code | Meaning | Action |
|---|---|---|
| 400 | missing/invalid parameter | fix arguments; see `keysso://reports` |
| 401 | bad token | operator must update the token file |
| 404 | domain/phrase not found in base | try another `base` or check spelling |
| 429 | plan request limit | wait `Retry-After`; check `keysso_limits`; reduce pages |
| 500 | provider error | retry once later |
| partial result | `complete=false`, `stop_reason` | report as partial; offer `next_page` |
