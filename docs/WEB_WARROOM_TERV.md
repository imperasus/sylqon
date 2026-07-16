# Sylqon.com — War Room: Clash & 5-stack draft-prep

> **ELVETVE (2026-07-16) — MÉG A KÓD ELŐTT, a saját §6 verifikációs lépése ölte meg.**
> A ToS-feltevés igazolódott (a Clash-scouting hivatalos, 7 perces fázis), de a piaci
> tézis megdőlt: három élő ingyenes eszköz (clash.tips, clashanalyzer.gg, wards.lol)
> csinálja ezt — ban-ajánlással együtt —, a játékos-kártya réteget pedig **maga a Riot
> adja a kliensben**. A „legközelebbi az op.gg multisearch, nulla szintézissel" állítás
> téves volt. Az érvényes irány: **`docs/WEB_STRATEGIA.md`** (app-first, a web szolgál).
> A dokumentum megmarad a bizonyíték és a tanulság kedvéért — ne kezdjük újra.

> Készült: 2026-07-16 · Ez a dokumentum **felváltja** a `WEB_DRAFT_TERV.md` irányát.
> Alap: a Daily Draft irány kivezetése utáni második koncepció-műhely (6 friss irány,
> a tulajdonos két kifogása mint mérce), majd tulajdonosi döntés: **War Room**.
>
> **Egymondatos irány:** a sylqon.com nem gyárt szórakozást és nem épít szokást —
> **egy meglévő, fájdalmas melót automatizál**: öt Riot ID-ból (a Clash-ellenfél
> rosterjéből) 60 másodperc alatt értelmezett scouting-riportot és ban-tervet ad,
> ott és akkor, amikor a csapat úgyis ezt csinálja.

---

## 0. Miért ez — a Daily Draft tanulsága

A Daily Draft (napi rejtvény + Gauntlet) leszállítva, kipróbálva, **elvetve** két okból,
és ez a két ok most a tervezési mérce:

| A bukás oka | Mit követel a következő iránytól |
|---|---|
| **„Nem elég szórakoztató"** — a pick→verdikt hurok nem húzott vissza | Ne mi gyártsuk a szórakozást. Az érték legyen **hasznosság**, a húzóerő pedig **külső, valós tét** — ne a mi tartalmunk minősége. |
| **„Nem látom a közönségét"** — a napi-rejtvény műfaj hit-driven | A közönség legyen **címezhető** (megnevezhető hely, ahol ma is ott vannak) és a szükségük **akut** (ma is elvégzik kézzel). |

A War Room mindkettőre strukturális választ ad:

- **A húzóerőt a Riot gyártja.** Minden Clash-kupa új bracket → új ellenfél → új riport.
  A visszatérési trigger külső esemény, valós téttel; nem kell szokást építenünk.
- **A munka ma is megvan, csak rosszul.** A draft-felelős a bracket-lock után 20–30 percet
  tölt öt op.gg-fül közt, kézzel jegyzetelve a Discordba. Ezt automatizáljuk.
- **A közönség címezhető.** Clash LFG Discordok, r/TeamRedditTeams, magyar LoL-szerverek —
  és időzíthető: a bracket-lock naptári esemény.

**Stratégiai bónusz:** a 2025-ös anonimitás-fordulat (25.20 + Spectator-V5 leállítás) az
identitás-alapú solo-queue scoutingot (porofessor-kategória) strukturálisan öli — a
**Clash-roster viszont Riot által szentesítetten látható**. Az egyetlen terepre állunk,
ahol az identitás-scouting legitim módon tovább él.
> **Az első munkalépés ezt igazolja** (§6): amíg nincs bizonyítva, hogy a Clash-scouting
> hivatalos fázis, addig a terv feltevésen áll.

---

## 1. A termék

**Bemenet:** 5 ellenfél-Riot-ID (a Clash-kliens megmutatja a rostert), opcionálisan a saját 5.
**Kimenet 60 másodperc alatt:** nem nyers profilok egymás mellett (azt adja az op.gg
multisearch), hanem **kész terv**:

| Réteg | Tartalom | Forrás |
|---|---|---|
| **Játékos-kártya** (×5) | becsült fő role, champion-pool comfort-pickekkel, forma, hivatalos rank | `pool.py` újracélozva + League-V4 |
| **Csapat-tendencia** | milyen komp-archetípus felé húznak (a leggyakoribb pickjeikből) | `draftintel.classify_comp` (portolva, ÉL) |
| **Ban-terv** | indokolt top-3 ban — *miért* az a champion | saját ~100k meccses `champion_matchups` |
| **Lane-fenyegetés** | melyik lane-en jön a nyomás, kire kell jungle-figyelem | `builds.py` matchup-aggregáció |
| **Átjáró** | egy kattintás a **már élő Draft Labbe**, az ellenfél pooljával előtöltve | `/draft?d=` (ÉL) |

**A hurok zárása:** a riport permalinkje a csapat-Discordjába kerül (a bot `/scout`
parancsa embedként posztolja) → a terv szimulálhatóvá válik a Draft Labben →
„ha ezt bannoljuk és ő erre megy, mi a válaszunk".

---

## 2. Oldaltérkép

| Route | Tartalom | Státusz |
|---|---|---|
| `/warroom` | Beviteli űrlap: 5 Riot ID, login nélkül | **ÚJ** |
| `/warroom/{slug}` | A megosztható riport (permalink) — a termék | **ÚJ** |
| `/warroom/{slug}/draft` | Átjáró a Draft Labbe, ellenfél-poollal előtöltve | **ÚJ** (a Lab él) |
| `/clash` | Clash-naptár landing: visszaszámláló, prep-checklist, SEO | **ÚJ**, Ü2 |
| `/draft`, `/audit`, `/download` | Változatlan — a War Room a Labbe vezet | **ÉL** |
| Discord `/scout` | 5 név → riport-embed + web-link a csapat-csatornába | **ÚJ**, Ü2 |

