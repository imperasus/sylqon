# Sylqon — LoL publikus webfelület fejlesztési terv

> Készült: 2026-07-09 · Alap: a beérkezett „op.gg-stílusú LoL webfelület" brief +
> a repo aktuális állapotának auditja (v1.22.0) + a meglévő `docs/FEJLESZTESI_TERV.md` (2026 H2 roadmap).
>
> **Pozicionálás:** ez a dokumentum a `FEJLESZTESI_TERV.md` **§5 (Fázis 2 / S3 — champion-pool
> weboldal)** kibővítése egy teljes, több-oldalas publikus webfelületté. Nem új termékvonal:
> a már élő `services/ingestion-svc/app/web.py` SSR-oldalt bővíti keresés → profil → meccsek →
> meccs-részletek → champion-meta → ranglista + insight irányba.

---

## 0. Vezetői összefoglaló — és 3 korrekció a briefhez

A brief egy generikus op.gg-klón terve, amit **kódbázis-ismeret nélkül** írtak. A tartalmi
irány (summoner-keresés → profil → meccslista → meccs-részletek → champion-meta → ranglista →
insights) jó, de három feltevése a repo valóságában **már megoldott vagy elavult**, egy pontja
pedig **ütközik a saját ToS-keretünkkel**. A terv ezekre épül:

| Brief feltevése | Valóság a repóban | Következmény a tervre |
|---|---|---|
| „A Sylqon arculata nem elérhető, feltételezhető modern/letisztult." | A **Graphite Volt** arculat kész és tokenizált: Space Grotesk + Inter + JetBrains Mono, lime `#a3e635` + amber `#fbbf24` grafit alapon (`ui/src/index.css`, `landing/landing.html`). | Nem feltételezünk — a §4 pontos tokeneket ad; a meglévő `web.py` palettáját kiegészítjük az amberrel és a fontokkal. |
| „A stack ismeretlen, feltételezhetően Node/React; javasolt Next.js/Nuxt SSR." | A publikus web **már FastAPI + build-mentes SSR HTML** (`ingestion-svc/app/web.py`), SEO-barát, hosztolva. A React csak a lokális dashboard (`ui/`). | **Nem hozunk be Node/Next-et.** SSR-first FastAPI marad; React-sziget csak indokolt interaktivitáshoz (§3). Ez olcsóbb hosztolás és nulla új runtime. |
| „Riot-klienst, region-routingot, rate-limitet fel kell építeni." | Kész: `ingestion-svc/app/riot_client.py` (Account-V1, Match-V5 + timeline, League-V4) + dual-window Redis token-bucket limiter, prod-key méretezve (450/10s + 27000/600s), 429 `Retry-After`. | A backend nagy része **kész** — a §5 végpont-térkép megmutatja, mi hiányzik ténylegesen (lényegében: leaderboard-hívás + olvasó view-endpointok). |

**A negyedik, legfontosabb pont — framing/ToS ütközés (döntést igényel, §2):** a brief
„player performance insights", „tier list win rate-tel" és „regionális ranglisták" funkciókat
javasol. A saját `FEJLESZTESI_TERV.md §9` compliance-táblázata viszont kimondja: **nincs
MMR/ELO-kalkulátor, a score-ok pool-lefedettséget mérnek, nem skill-ratinget.** A meglévő
`web.py` minden száma szándékosan *pool coverage*, sosem *player skill* (teszt is védi). A terv
ezt a gerincet **megtartja**, és a brief új oldalait ToS-konform keretbe illeszti (§2, §9).

**Egymondatos irány:** a meglévő pool-coverage SSR-oldalt bővítjük teljes, márkahű, SEO-barát
LoL webfelületté — a Riot-hivatalos adatokra (Account-V1 + Match-V5 + League-V4) és a saját
Match-V5 aggregációra építve —, a „coaching, nem skill-rating" pozicionálás megtartásával.

---

## 1. Kiindulás — mi van már kész

