# Sylqon — Részletes fejlesztési terv (2026 H2)

> Készült: 2026-07-02 · Alap: a „Sylqon Product Development — Exploiting LoL Software Gaps"
> kutatási dokumentum + az S1–S10 ötletkatalógus + a repo aktuális állapotának auditja (v1.9.x).

---

## 0. Vezetői összefoglaló

A terv a Sylqon lokális draft-asszisztenst egy **háromtermékes portfólióvá** bővíti úgy, hogy a
már megírt elemző-motort (mission/match-review promptok, counters/synergies DB, pool-kezelés,
draft intel) hosztolt szolgáltatások mögé is beköti:

| Fázis | Termék | Rés | Időtáv | Cél |
|---|---|---|---|---|
| **0** | Közös alap: Riot-kulcs pálya + Match-V5 ingestion szolgáltatás | — | 0–2. hét | Production key előfeltételek, op.gg-kiváltás megkezdése |
| **1** | **„Egy tanács meccsenként" post-game Discord bot** (S2) + magyar lokalizáció (S10) | Iron–Gold coaching | 3–12. hét | Első bevétel, első hosztolt userbázis |
| **2** | **Champion-pool optimalizáló weboldal** (S3) | Személyre szabott pool vs. globális tier-lista | 9–16. hét (részben párhuzamos) | Production keyhez szükséges „working site" + freemium web |
| **3** *(feltételes)* | **Fearless Draft Copilot csapatoknak** (S1) | Bo3/Bo5 fearless prep | 17–28. hét | B2B/csapat-előfizetés — csak trakció esetén |

**Kulcsdöntés:** a hosztolt, skálázandó komponensek (Match-V5 ingestion, rate limiter, Discord
gateway, account-linking) **külön Spring Boot mikroszolgáltatásként** épülnek (Tomi natív
stackje), a Sylqon Python-kódbázisa pedig marad a lokális kliens-termék ÉS az elemző-logika
referencia-implementációja, amit a szerver-oldal portol vagy belső API-n hív.

**Fontos korrekció a kutatási dokumentumhoz képest:** a dokumentum állításával szemben a repo
**már tartalmaz hivatalos Riot REST API klienst** — `sylqon/riot/api.py` (Spectator-V5,
League-V4, Match-V5, Mastery-V4, `RIOT_API_KEY`-jel, konkurencia-budgettel és 429-backoff-fal),
és erre épülő scoutingot (`sylqon/riot/scout.py`: rank + match-history fingerprint, premade-
detektálás). Az op.gg-scraping kiváltása tehát **nem nulláról indul** — a Python-oldali
Match-V5 tapasztalat már megvan, a hiányzó elem a *szerver-oldali, több-felhasználós*
ingestion (production key, perzisztens tárolás, RSO account-linking, kvóta-gazdálkodás).

---

## 1. Kiindulási helyzet — mi van már kész a repóban

Repo-audit (2026-07-02, `master`, v1.9.x után):

### 1.1 Újrahasznosítható eszközleltár

| Meglévő modul | Mit tud | Melyik termékben hasznosul |
|---|---|---|
| `sylqon/riot/api.py` | Hivatalos Riot REST kliens: Spectator-V5, League-V4, Match-V5, Mastery-V4; szemaforos konkurencia-plafon, 429-kezelés | **Mind** — a Spring Boot ingestion referencia-implementációja |
| `sylqon/riot/scout.py` | PUUID-alapú fingerprint: rank, season W/L, premade-detektálás, champ-statisztika | S1 scouting, S3 pool-elemzés |
| `sylqon/ai/mission_prompt.py`, `ai/match_review.py` | Post-game elemzés: halálok, CS/min, vízió, eredmény → strukturált, validált missziók/review | **S2 magja** — az „egy tanács" generátor |
| `sylqon/ai/prompts.py`, `ai/engine.py` | Ollama engine (temp=0, seed=1337), counter-build promptok, kimenet-validálás statikus táblák ellen | S2 tanács-szöveg, S10 magyar válaszok |
| `sylqon/ai/lane_plan.py`, `ai/macro_coach_prompt.py`, `analysis/macro_coach.py` | Lane-terv és makró-coaching promptok | S2 prémium mélyelemzés |
| `sylqon/analysis/scoring.py`, `analysis/matchup.py`, `analysis/pairwise.py` | Champion-scoring, matchup- és páronkénti elemzés | **S3 magja** — pool-lefedettségi score |
| `sylqon/analysis/draft_intel.py` | Hálózat-mentes comp-osztályozás + counter-tanács | **S1 magja** |
| `sylqon/db/` (schema, queries, matches) | SQLite: champions, counters, synergies, matches, match_participants + migráció | Séma-előkép a Postgres-hez |
| `sylqon/data/static.py`, Data Dragon katalógus | Statikus rune/spell/item táblák, validáció; DDragon `hu_HU` locale elérhető | S10 magyar bot, minden validáció |
| `sylqon/rag/` | Item/rune/kit embedding-index + retrieval | S2/S3 tanács-minőség javítása |
| `ui/` (React) — LiveDraftView, Dashboard | Draft-board és pool-kezelő UI-minták | S1 draft-szoba, S3 web-UI előkép |
| `sylqon-overlay-shell/` | OBS browser-source overlay minta | S5 (backlog) |
| `.github/workflows/release.yml` | Tag-alapú release pipeline (PyInstaller + NSIS) | Minta az új szolgáltatások CI-jához |

