# Sylqon.com — Draft-gerinc újrapozicionálási terv

> Készült: 2026-07-14 · Ez a dokumentum **felváltja** a `WEB_FELULET_TERV.md` irányát.
> Alap: 3-ágú piaci/repo-kutatás + 6 független koncepció-irány kidolgozása és bírálata,
> majd tulajdonosi döntés (2026-07-14): **Draft-gerinc + radikális vágás**.
>
> **Egymondatos irány:** a sylqon.com megszűnik stat-oldalnak lenni, és műfajt vált —
> *a hely lesz, ahol draftolni tanulsz*: napi draft-rejtvény (Daily Draft) most,
> elemzős draft-szimulátor (Draft Lab) második ütemben, személyi edző (Coach) szárny
> harmadikban; minden más generikus oldal kikerül a navigációból és az indexből.

---

## 0. A döntés és az indoklása

**A probléma:** a jelenlegi site (kereső → profil → pool-riport → champion-meta →
leaderboard) abban a műfajban versenyez, ahol az op.gg / u.gg / lolalytics / mobalytics
verhetetlen — „még egy stat-oldal", nincs ok idejönni, pláne visszajönni.

**A piaci kutatás kulcs-tényei (2026-07-14):**

| Tény | Következmény |
|---|---|
| A fő játékos-panasz: a stat-oldalak megmondják **MIT** (winrate, grade), de nem **MIÉRT és MIT TEGYÉL** — a r/summonerschool tele van „review my op.gg" posztokkal | A magyarázat a differenciátor, nem az adat |
| A nagyok pageview-hirdetésből élnek: kevés-oldalas, magyarázó/játékos élmény nekik **modell-ellenes** — strukturálisan nem másolják le | A rés védhető |
| A **no-install szegmens** gazdátlan: sokan elvből nem telepítenek Overwolf/companion appot (bloat, ban-félelem, munkahelyi gép) | Webes, account-mentes, azonnal betöltő élmény kell |
| A Riot 2025-ös változásai (25.20 champ-select anonimitás, Spectator-V5 leállítás) az **identitás-alapú** scoutingot ölik (porofessor-modell) — a **komp-alapú, identitás-független** elemzést nem érintik | A Sylqon draft-intel magja pont a jövőálló kategória |
| A draftlol.dawe.gg bizonyítja a tömeges keresletet böngészős draft-UI-ra — de **nulla elemzési réteggel**; a webes AI-eszközök (LoLDraftAI) fekete dobozok, az iTero desktop-first | „Szimulátor + agy" a weben üres terep |
| A Loldle/Wordle/chess.com-daily-puzzle bizonyítja: a LoL-közönség **naponta** visszajár egy jó rejtvényért | A napi játék az egyetlen valódi napi-visszatérés mechanika |