### 1.1 Publikus web (a bővítés alapja) — `services/ingestion-svc/app/web.py`
Build-mentes, SSR HTML, Graphite Volt palettával, ToS-safe „pool coverage" kerettel:

| Route | Tartalom | Brief-megfelelője |
|---|---|---|
| `GET /` | Riot ID beviteli űrlap | Keresőoldal (részben) |
| `GET /pool-report?riot_id=Name%23TAG` | Per-role pool-coverage audit (performance + blind-pick safety + counter coverage), 3-fős pool-javaslat | Profil + Insights (részben) |
| `GET /champions` | Champion-jelenlét + win rate a saját adathalmazból | Champion-meta (részben) |
| `GET /champion/{name}` | Core-item build + lane-matchup a saját aggregációból | Champion-részletek |

### 1.2 Backend API — `ingestion-svc/app/main.py`
`POST /api/ingest`, `GET /api/pool/{name}/{tag}`, `GET /api/meta-sync/full`,
`GET /api/meta-build/{champion}`, `GET /api/advice/{match_id}/{puuid}`, `GET /healthz`.

### 1.3 Riot-kliens — `ingestion-svc/app/riot_client.py`
`get_account_by_riot_id` (Account-V1, mass-cluster), `get_match_ids` / `get_match` /
`get_timeline` (Match-V5, mass-cluster), `get_ranked_stats` (League-V4 entries, platform-route).
Region-config: `RIOT_PLATFORM_REGION=euw1`, `RIOT_MASS_REGION=europe`. **Hiányzik:**
challenger/grandmaster/master-league lekérés és champion-mastery (utóbbi a `sylqon/riot/api.py`-ban
megvan, ide portolandó).

### 1.4 Adatmodell — `ingestion-svc/app/models.py` (Postgres, JSONB)
`Match`, `MatchParticipant` (KDA, CS, gold, vision, wards, damage + teljes `stats` JSONB),
`Timeline`, `Advice`, `ComputedBenchmark` (role×rank-band mediánok), `PlayerRank` (League-V4),
`MetaBuild`, `CrawlTarget` (co-player seed-crawl frontier). A meccs- és résztvevő-adat, valamint
a rank **már perzisztálva van** — a brief adatmodelljének nagy része létező tábla.

### 1.5 Advice-pipeline (az „insights" motorja) — `ingestion-svc/app/advice/`
5 determinisztikus heurisztika (halál-kontextus, CS-benchmark, item-timing, vízió,
objective-jelenlét) → súlyozott top-1 tanulság → HU/EN sablonszöveg, `(match, puuid)`-onként
cache-elve. **Ez a brief „insights panel"-jének kész, transzformatív (coaching) magja** — nem
kell skill-rating-kalkulátort építeni hozzá.

### 1.6 Arculat — Graphite Volt (kész, tokenizált)
`ui/src/index.css` + `landing/landing.html`: lásd §4. A `web.py` a lime + grafit palettát már
használja; a Space Grotesk/Inter fontok és az amber szekunder még hiányoznak belőle.

---

## 2. Stratégiai döntés — framing (a terv sarokköve)

A brief új oldalai közül kettő ToS-érzékeny. A javasolt kezelés:

| Brief-funkció | Kockázat | Javasolt ToS-konform kezelés (ajánlott) |
|---|---|---|
| **Insights: „player performance"** | Skill-rating látszata (MMR/ELO-tiltás) | Az „insights" = a meglévő **advice-heurisztikák** (coaching, transzformatív) + **leíró** saját-meccs statisztikák (KDA, CS/min, vízió trend). Sosem „skill score" vagy MMR-becslés. |
| **Champion tier list win rate-tel** | Ha „ki a legjobb játékos" — tiltott; ha „champion-jelenlét/WR a datasetben" — OK | A meglévő `/champions` keretét visszük tovább: *champion presence & win rate a saját adathalmazból*, patch-címkével. Champion-meta, nem player-ranking. |
| **Regionális ranglisták (Challenger/GM)** | **Megengedett** — hivatalos League-V4 publikus adat | Új oldal + endpoint OK. Kizárólag a Riot által publikált liga-adat, változtatás nélkül. Nem keverjük a mi score-jainkkal. |
| **Profil rang megjelenítése** | Hivatalos League-V4 → OK | Megjeleníthető (tier/division/LP), mert ezt maga a Riot publikálja. |