### 1.2 Ami hiányzik (a közös „drága" rész)

1. **Production Riot API-kulcs** — regisztrált termék, hosztolt weboldal + ToS + Privacy Policy
   szükséges hozzá (GitHub-repót a Riot nem fogad el).
2. **Szerver-oldali, több-felhasználós Match-V5 ingestion** — rate-limit-aware crawler,
   perzisztens tárolás (Postgres), region-routing (europe cluster), kvóta-gazdálkodás
   felhasználók közt.
3. **RSO (Riot Sign-On) account-linking** — hogy a Discord-user a saját Riot-fiókját kösse be,
   és ne kelljen név alapján keresgélni.
4. **Discord gateway** — JDA-alapú bot, slash-parancsok, meccs-utáni proaktív üzenet.
5. **Számlázás/előfizetés** — Stripe (vagy Discord-natív előfizetés a botokhoz).

Ez az öt elem **egyszer épül meg** (Fázis 0–1), és mindhárom termék erre ül rá.

---

## 2. Célarchitektúra

```
                    ┌──────────────────────────────────────────────┐
                    │              HOSZTOLT (K8s / VPS)            │
                    │                                              │
 Riot Match-V5 ────▶│  ingestion-svc (Spring Boot)                 │
 League-V4          │   · Redis token-bucket rate limiter          │
 Spectator-V5       │   · match + timeline crawler, region-routing │
                    │   · Postgres (matches, participants,         │
                    │     timelines, users, riot_accounts)         │
                    │                    │                         │
                    │        ┌───────────┼──────────────┐          │
                    │        ▼           ▼              ▼          │
                    │  advice-svc    pool-svc       scout-svc      │
                    │  (S2 tanács-   (S3 pool-      (S1 fearless,  │
                    │   heurisztikák) aggregáció)    Fázis 3)      │
                    │        │           │              │          │
                    │        ▼           ▼              ▼          │
                    │  discord-gw     web (S3/S1)   OBS endpoints  │
                    │  (JDA, slash    HTMX/Thymeleaf                │
                    │   + proaktív    vagy React                    │
                    │   post-game)                                  │
                    └──────────────────────────────────────────────┘
                                     ▲
                                     │ belső API / portolt heurisztikák
                    ┌────────────────┴─────────────────┐
                    │  LOKÁLIS: Sylqon (Python/FastAPI) │
                    │  · LCU draft-asszisztens + inject │
                    │  · in-game overlay coach          │
                    │  · Ollama LLM (privát, lokális)   │
                    │  · marad önálló, ingyenes termék  │
                    └───────────────────────────────────┘
```

**Elvek:**

- **A Sylqon lokális termék marad, változatlan pozicionálással** (privát, LLM-alapú,
  ellenfél-adaptív, Overwolf-mentes). Az LCU-injektálás **kizárólag lokális, opt-in** funkció
  marad — soha nem lesz a hosztolt szolgáltatás magja (ToS-kockázat minimalizálása).