Navigáció: **War Room · Draft Lab · Pool audit · Download**.

---

## 3. Ütemezés

| Ütem | Tartalom | Elfogadás |
|---|---|---|
| **Ü1 — MVP (~1-2 hét)** | ToS-igazolás (§6) → `/warroom` űrlap + riport-oldal: játékos-kártyák + ban-terv + permalink. Se Draft Lab-átjáró, se bot-parancs. | A következő Clash-hétvége előtti keddre élesben; a riport 60 mp alatt kész és értelmezhető. |
| **Ü2 — A hurok (~2 hét)** | Draft Lab-átjáró (ellenfél-pool előtöltés), Discord `/scout`, `/clash` landing. | A riportból egy kattintás a szimulált draft; a bot a csapat-csatornába posztol. |
| **Ü3 — A völgy kitöltése (opcionális)** | Scrim-mód (mentett ellenfél-csapatok, heti prep-ritmus), HU tükör. | Csak ha az Ü1-2 kereslet-teszt él. |

### Kereslet-teszt (a §0 tanulsága: mérj, ne higgy)
Élesítés a következő **Clash-hétvége előtti kedden**; seed: 3-5 Clash LFG Discord +
r/TeamRedditTeams + magyar szerverek. **Három szám dönt:**
1. Hány riport készül a bracket-lock és a meccsek közti ablakban?
2. Hány riport-permalinket osztanak meg (külső referer)?
3. Hány riportból lép tovább valaki a Draft Labbe?

**Kill-kritérium:** ha az első Clash-hétvégén nem születik érdemi riport-szám, az irány
nem áll meg — és ezt egy hétvége alatt, olcsón tudjuk meg.

---

## 4. Mit hasznosítunk újra (a munka 70-80%-a kész)

- **Ingest-pipeline + Redis rate limiter + `resolved_riot_ids`** — Riot ID → meccstörténet, kvóta-takarékosan
- **`pool.py`** — a pool-elemzés újracélozva ellenfélre (comfort-pickek, lefedettség)
- **`draftintel.py`** (portolva, paritás-teszttel védve) — komp-archetípus tendencia
- **`builds.py` / `champion_matchups`** — a ban-terv és lane-fenyegetés indoklása
- **Draft Lab** (`/draft`, `/d/{code}`) — a szimulációs átjáró célpontja, permalink-mintával
- **Discord-bot guild-infra** — a `/scout` parancs otthona
- **HU/EN sablon-réteg** — a magyar piac mint nulla költségű első csatorna
- **Graphite Volt + a `/audit` üres-adat UX** (honesty-gate, `low_data` flag)

**Új kód:** lényegében a **szintézis-réteg** (5 profil → egy terv) és a riport-oldal.

---

## 5. Kockázatok — őszintén

| Kockázat | Kezelés / vállalás |
|---|---|
| **Burstiness + niche-plafon** (a fő kockázat) | Vállalt: a forgalom Clash-csúcsos, köztes völgyekkel. Az Ü3 scrim-mód tölthet, de ha a társas hurok nem indul be, a War Room egyszeri kíváncsiság marad. Ezt a kereslet-teszt egy hétvége alatt kimondja. |
| **Zajos role/pool-becslés** (smurf, off-role Clash-pick, rejtett profil) | Egy **tétes** meccs előtti rossz riport gyorsabban éget bizalmat, mint egy unalmas. Kötelező: mintaméret-jelzés minden állításnál, `low_data` flag, „nem tudjuk" ott, ahol nem tudjuk. |
| **Riot beépíti a kliens-scoutingot** | A mag-értékajánlat egy része ingyenessé válna. A védelem a **szintézis** (ban-terv + Draft Lab-átjáró), amit a kliens nem ad. |
| **ToS: identitás-scouting** | §6 az első munkalépés. Rejtett/streamer-mode profilok tisztelete (üres-adat UX, nem megkerülés). |

---

## 6. ToS-őrség (az első munkalépés!)

- **IGAZOLANDÓ ELSŐKÉNT:** a Clash-scouting hivatalosan szentesített fázis-e (a kliens
  maga mutatja az ellenfél-rostert). A terv erre a feltevésre épül — hiteles forrásból
  (Riot dev portál / Clash dokumentáció) igazolni kell, **mielőtt kód készül**.
- **Nincs skill-score.** Csak hivatalos rank + lefedettség/tendencia framing. A `web.py`
  copy-tesztje kiterjesztendő a riport-oldalra.
- **Nincs játékos-megbélyegzés.** A porofessor-féle „tilter / smurf / griefer" címkéket
  **tudatosan kerüljük** — a nyelvezet „felkészülés", nem „ítélet".
- **Rejtett profilok tisztelete** — üres-adat UX, sosem megkerülés.
- **Minden adat hivatalos Riot API-ból** (Match-V5, League-V4); ugyanaz a kategória, amit
  az op.gg multisearch évek óta csinál.

> **Kapcsolódó:** `docs/WEB_DRAFT_TERV.md` (meghaladott — a Daily Draft kivezetve; a
> motor-port, a Draft Lab és a §5 vágás onnan érvényben marad),
> `docs/WEB_FELULET_TERV.md` (meghaladott; infra-részei élnek).
