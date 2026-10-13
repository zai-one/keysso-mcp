# Keys.so metrics glossary (field names as returned by the API)

| Field | Meaning |
|---|---|
| `vis` | visibility score of the domain in the base |
| `it1`, `it3`, `it5`, `it10`, `it50` | number of keywords in TOP-1/3/5/10/50 |
| `topvis`, `topkeys` | domain's rank among all domains by visibility / by keywords |
| `pagesinindex` | pages found in the search results |
| `adtraf`, `adcost` | estimated ad traffic and budget (`adcost.average`, `max`) |
| `adscnt`, `adkeyscnt` | number of ads / keywords with ads |
| `word` | search phrase |
| `ws` | broad frequency (Wordstat "word") |
| `wsk` | exact frequency ("!word") |
| `pos` | domain position for the phrase |
| `cnt`, `perc` (competitors) | common keywords and share of overlap |
| `dr` | domain rating |

Sort format: `field|asc` or `field|desc`, up to three comma-separated (e.g. `pos|asc,wsk|desc`).

Bases (`base`): msk Яндекс Москва · spb Санкт-Петербург · ekb Екатеринбург · nsk Новосибирск ·
kzn Казань · nnv Н. Новгород · rnd Ростов · krr Краснодар · sam Самара · ufa Уфа · prm Пермь · che
Челябинск · vrn Воронеж · vlg Волгоград · kry Красноярск · oms Омск · sar Саратов · tmn Тюмень · tom
Томск · mns Минск · gru Google Москва · gkv Google Киев · gmns Google Минск · gny Google New York · zen
Дзен. Source: https://apidoc.keys.so/