- **Heurisztika-portolás iránya:** a Python-oldali elemzők (`mission_prompt`, `scoring`,
  `matchup`) az igazságforrás; a Spring-oldal első körben **belső HTTP-hívással** használja
  őket (a Sylqon-kód FastAPI-ként konténerbe csomagolva), és csak bizonyított terhelésnél
  portolunk Javára. Így nincs kettős karbantartás az MVP-fázisban.
- **LLM a szerveren:** az Ollama-minta (temp=0, seed=1337, kimenet-validálás) átvihető;
  hosztolt környezetben vLLM/Ollama egy GPU-s node-on, vagy — költségküszöbig — kis
  hosted-modell API. A tanács-generálás determinisztikus és cache-elhető meccs-ID szerint.
- **Adatmodell:** a meglévő SQLite-séma (`db/schema.py`) a Postgres-séma kiindulópontja;
  új táblák: `users`, `riot_accounts` (RSO), `guild_configs` (Discord), `subscriptions`,
  `timelines`, `advice_log` (kiadott tanácsok + visszajelzés).

---

## 3. Fázis 0 — Alapozás (0–2. hét)

**Cél:** minden későbbi munka előfeltételeinek letudása + a közös ingestion-infrastruktúra váza.

### 3.1 Riot Developer Portal pálya

- [ ] Personal API key regisztrálása (20 hívás/mp, 100 hívás/2 perc, 24 óránként megújítandó) —
      a prototípus-fejlesztéshez elég.
- [ ] Production key kérelem **előkészítése**: a Riot működő, tesztelhető appot akar látni →
      a beadás valós időpontja a Fázis 2 (S3 weboldal) élesedése. Addig: terméknév, leírás,
      ToS + Privacy Policy szöveg elkészítése, domain regisztrálása.