**Miért ez a gerinc:** a Daily Draft, a Draft Lab és a „játszható demó" **ugyanarra az egy
motorra épül** (a `sylqon/analysis/draft_intel.py` pure-function portja + a `data/static.py`
táblák) — az első ütem megépítése a többi ~70%-át ingyen adja. A rejtvény egyben a desktop
app demója: a látogató átéli, milyen nehéz jól counter-pickelni, és pont ebben a pillanatban
kapja a CTA-t („ezt az app élőben hozza meg helyetted a champ selectben").

**Tulajdonosi döntések (2026-07-14, rögzítve):**
1. Gerinc: **Draft** (Daily Draft → Draft Lab → Coach-szárny ütemezve).
2. Régi oldalak: **radikális vágás** — csak az új élmény + pool-audit + letöltés marad
   első osztályú polgárként (részletek: §5).

---

## 1. Célarchitektúra

Ami **nem** változik: FastAPI build-mentes SSR (`services/ingestion-svc/app/web.py`),
Graphite Volt arculat, Riot-kulcs szerveroldalon, Postgres + Redis, Caddy TLS a VPS-en.
JS csak izolált szigetként (esbuild egyetlen fájl) — nincs Next/SPA.

```
  sylqon.com (apex, Contabo VPS)
  └─ ingestion-svc (FastAPI)
     ├─ web.py (SSR)
     │   ├─ /            főoldal = a mai rejtvény above-the-fold + letöltés CTA
     │   ├─ /daily       a napi draft-rejtvény (JS-sziget)
     │   ├─ /daily/{date} megoldás-archívum (SSR, SEO-felület)
     │   ├─ /draft       Draft Lab (Ü2, JS-sziget) + /d/{state} permalink
     │   ├─ /audit       pool-audit (a /pool-report utódja, 301)
     │   ├─ /download    letöltés + „miért merhetsz telepíteni" (lokális-first sztori)
     │   └─ /coach/...   Coach-szárny (Ü3)
     ├─ draftintel.py    ← ÚJ: a draft_intel pure-függvények portja
     ├─ data/draft_tables.json ← ÚJ: a static.py tag/threat/damage táblák bundle-je
     ├─ puzzles (cron)   ← ÚJ: rejtvény-generátor a saját Match-V5 állományból
     └─ bot.py           napi rejtvény-embed + guild-ranglista (meglévő infra)
```

**A motor-port szabálya (kritikus):** az ingestion-svc standalone, nem importálhat
`sylqon/`-t. A megoldás a bevált bundle-minta (mint `app/data/champions.json`):
- a `sylqon` repóban egy **export-script** a `data/static.py` tag/threat/damage tábláiból
  `draft_tables.json`-t generál;
- a `classify_comp`, `draft_balance`, `counter_pick_advice` (~285 sor, egyetlen függősége
  a static.py) **újraimplementálódik** `app/draftintel.py`-ként, a bundle-ből olvasva;
- **paritás-teszt** védi a driftet: ugyanarra a bemenetre a sylqon-oldali és a portolt
  motor kimenete azonos (offline teszt mindkét suite-ban, fixture-ökkel).

---

## 2. Ütem 1 — Daily Draft (MVP: ~2 hét, +1 hét polish)

### 2.1 A termék

Naponta egy **valódi, a saját 40k+ meccses Postgres-állományból** vett draft, az utolsó
pick előtt befagyasztva. A játékos látja: 4+5 champion, rank-sáv, patch, a saját role-ja.
**6 jelölt** közül választ; beküldés után:

1. **Pontozás + magyarázat** — a motor driver-chipekkel mutatja, mit adott a pick a
   komphoz (frontline, damage-mix, engage-válasz, CC, lane-matchup a saját
   `champion_matchups` aggregációból). Több elfogadható válasz van — a framing
   „a motor olvasata", nem „a helyes válasz".
2. **Epilógus — az ütőkártya, amit senki más nem tud:** „a valódi játékos X-et vitte,
   ezt buildelte (metabuild / tényleges itemek), és így alakult a meccs." Név nélkül,
   anonimizálva.
3. **Streak + megosztható emoji-rács** (Wordle-minta) — localStorage, se account, se login.
4. Záró CTA: „ezt a döntést a Sylqon app élőben hozza meg helyetted" → /download.

### 2.2 Építőelemek

| Elem | Mi kell hozzá | Státusz |
|---|---|---|
| Motor-port (`app/draftintel.py` + `draft_tables.json` + export-script + paritás-teszt) | §1 szerint | ÚJ (~3-4 nap) |
| Rejtvény-generátor (CLI/cron): tárolt meccs kiválasztása — teljes draft-adat, nem-remake, plat+ sáv; befagyasztás az utolsó pick előtt; 6 jelölt = valódi pick + a motor top-pickje + 4 plauzibilis a matchup-aggregációból; `DailyPuzzle` tábla | `matches`/`match_participants` KÉSZ, `champion_matchups` KÉSZ | ÚJ (~3 nap) |
| `GET /daily` SSR + kis JS-sziget (választás → pontozás → magyarázat → epilógus → emoji-rács + streak) | `web.py` `_page()` + page-cache minta KÉSZ | ÚJ (~4-5 nap) |
| `GET /daily/{date}` megoldás-archívum: mind a 6 jelölt kifejtve — napi friss, egyedi SEO-tartalom, a megosztott linkek landing-je | SSR-minta KÉSZ | ÚJ (~2 nap) |
| Magyarázó szövegek: sablon-alapú HU/EN (az `advice/messages.py` mintájára); LLM-próza később batch-ben (temp=0, seed=1337 a dev gépen → bundle, metasync-minta) | sablon-infra KÉSZ | ÚJ (~2 nap) |
| Discord-bot: napi rejtvény-embed + guild-ranglista | `bot.py` + `GuildConfig` + `Delivery` KÉSZ | bővítés (~2 nap) |
| Főoldal-hero csere: a mai rejtvény above-the-fold + letöltés CTA | — | ÚJ (~1 nap) |

### 2.3 Minőség-kapuk (a rejtvény-igazságosság a fő kockázat)

- A draft-heurisztika szándékosan durva (35–65% clamp) → **kezdeti kézi kurálás**: a
  generátor jelölteket ad, az élesítés előtt napi 1 perc emberi jóváhagyás (admin-lista
  a következő 7 nap rejtvényeiről; gyenge/kétértelmű draft eldobható).
- Több elfogadható válasz: a pontozás sávos (pl. „erős / védhető / kockázatos"), nem
  bináris jó/rossz — a magyarázat a termék, nem az ítélet.
- Ha a motor top-pickje és a valódi pick eltér, az explicit tananyag („a motor ezt
  látta — a valóságban ez történt"), nem hiba.

### 2.4 Kereslet-teszt és gate (2-3 hét élesben)

Mérés: napi visszatérők aránya, végigjátszási arány, emoji-rács megosztások,
Discord-embed átkattintás, /download klikk az epilógusból. Terjesztés: a meglévő magyar
LoL Discord-szerverek + 1-2 nemzetközi szerver + r/summonerschool poszt.
**Kill-kritérium:** ha 2-3 hét alatt a napi visszatérés és a megosztás nem mozdul,
olcsón buktunk — az Ü2 előtt irány-felülvizsgálat (a motor-port akkor is megmarad
a Draft Labhoz).

---

## 3. Ütem 2 — Draft Lab (~2-3 hét, az Ü1 gate után)

A rejtvény draft-boardja és a motor újrahasznosításával:

- **`GET /draft`** — szabad 5v5 szimulátor valós pick-orderben: minden változásra
  komp-osztályozás (confidence-szel), damage/frontline/CC chipek, clampelt mérleg
  driver-magyarázattal, counter-ablak jelzés („a B3 slotod counter-pozíció").
- **Permalink DB nélkül indulva:** a draft-állapot base64-ben az URL-ben
  (`/d/{state}`), SSR-elve renderelt elemzés + OG-meta — a „nézd, ezt kellett volna
  picknelni" viták landing-je. Később: rövid share-id + Pillow OG-kép.
- **Pool-integráció:** Riot ID megadásával a „melyik pickem a legjobb ide" panel a
  saját poolból rangsorol (`pool.py` KÉSZ) — itt ér össze a Draft Lab és az /audit.
- **Clash-mód (az ütem vége, opcionális):** 5 ellenfél-Riot-ID → comfort-pick térkép
  + ban-terv a tárolt Match-V5-ből — a porofessor-űr identitás-anonimitás-álló betöltése,
  felhasználó által önként megadott ID-kból.
- Desktop-hurok: az app „Share draft" gombot kap, ami az élő draftot web-permalinkké
  exportálja (Ü2 után, app-oldali munka).

---

## 4. Ütem 3 — Coach-szárny (~2-3 hét, opcionális, az Ü2 után)

A Riot ID-s felhasználók perszonalizált visszatérő lába, a **kész** advice-motorra:

- **`GET /coach/{region}/{name}/{tag}`** — anti-dashboard: az utolsó meccs top-1
  tanulsága bizonyítékkal (`advice/` pipeline KÉSZ), heti fókusz (a `report.py` már
  számolja a visszatérő tanulság-típust), „javult / nem javult" ítélet (irány, nem szám).
- **`GET /lesson/{match_id}/{puuid}`** — megosztható lecke-kártya; a Discord-bot
  advice-embedje ide mélylinkel (a bot a retention-motor, a web a landoló felület).
- Anti-ismétlődés szabály (ugyanaz a fókusz-típus csak romlás esetén térhet vissza) +
  a heurisztika-készlet bővítése a meglévő 👍/👎 feedback-log alapján.
- A generikus meccs-oldalakat NEM támasztjuk fel — a lecke-permalink a felület.

Ez az ütem adja a legjobb sztorit a **Riot production-key kérelemhez** is
(transzformatív coaching, nulla skill-score) — a kérelem az Ü1+Ü2 élesedése után
adható be, a Coach-szárny tovább erősíti.

---

## 5. Radikális vágás — a régi oldalak sorsa

Cél: egy erős élmény, nulla zaj. A „még egy stat-oldal" érzést az kelti, hogy a
navigáció és a főoldal a generikus lookup-ot tolja előre.

| Route | Sors | Megjegyzés |
|---|---|---|
| `/` | **Újraépül**: a mai rejtvény + letöltés CTA | A hero nem mesél — játszat |
| `/pool-report` | **301 → `/audit`**, újrakeretezve | „A személyes nehézségi térképed"; a rejtvényből ide vezet út („a poolod nem tudta megoldani a mai rejtvényt → ezt a 2 champot tanuld") |
| `/download` | Marad, bővül | Lokális-first / „miért merhetsz telepíteni" szekció (anti-Overwolf pozicionálás) |
| `/summoner/*`, `/match/*` | **Nav-ból ki, `noindex`, sitemap-ból ki** | 90 napig kiszolgálva, utána döntés: 301 az /audit-ra vagy 410 |
| `/leaderboard/*` | **Nav-ból ki, `noindex`, sitemap-ból ki** | Ugyanez a 90 napos kivezetési ablak |
| `/champions`, `/champion/{name}` | **Nav-ból ki, `noindex`** — de a kód marad | A friss perf-munka (composite index, stale-serve, warmer) nem vész el: az Ü2 counter-explorere / a Draft Lab champion-kontextusa később újrahasznosíthatja; a kivezetés végleges döntése az Ü2 után |
| Navigáció | **Daily · Draft Lab (Ü2) · Pool-audit · Letöltés** | Ennyi. |

SEO-következmény vállalva: a levágott oldalak organikus forgalma elvész — cserébe a
`/daily/{date}` archívum napi friss, egyedi tartalmat termel, ami hosszabb távon jobb
SEO-eszköz, mint a duplikált lookup-oldalak.

---

## 6. ToS- és compliance-őrség (minden ütemre kötelező)

- **Nincs skill-score sehol.** A rejtvény-pont a *rejtvény megoldását* méri
  (játékmechanika), nem meccs-adatból számolt játékos-ügyességet. A Coach-ítéletek
  irányok („javult"), nem számok. A `web.py` meglévő copy-tesztje **kiterjesztendő**
  minden új oldalra (`score`/`rating`/`grade`/`MMR` tiltólista a player-kontextusban).
- **Anonimizálás:** a rejtvénnyé tett valódi meccsekből név soha nem jelenik meg —
  csak pickek, rank-sáv, patch.
- **A motor nem diktál:** több elfogadható válasz + indoklás; a `draft_balance`
  kizárólag a beépített 35–65 clamp + „heurisztika, nem modell" framinggel.
- **IP:** a draft-board nem lehet a Riot-kliens vizuális klónja — saját Graphite Volt
  nyelvtan (a `ui/` LiveDraftView már ilyen), Data Dragon assetek, fan-content
  disclaimer.
- **LLM csak előre-generálva:** a hosztolt oldalon nincs futásidejű LLM — minden próza
  determinisztikus sablon vagy dev-gépi batch (temp=0, seed=1337) → bundle.

---

## 7. Kockázatok

| Kockázat | Kezelés |
|---|---|
| A napi játék hit-driven műfaj (a Wordle mögött ezer klón halt meg) | Olcsó teszt (2 hét MVP + kill-kritérium §2.4); Discord-disztribúció + magyar piac (nulla verseny) mint védőháló |
| A rejtvény önkényesnek érződik → a streak-motiváció elhal | Kézi kurálás + sávos pontozás + „motor olvasata vs. valóság" framing (§2.3) |
| Motor-drift a desktop app és a web-port között | Egyetlen forrás (export-script) + paritás-teszt mindkét suite-ban (§1) |
| SEO-veszteség a vágásból | Vállalt döntés; 90 napos kivezetési ablak + a /daily archívum mint új organikus felület |
| A rejtvény-forrás elfogy / egysíkú | 40k+ meccs nő tovább (ingest él); szűrők (rank-sáv, patch, role-rotáció) a változatosságra |

---

## 8. Első lépések (azonnal indítható)

1. Export-script a `sylqon` repóban: `data/static.py` táblák → `draft_tables.json`.
2. `app/draftintel.py` port (classify_comp, draft_balance, counter_pick_advice) +
   paritás-fixture-ök + offline tesztek.
3. `DailyPuzzle` tábla + rejtvény-generátor CLI (`python -m app.cli puzzle-gen`) +
   kurálási admin-lista.
4. `GET /daily` SSR + JS-sziget; `GET /daily/{date}` archívum.
5. Discord-bot napi embed.
6. Főoldal-hero csere + navigáció-szűkítés + noindex a levágott oldalakra +
   `/pool-report` → `/audit` 301.
7. Mérés bekötése (§2.4 metrikák) → 2-3 hét gate → Ü2 döntés.

> **Kapcsolódó:** `docs/WEB_FELULET_TERV.md` (meghaladott — a §3 infrastruktúra-részei,
> Caddy/TLS/domain, továbbra is érvényesek), `docs/FEJLESZTESI_TERV.md` (a 3-termékes
> roadmap; ennek web-fázisát ez a terv váltja).