**Ajánlott irány (default):** a „pool coverage / coaching" gerincet **megtartjuk** — ez a
production-key kérelem feltétele (§9) ÉS a fő differenciátor a stat-trackerekkel szemben. A
profil/meccs/meccs-részlet oldalak **leíró adatmegjelenítésként** épülnek (a Riot saját adatát
mutatják), az „insights" a coaching-heurisztikákból jön, a ranglista pedig tiszta hivatalos
League-V4 adat. Így a felület gazdagabb lesz (a brief célja), de nem csúszik át tiltott
skill-rating-kalkulátorba.

> **Nyitott döntés a tulajdonosnak:** ha a cél kifejezetten egy op.gg-versenytárs (nyers
> stat-tracker, egyéni „performance score" előtérben), az szembemegy a §9 compliance-gate-tel és
> veszélyezteti a production key-t. A terv az ajánlott, ToS-konform gerincre épül; ha pivot kell,
> az a §2 újratárgyalása.

---

## 3. Célarchitektúra — hol él és mivel épül a webfelület

- **Otthona:** a `services/ingestion-svc` **`web.py` bővítése** (nem új szolgáltatás). Ez már
  publikus, hosztolt, Riot-API-only és pool-coverage-framed — pontosan a brief „hosztolt
  webapp" igénye. A lokális React `ui/` dashboard külön marad (nem publikus web).
- **Domain / pozicionálás (eldöntve, 2026-07-09):** a **`sylqon.com` apex = ez a funkcionális
  webapp** — ő a fő site. A jelenlegi marketing `landing/` (ma GitHub Pages) **beolvad ennek a
  nyitóoldalává**: a landing hero + „töltsd le a desktop appot" CTA a FastAPI-app `/` route-ján
  szolgálódik, a Riot ID keresés pedig ugyanezen a főoldalon az elsődleges CTA. Következmények:
  (1) **DNS:** a `sylqon.com` apex A-rekord **már a Contabo VPS-re** (`173.212.220.128`) mutat
  ([[landing-page]]) — nincs DNS-migráció; a teendő a `web.py` apexen szolgálása. A www/`app.`
  ma GitHub Pages → az apexre redirectel vagy kivezethető. (2) **Landing-merge:** a
  `landing/landing.html` tartalma a `web.py`-ba kerül (statikus hero-szekció + a meglévő
  kereső-kártya). (3) **TLS:** a VPS reverse-proxyján (Caddy/nginx + Let's Encrypt) cert a
  `sylqon.com`-ra. (4) **SEO-bónusz:** az SSR-oldalak így az apex-domainen indexelődnek. Ez egy
  új W-darab (lásd §8, §11).
- **Renderelés — SSR-first FastAPI (a brief Next/Nuxt-javaslata helyett).** Indok: már ez a
  minta él, SEO-barát build-mentesen, nincs Node-runtime hosztolási költség, a `_page()`
  helper adott. A brief SEO- és SSR-előnye **így is teljesül** (a szerver kész HTML-t ad).
- **React-sziget csak ott, ahol valódi interaktivitás kell** (nem az egész app): pl. a
  meccs-részletek kibontható idővonala, kereső-autocomplete. Ezek beágyazott, izolált
  komponensek (esbuild egyetlen JS-fájlba), nem full-SPA — nincs Next/Nuxt.
- **Adatréteg:** Riot-hívások kizárólag szerveroldalon (`riot_client.py`), kulcs a szerveren.
  Olvasás a Postgres-ből (`models.py`), aggregáció a meglévő `pool.py` / `builds.py` /
  `metasync.py` / `aggregate.py` modulokból. Új adat háttér-ingesttel kerül be (`/api/ingest`,
  seed-crawl), nem a kérés kritikus útján.
- **Statikus játékadat (Data Dragon):** patch-verzió a `versions.json`-ból pinning-gel;
  champion-square/ikon a `ddragon.leagueoflegends.com` CDN-ről, verzióra fixálva, lokálisan
  cache-elve (a repo `cache/ddragon_catalog.json`-ja már meglévő minta a katalógusra).

```
  Böngésző ──HTTP──▶  sylqon.com  (apex → Contabo VPS)
                     └─ ingestion-svc (FastAPI)
                        ├─ web.py  (SSR HTML, Graphite Volt _page())
                        │    ├─ /                   (landing hero + Riot ID keresés)
                        │    ├─ /summoner/{riot_id} (profil + rang + mastery + insights)
                        │    ├─ /summoner/.../matches (meccslista)
                        │    ├─ /match/{match_id}   (meccs-részletek; React-sziget: idővonal)
                        │    ├─ /champions, /champion/{name} (meta — MEGVAN)
                        │    └─ /leaderboard/{queue} (ranglista — ÚJ)
                        ├─ riot_client.py  (Account-V1 / Match-V5 / League-V4  ← szerveroldali kulcs)
                        ├─ Postgres (matches, participants, timelines, ranks, meta_builds)
                        └─ Redis   (dual-window rate limiter + válasz-cache)
                                     ▲
                        DDragon CDN ─┘  (verzió-pinnelt champion-assetek)
```

---

## 4. Márkahűség — Graphite Volt (pontos tokenek)

A brief „ismeretlen arculat" feltevését felülírjuk. Kötelező tokenek minden új oldalon
(forrás: `ui/src/index.css`, `landing/landing.html`):

| Token | Érték | Használat |
|---|---|---|
| `--font-display` | **Space Grotesk** (600) | H1–H3, brand, gombfeliratok |
| `--font-body` | **Inter** (400–700) | Törzsszöveg, táblázatok |
| mono | **JetBrains Mono** | Számadatok (KDA, CS, LP, %) |
| `--color-accent` (primer) | **`#a3e635`** (lime) | Linkek, kiemelés, aktív állapot, score-sáv |
| `--color-accent-2` / amber | **`#fbbf24`** | Figyelmeztetés, AD/warm jelzés, másodlagos hangsúly |
| bg / surface / surface2 | `#0e0e0f` / `#19191a` / `#212123` | Grafit alap, kártyák |
| text / muted / border | `#f0f0f1` / `#8a8b8e` / `#2a2a2d` | Szöveg, halvány, hajszálvonalak |
| red | `#f87171` | Vereség, hiba, „warn" tag |

Stílus-elvek: **flat hairline surfaces, no glow/glass** („pro-analytics", `index.css` kommentje).
Kártya = 1px `--border` + `border-radius:12px`, nincs erős árnyék. Kerülendő: neon/esport
grafika (a brief is ezt kéri). A `web.py` `_CSS`-ét kiegészítjük: (1) Space Grotesk+Inter
`@font-face`/`<link>`, (2) `--accent-2:#fbbf24`, (3) `font-family:var(--font-display)` a
címsorokra — így a publikus web 1:1 a dashboarddal és a landinggel.

**Ikon:** a „Signal-S" márkajel (`ui/src/components/BrandMark.jsx`) SVG-je hordozható a
publikus web headerébe; a `web.py` jelenlegi szöveges „SYL·QON" helyett.

---

## 5. Végpont-térkép — brief javaslat → mi van / mi új

A brief `/api/lol/...` prefixe elhagyható; a meglévő konvenciót követjük (`/api/...` +
publikus SSR route-ok). Fő korrekció: **nincs summoner-by-name** — a Riot ezt kivezette, minden
Riot ID (`Name#TAG`) → Account-V1 → PUUID úton megy (a `riot_client` már így csinálja).

| Brief-végpont (cél) | Repo-státusz | Teendő |
|---|---|---|
| `summoners/{region}/{name}` (profil) | **Nincs by-name; Account-V1 megvan** | Új `GET /api/summoner/{game_name}/{tag_line}` view: Account-V1 + League-V4 rank + (portolt) Mastery-V4 top-N → egy profil-DTO. |
| `summoners/id/{id}` (rang) | League-V4 `get_ranked_stats` **megvan** | A profil-DTO-ban összevonva. |
| `matches/{puuid}` (meccs-id-k) | `get_match_ids` + `/api/ingest` **megvan** | Új **olvasó** `GET /api/summoner/.../matches`: a tárolt meccsek listanézete (nem nyers id-k). |
| `match/{matchId}` (részletek) | `get_match`/`get_timeline` + tárolt `raw` **megvan** | Új `GET /api/match/{match_id}`: a tárolt match+timeline → részletnézet-DTO. |
| `champions/meta` | `GET /api/meta-sync/full` + `/champions` SSR **megvan** | Marad; a meta-oldal ráépül. |
| `leaderboards/{queue}/{region}` | **Nincs** | Új: `riot_client`-be challenger/grandmaster/master-league (League-V4, platform-route) + cache + `GET /api/leaderboard/{queue}` + SSR-oldal. |

**Region-routing (a repo configjához pinnelve):** platform-route (`euw1`, `eun1`) a
League-V4 / Summoner-V4 / Champion-Mastery hívásokhoz; mass-cluster (`europe`/`americas`/`asia`)
az Account-V1 és Match-V5 hívásokhoz. A régióválasztó a fronton platform-kódot ad, amit a
backend a megfelelő cluster-re képez.

---

## 6. Adatmodell — mi van, mi hiányzik

**Már megvan** (§1.4): `Match`, `MatchParticipant` (a brief „Résztvevő" entitása szinte 1:1),
`Timeline`, `PlayerRank` (a brief „rang" mezői), `MetaBuild` + a `/champions` aggregáció (a
brief „Champion_meta"), `Advice` (az „Insights" leszármazottja).

**Új / kiegészítendő tábla vagy cache:**

| Entitás | Mezők (új) | Indok |
|---|---|---|
| `ChampionMastery` (cache) | `puuid, champion_id, mastery_points, level, last_play, fetched_at` | Profil „legjobb bajnokai" — Mastery-V4, TTL-lel. |
| `LeaderboardSnapshot` (cache) | `queue, platform, payload(JSONB), fetched_at` | Ranglista-oldal; League-V4 ritkán változik → 15–30 perc TTL. |
| `SummonerProfile` (cache, opcionális) | `puuid, game_name, tag_line, profile_icon, summoner_level, updated_at` | Ismételt profil-nézetek gyorsítása; a `raw` JSONB-ből is deriválható. |

Indexek: a `match_participants(puuid)` és `(champion_id, team_position)` **már létezik**;
a profil-meccslista és a champion-meta lekérdezés ezekre ül.

---

## 7. Oldaltérkép és per-oldal adatigény

| Oldal | Route | Adatforrás | Státusz |
|---|---|---|---|
| **Kereső / Kezdő** | `/`, `/search` | — (form → Account-V1 létezés-ellenőrzés) | Van (`/`), bővítendő régióválasztóval |
| **Profil** | `/summoner/{game_name}-{tag_line}` | `GET /api/summoner/...` (rang + mastery) + advice-összegző + pool-audit link | **Új** (a `/pool-report` beleolvad/mellé kerül) |
| **Meccslista** | `/summoner/.../matches` | tárolt `Match`+`MatchParticipant` view; háttér-`/api/ingest` frissítés | **Új** |
| **Meccs-részletek** | `/match/{match_id}` | tárolt match `raw` + `Timeline`; React-sziget az idővonalhoz | **Új** |
| **Champion-meta / tier** | `/champions` | `meta-sync` aggregáció, patch-címke | **Van**, meta-nézetté bővítve |
| **Champion-részletek** | `/champion/{name}` | build + matchup a saját adatból + DDragon kép | **Van** |
| **Ranglista** | `/leaderboard/{queue}` | League-V4 challenger/GM cache | **Új** |

Minden oldal kezeli a betöltő/hiba/üres állapotot (a `_page()` helper adott): „Játékos nem
található" (404 Account-V1), „Még nincs tárolt SR-meccs — próbáld pár perc múlva" (üres dataset,
már él a `/pool-report`-ban), „A szolgáltatás átmenetileg nem elérhető" (429/5xx). Reszponzív:
a `_CSS` grid + `max-width:100%` táblák; széles táblákra `overflow-x:auto` wrapper.

---

## 8. Fázisok — a meglévő roadmaphez illesztve

A `FEJLESZTESI_TERV.md §5` mérföldkövei már részben teljesültek (`/pool-report`, `/champions`,
`/champion` él). Ez a terv onnan viszi tovább, MVP-központúan:

| Fázis | Tartalom | Elfogadási kritérium |
|---|---|---|
| **W1 — Brand + keresés (MVP-alap)** | `web.py` `_CSS` Graphite Volt-ra (fontok, amber, Signal-S ikon); régióválasztó a keresőn; **profil-endpoint + oldal** (Account-V1 + League-V4 rang + Mastery-V4 top-N). | Riot ID → profil oldal élő rang- és mastery-adattal; márka 1:1 a landinggel; brand-teszt zöld. |
| **W2 — Meccslista + részletek** | Olvasó meccslista-endpoint + oldal (tárolt meccsek, KDA/eredmény/idő/champ); `GET /api/match/{id}` + részletoldal; idővonal React-sziget. | Profilról elérhető utolsó 10–20 meccs; meccsre kattintva teljes csapat-statok. |
| **W3 — Ranglista + meta-polish** | League-V4 leaderboard (challenger/GM) endpoint + cache + oldal; a `/champions` meta-nézetté (patch-címke, pick/win presence). | Ranglista helyes sorrendben, hivatalos adat; meta-oldal patch-tudatos. |
| **W4 — Insights + finomítás** | Profil „insights" szekció az advice-heurisztikákból + leíró trendek (KDA/CS/vízió több meccsen); a11y + SEO meta + telemetria + hibakezelés élesítése. | Insights coaching-jellegű (nem skill-score); WCAG AA kontraszt/alt/fókusz; Sentry+analytics él. |

W1–W2 = a brief „Fázis 1 (MVP)"; W3 = „Fázis 2 (bővítés)"; W4 = „Fázis 3 (insights)".
A production-key kérelem (a `FEJLESZTESI_TERV §5.3` szerint) a W1–W2 élesedésekor adható be —
a több-oldalas, működő weboldal pont az, amit a Riot „working site"-ként lát.

---

## 9. Kereszt-funkciós elvek (a brief pontjai a repóra vetítve)

- **SEO/SSR:** teljesül a FastAPI SSR-rel; nem kell Next/Nuxt. Dinamikus `<title>`/meta
  (summoner-név, champion+patch), JSON-LD a champion/ranglista oldalon; `sitemap.xml` a
  champion-oldalakra (organikus csatorna, ahogy a `web.py` kommentje már célozza).
- **Akadálymentesség (WCAG 2.1 AA):** a Graphite Volt lime `#a3e635` grafit `#0e0e0f`-en
  ellenőrzendő kontraszt (nagy szöveg OK; kis szövegnél inkább `--text`-et, a lime csak
  hangsúly); champion-képekre `alt`; billentyű-fókusz látható; logikus fókuszsorrend.
- **Rate-limit / cache:** a dual-window limiter kész (prod-key méret). Profil/rang/leaderboard
  Redis-cache 5–30 perc; meccs-adat a Postgresből (immutábilis, korlátlan cache); a nehéz
  aggregáció (`meta-sync`) prewarm batch-csel (`python -m app.cli metasync`), nem a kérés útján.
- **Hibakezelés / back-off:** a `riot_client` 429 `Retry-After` + retry-budget **kész**;
  felhasználó felé barát üzenetek (§7). A back-off már szerveroldalon van, a kliens sosem lát
  nyers Riot-hibát.
- **Biztonság:** Riot-kulcs kizárólag szerveren (env, fail-fast a lifespan-ben — kész); a
  publikus felület csak a saját route-jainkat exponálja; CORS szigorítás a hoszt-domainre;
  minden forgalom TLS.
- **Telemetria:** Sentry (backend 4xx/5xx + esetleges JS-sziget hibák) + könnyű analytics
  (privacy-barát, pl. Plausible/Matomo — a landinghez is illeszthető). Szerver-metrikák a
  meglévő logging-mintára (`logging.basicConfig` a `main.py`-ban).
- **ToS-gate:** minden új oldalt a `FEJLESZTESI_TERV §9` táblázatán átfuttatni; a
  pool-coverage/coaching framing megtartása; leaderboard = változatlan hivatalos adat; a
  „no MMR/ELO" nyelvi tiltás a UI-szövegekben (a `web.py` copy-tesztjének kiterjesztése az új
  oldalakra).

---

## 10. Kockázatok és nyitott döntések

| Tétel | Megjegyzés |
|---|---|
| **Framing-pivot (fő döntés)** | Ha „op.gg-versenytárs egyéni performance-score-ral" a cél → §9 compliance-ütközés, production-key kockázat. A terv az ajánlott ToS-konform gerincre épül; pivot = §2 újratárgyalás. |
| Adathiány új játékosnál | A profil/meccs oldal üres, míg a háttér-ingest lefut (Match-V5 ~42 hívás/20 meccs, másodpercek prod-key-en). UX: „frissítés folyamatban" állapot, majd auto-reload. |
| Mastery/leaderboard portolás | Mastery-V4 a `sylqon/riot/api.py`-ban van, de az `ingestion-svc` standalone (nem importálhat `sylqon`-t) → **újra kell implementálni** a `riot_client.py`-ban (a viselkedést másolva). |
| React-sziget scope-csúszás | A cél nem SPA; a sziget csak az idővonal/autocomplete. Ha full-interaktivitás kell, az külön döntés (a `ui/` React-minták viszik). |
| SSR HTML karbantarthatóság | A `web.py` string-alapú HTML nő; ha kényelmetlen, Jinja2 template-ekre bontás (még mindig build-mentes, nem Next). |

---

## 11. Első lépések (azonnal indítható)

1. **W1 kickoff:** `web.py` `_CSS` Graphite Volt-ra (Space Grotesk + Inter `<link>`,
   `--accent-2:#fbbf24`, címsor-font), Signal-S ikon a headerbe; a brand-copy teszt kiterjesztése.
2. `GET /api/summoner/{game_name}/{tag_line}` + `/summoner/...` SSR-oldal (Account-V1 + rank).
3. Mastery-V4 portolása a `riot_client.py`-ba + `ChampionMastery` cache-tábla.
4. Régióválasztó a keresőoldalon (platform-kód → cluster-map a backendben).
5. **Domain + landing-merge (a §3 döntés kivitelezése):** az apex A-rekord már a VPS-re mutat →
   a `web.py` apexen szolgálása (Caddy/nginx reverse-proxy + Let's Encrypt TLS a `sylqon.com`-ra);
   a `landing/landing.html` hero-szekció beolvasztása a `web.py` `/` route-jába (a meglévő
   kereső-kártya fölé).
6. Production-key kérelem előkészítése (a működő több-oldalas web a `FEJLESZTESI_TERV §5.3`
   „working site" feltétele).

> **Kapcsolódó dokumentumok:** `docs/FEJLESZTESI_TERV.md` (a teljes 3-termékes roadmap; ez a
> terv annak §5/S3 web-fázisát részletezi és bővíti), `services/ingestion-svc/README.md`
> (a hosztolt szolgáltatás futtatása és API-ja).