- [ ] A monetizációs terv előzetes egyeztetése a portálon (kötelező ingyenes tier; a fizetős
      tartalom „transformative" — lásd 9. fejezet compliance-táblázat).

### 3.2 Ingestion-szolgáltatás váz (Spring Boot)

- [ ] `ingestion-svc` skeleton: Spring Boot 3 + Postgres + Redis; Riot-kliens a
      `sylqon/riot/api.py` mintájára (region-routing: `europe` mass-cluster Match-V5-höz,
      platform-route League-V4-hez).
- [ ] **Rate limiter:** Redis token-bucket, két szint (per-second + per-2-minute ablak),
      kulcsonként és régiónként; 429 `Retry-After` tisztelete. Ez a komponens a production
      key-nél is változatlanul használható (csak a limitek nőnek).
- [ ] Crawler-queue: PUUID-alapú feladatok (match-ids → match → timeline), idempotens mentés,
      deduplikáció match-ID szerint. K8s-en worker-podok; MVP-ben egyetlen VPS-en is elfut.
- [ ] Séma-migráció: Flyway; a `matches` / `match_participants` táblák a meglévő SQLite-séma
      Postgres-portja + `timelines` (JSONB).

### 3.3 op.gg-kiváltási terv (Sylqon lokális termék)

A jelenlegi op.gg belső-API-scraping a Riot „supported services for data ingestion" előírásával
ütközik, és törékeny. Ütemezett kiváltás:

- [ ] Meta/build-adat forrásváltás felmérése: mi jön ma op.gg-ből (`cache/opgg_fetch.py`,
      `cache/opgg.py`), és mi állítható elő saját Match-V5 aggregációból (item-buildek,
      rune-winrate-ek rank-sávonként).
- [ ] Átmeneti időszakban az op.gg-függés **csak a lokális, nem-monetizált** Sylqonban marad;
      a hosztolt termékek **kizárólag** hivatalos Riot API-ból dolgoznak, első naptól.
- [ ] Célállapot (Fázis 2 végére): a saját aggregáció (pool-svc) adja a meta-adatot a lokális
      Sylqonnak is → az op.gg-scraping teljesen kivezethető.

**Fázis 0 kilépési kritérium:** personal key-jel egy megadott summoner utolsó 20 meccse +
timeline-ja bekerül Postgres-be, rate-limit-sértés nélkül, ismételt futtatásra idempotensen.

---

## 4. Fázis 1 — „Egy tanács meccsenként" Discord bot (S2) + magyar lokalizáció (S10) — 3–12. hét

**Pozicionálás:** a Mobalytics/Blitz dashboard-káosza ellen a „kevesebb, de emészthető" —
meccs után a bot **egyetlen**, kontextusos, magyarul is elérhető tanulságot ír be Discordra.
Célszegmens: Iron–Gold, először a magyar közösségen validálva (S10 = disztribúciós csatorna,
nem külön termék).

### 4.1 Architektúra-elemek

| Komponens | Stack | Tartalom |
|---|---|---|
| `discord-gw` | Spring Boot + JDA | Slash-parancsok (`/link`, `/utolsomeccs`, `/beallitas`), guild-onboarding, proaktív post-game üzenet |
| `advice-svc` | Spring Boot (+ Python heurisztika-konténer belső API-n) | Timeline → tanács-pipeline: heurisztikák futtatása, top-1 kiválasztás, LLM-szövegezés, validálás |
| Account-linking | RSO OAuth2 (fallback: Riot ID + megerősítő meccs-ellenőrzés) | Discord user ↔ PUUID összerendelés |
| Meccs-figyelő | ingestion-svc ütemezett poll (linked PUUID-k, 2–5 perces ciklus) | Új meccs észlelése → advice-pipeline trigger |

### 4.2 Az öt induló heurisztika (MVP)

A `ai/mission_prompt.py` / `ai/match_review.py` logikájából kiindulva, Match-V5 timeline-ra
fogalmazva; mindegyik determinisztikus szabály, súlyozott „legfontosabb tanulság" kiválasztással:

1. **Halál-kontextus** — halálok osztályozása: létszámhátrányban / vision nélküli zónában /
   rossz wave-állapotnál / objective-trade-ben (percenkénti pozíció-snapshot + event-ek;
   ez az S7 „halál-audit" szabályalapú első verziója, az ML-réteg későbbi csere).
2. **CS-benchmark** — CS@10/CS@15 a saját rank-sáv medánjához képest, role-bontásban.
3. **Item-timing** — első/második core-item elkészülte vs. rank-benchmark; „halott" arany
   (befejezetlen komponensek hosszan az inventoryban).
4. **Vízió** — ward-elhelyezés/percek, control ward-vásárlás, halál-korreláció sötét zónákkal.
5. **Objective-jelenlét** — csapat-objective-eknél (drake/herald/baron) való részvétel aránya,
   TP/rotáció-késés.

A kiválasztott top-1 tanulságot az LLM önti 2–3 mondatos, közérthető szöveggé (magyar/angol),
a kimenet a meglévő validációs mintával ellenőrizve (nincs hallucinált item/rúna-név).

### 4.3 Sprint-bontás (10 hét, 2 hetes sprintek)

| Sprint | Hét | Tartalom | Kilépési kritérium |
|---|---|---|---|
| 1 | 3–4. | discord-gw skeleton, `/link` (Riot ID fallback-kel), ingestion-svc rákötés, meccs-detektálás | Bot észreveszi a linkelt user új meccsét |
| 2 | 5–6. | 1–2. heurisztika (halál-kontextus, CS-benchmark) + top-1 kiválasztó + sablonos (LLM nélküli) üzenet | Első automatikus post-game tanács élesben |
| 3 | 7–8. | 3–5. heurisztika, LLM-szövegezés + validálás, magyar lokalizáció (DDragon `hu_HU`), `/utolsomeccs` | Mind az 5 heurisztika fut, HU+EN kimenet |
| 4 | 9–10. | Zárt béta 2–3 magyar Discord-szerveren; visszajelzés-gomb (👍/👎) a tanács alatt → `advice_log`; rank-benchmark táblák feltöltése saját aggregációból | ≥50 aktív linkelt fiók, visszajelzési arány mérve |
| 5 | 11–12. | Prémium tier (heti összefoglaló, trend-riport, multi-account), Stripe/Discord-előfizetés, RSO-ra átállás ha a jóváhagyás megvan | Fizetős tier élesben (3–5 €/hó) |

### 4.4 S10 — magyar lokalizáció mint beépített funkció

Nem külön bot: a discord-gw minden parancsa és a tanács-szöveg guild-szinten `hu`/`en`
nyelvre állítható. Plusz két olcsó, közösségépítő parancs a meglévő adatokból:
`/build <champion>` (aktuális meta-build a saját aggregációból, magyar item-nevekkel) és
`/matchup <champ> <champ>` (a counters/synergies DB-ből). Terjesztés: meglévő magyar LoL
Discord-szerverek — nulla user-acquisition-költség, ez a validációs terep.

### 4.5 Monetizáció (S2)

- **Ingyenes:** 1 tanács/meccs, `/build`, `/matchup`, `/utolsomeccs`.
- **Prémium (3–5 €/hó):** heti trend-összefoglaló, mélyelemzés (lane-terv a
  `ai/lane_plan.py` mintájára), multi-account, coach-nézet (más játékos riportja engedéllyel —
  ez az S6 „homework" irány magja, későbbi upsell).
- ToS-megfelelés: az ingyenes tier érdemi (nem csonka), a prémium *transzformatív* elemzést
  ad, nem nyers adatot zár paywall mögé.

---

## 5. Fázis 2 — Champion-pool optimalizáló weboldal (S3) — 9–16. hét (részben párhuzamos)

**Kettős cél:** (1) önálló freemium termék — személyre szabott, *poolban gondolkodó* ajánlás a
globális tier-listák ellenében; (2) **ez a hosztolt weboldal kell a production key
kérelemhez** — ezért a 11–12. héten (Fázis 1 vége felé) már be kell adni a kérelmet ezzel.

### 5.1 Funkcionális mag

- Riot ID beadása → mastery + match-history + rank lekérés → jelenlegi pool felmérése
  (a Sylqon pool-kezelés és `analysis/scoring.py` / `matchup.py` / `pairwise.py` logikájára építve).
- **Pool-lefedettségi score:** blind-pick biztonság + counter-lefedettség + a játékos tényleges
  teljesítménye (WR, minta-méret) együtt; 3 fős pool-javaslat role-onként, indoklással.
- Rank-sávos matchup-statisztika a **saját Match-V5 aggregációból** (pool-svc) — ez ugyanaz az
  adat, ami az S2 benchmarkjait és a lokális Sylqon op.gg-kiváltását is táplálja.
- Heti pool-riport batch-job → e-mail/Discord push (S2-vel közös gateway).

### 5.2 Műszaki terv

- `pool-svc` (Spring Boot): éjszakai aggregációs batch (rank-sáv × role × matchup winrate,
  minimum minta-küszöbbel), materializált nézetek Postgresben.
- Web-frontend: **HTMX/Thymeleaf** az MVP-hez (nem kell React-mélyvíz; a meglévő `ui/` minták
  csak vizuális referenciák). Publikus, SEO-barát champion/matchup-oldalak = organikus
  csatorna.
- **Framing-szabály (ToS):** a score-ok *pool-lefedettséget* mérnek, kifejezetten **nem**
  MMR/ELO-alternatívát — a „no MMR/ELO calculator" tiltás miatt a kommunikációban és a
  UI-szövegekben is kerülendő minden skill-rating jellegű címke.

### 5.3 Mérföldkövek

| Hét | Mérföldkő |
|---|---|
| 9–10. | pool-svc aggregációs batch + első matchup-táblák (EUNE/EUW mintán) |
| 11–12. | Weboldal MVP: Riot ID → pool-audit riport; ToS+Privacy oldalak; **production key kérelem beadása** |
| 13–14. | 3 fős pool-ajánló + indoklás (LLM-szövegezés a meglévő prompt-mintákkal); freemium korlátok |
| 15–16. | Prémium filterek (patch-szűrés, role-mélyelemzés), heti riport-push; a lokális Sylqon átkötése a saját meta-adatra (op.gg-kivezetés kezdete) |

### 5.4 Monetizáció (S3)

Freemium web: ingyen a pool-audit + alap-ajánlás; prémium (4–6 €/hó, az S2-vel közös
előfizetésben „Sylqon Plus" néven) a szűrők, heti riport, korlátlan újraszámolás.

---

## 6. Fázis 3 (feltételes) — Fearless Draft Copilot csapatoknak (S1) — 17–28. hét

**Indítási feltétel (go/no-go a 16. héten):** az S2+S3 együtt ≥500 aktív felhasználó VAGY az
S3 ingyen→fizetős konverzió >5%. Ha nincs meg, a fázis csúszik, és a fókusz a meglévő két
termék retenciójára megy.

- **Mag:** multi-team workspace; Bo3/Bo5 **fearless állapotgép** (meccsek közt zárolt
  championok); ellenfél-scouting Match-V5-ből (a `riot/scout.py` fingerprint + premade-
  detektálás kiterjesztése csapatokra); pool-lefedettségi mátrix („melyik champot égeti el az
  ellenfél az 1. meccsen") — a `analysis/draft_intel.py` comp-osztályozás szerver-oldalra kötve.
- **UI:** itt már kell interaktív draft-board — a meglévő `ui/` LiveDraftView React-komponensei
  a kiindulópont; megosztható draft-szoba (WebSocket).
- **Custom-game adat:** csapat-scrimek meccsei csak opt-in/RSO-val érhetők el — a scouting
  alapja a publikus soloQ-történet.
- **Monetizáció:** csapat-előfizetés 30–80 €/hó; a szimulátor a 2. iteráció, az MVP a
  scouting-riport.
- Versenytárs-figyelés (drafter.lol, scoutahead.pro, DraftCore): a rés a *fearless-specifikus
  analitika* + pool-lefedettség, nem a tábla-funkció — oda nem érdemes belépni.

---

## 7. Backlog — tudatosan elhalasztva / elvetve

| Ötlet | Állapot | Indok |
|---|---|---|
| S7 halál-audit ML | **Beépül az S2-be** | Az MVP szabályalapú (4.2/1. heurisztika); ML-csere (Python microservice) csak ha a 👍/👎 adat indokolja. A timeline percenkénti felbontása miatt a plafon „jó heurisztika" — ezt a UX vállalja fel. |
| S6 coach-homework | **S2 upsell-irány** | A coach-nézet + auto-validált feladatok az advice-svc kiterjesztése; önálló termékként csak S2-trakció után. |
| S4 scrim-bróker | Elhalasztva | Tournament-V5 jóváhagyás + hideg-start; akkor releváns, ha az S1 csapat-ügyfélkör megvan. |
| S5 liga-motor | Elhalasztva | Tournament-V5 provider-regisztráció (callback gTLD/CA-korlátok) magas belépő; az OBS-overlay minta (`sylqon-overlay-shell/`) megvan hozzá, ha B2B kereslet igazolódik. |
| S8 patch-előrejelző | Backlog | Ígéretes rés, de saját historikus aggregáció kell előbb (a pool-svc mellékterméke lehet a 2. fázis után). |
| VOD/CV-elemzés | **Elvetve** | Nincs hivatalos replay-API, CV-költség aránytalan. |
| ❌ Riot-API-proxy B2B | **Tilos** | „No data broker" szabály — nem építjük meg. |

---

## 8. A lokális Sylqon termék karbantartása a fázisok alatt

- A lokális app marad az ingyenes „zászlóshajó" (privát, LLM-alapú, ellenfél-adaptív — a
  Blitz/U.GG statikus buildjeivel szembeni fő differenciátor), és a hosztolt termékek
  funnel-csúcsa.
- **LCU-szabályok betartása:** kiadás előtt Riot-értesítés; csak engedélyezett endpointok;
  Korea-régió kizárása a terjesztésből; az injektálás opt-in marad.
- README tesztszám-ellentmondás javítása (README „29" vs CLAUDE.md „~116") — apró, de a
  production key-elbírálásnál a repo-minőség számít.
- Változás-minimum: a fázisok alatt a lokális termékbe csak (1) a saját meta-adat-forrásra
  átkötés (op.gg-kivezetés) és (2) hibajavítások mennek.

---

## 9. ToS / compliance ellenőrzőlista (minden release előtt átfutandó)

| Szabály | Következmény a tervre | Státusz-gate |
|---|---|---|
| Dev key: 20/s, 100/2 min, 24 h lejárat; production: 500/10 s, 30 000/10 min | Fázis 0–1 personal key-jel; tömeges aggregáció (S3 batch) csak production key után skálázható | Fázis 2, 12. hét |
| Kötelező ingyenes tier; fizetős tartalom „transformative" | Freemium-struktúra a 4.5/5.4 szerint; nyers adat sosem kerül paywall mögé | Minden árazási döntés |
| „No data broker" | API-proxy irány tiltva; a saját aggregált statisztika publikus weben OK, tömeges adat-továbbadás API-ként NEM | Állandó |
| „Supported services for data ingestion" | op.gg-scraping kivezetése (3.3); hosztolt termékek első naptól csak Riot API | Fázis 2 vége |
| Nincs a kliensben nem látható, játék-szesszió-specifikus infó; app nem „diktálhat" döntést | Overlay/missziók maradnak a jelenlegi (megfelelő) mintán: több választás, csak látható infó | Overlay-változtatásoknál |
| No MMR/ELO calculator; no Augment/Arena winrate | S3 framing: „pool-lefedettség", nem skill-rating; Arena-adat kizárva az aggregációból | S3 UI-szövegek |
| LCU: Riot-értesítés kiadás előtt, engedélyezett endpointok, Korea tiltott | Lokális termék release-folyamatába beépítve | Minden Sylqon-release |
| Rejtőzködő játékosok elemzése tilos | Scouting csak publikus profilokra; opt-out tisztelete | S1/S3 |
| Tournament: 70% prize pool, min. 20 fő, EU-szervezői szabályzat | Csak S4/S5-nél releváns (backlog); szoftver-eladásnál a compliance szerződésben a szervezőé | Backlog |

---

## 10. Kockázatok és döntési küszöbök

| Kockázat | Valószínűség | Terv |
|---|---|---|
| **Production key elutasítás** | Közepes | Fallback: lokális-first modell marad; a Discord bot csak a felhasználó saját (RSO-val linkelt) fiókjának adatait dolgozza fel personal-key-kvótán belül; skálázás befagyasztva az újrabeadásig |
| S2 bot 30 nap alatt <500 aktív user | Közepes | Nem skálázunk K8s-re — minden marad egy VPS-en; a magyar közösségi terjesztést erősítjük, mielőtt fizetett csatornába mennénk |
| S3 konverzió >5% | (pozitív küszöb) | S1 (Fázis 3) előrehozása az S5/S8 backlog elé |
| op.gg belső API törik a migráció előtt | Magas | A seed-fallback (`cache/seed.py`) már ma véd; a kiváltás (3.3) prioritása nő |
| Riot API-szabályváltozás | Alacsony/folyamatos | Minden monetizációs lépés előzetes egyeztetése a Developer Portalon; a 9. fejezet táblázata release-gate |
| Egy-fejlesztős terhelés (3 termék párhuzamosan) | Magas | A fázisolás szigorúan szekvenciális kilépési kritériumokkal; párhuzamosság csak ott, ahol közös a komponens (ingestion, gateway); backlog fegyelmezetten zárva |
| LLM-hosting költség a szerveren | Közepes | Tanács-cache meccs-ID szerint (determinisztikus kimenet); sablonos fallback LLM nélkül; GPU csak mért igénynél |

---

## 11. Összefoglaló idővonal

```
Hét:   0  2  4  6  8  10 12 14 16 18 20 22 24 26 28
       ├──┤                                            Fázis 0: kulcs + ingestion-váz
          ├─────────────────────┤                      Fázis 1: S2 bot (+S10 HU)  → fizetős tier a 12. héten
                    ├───────────────────┤              Fázis 2: S3 web  → production key kérelem a 12. héten
                                        ◆              GO/NO-GO (16. hét): ≥500 user vagy >5% konverzió
                                        ├─────────────▶ Fázis 3: S1 Fearless Copilot (feltételes)
```

**Első 2 hét teendői (azonnal indítható):**
1. Personal API key regisztrálása a Developer Portalon.
2. `ingestion-svc` repo létrehozása (Spring Boot 3 + Postgres + Redis skeleton, Flyway-séma a
   meglévő `db/schema.py` alapján).
3. Redis token-bucket rate limiter + Match-V5 crawler (a `sylqon/riot/api.py` viselkedésének
   portja: konkurencia-plafon, 429 `Retry-After`).
4. Domain + ToS/Privacy szövegek előkészítése a production key kérelemhez.
5. README tesztszám-javítás + a `sylqon/riot` modul dokumentálása a CLAUDE.md-ben (a repo
   „kirakat-minősége" a key-elbírálás része).
