# Sylqon web — stratégia: app-first, a web szolgál

> Készült: 2026-07-16 · Ez a dokumentum **felváltja és lezárja** a `WEB_FELULET_TERV.md`,
> `WEB_DRAFT_TERV.md` és `WEB_WARROOM_TERV.md` irányait.
>
> **A döntés:** a sylqon.com **nem önálló termék**. Nem keresünk neki gerinc-élményt.
> A web az appot szolgálja ki: bemutatja, kipróbálhatóvá teszi, letöltésre visz.
> A fejlesztési energia oda megy, ahol a Sylqonnak **valódi árka** van — a desktop appba.

---

## 0. Miért — három halott irány tanulsága

| Irány | Mikor halt | Miért |
|---|---|---|
| **op.gg-stílusú webfelület** (`WEB_FELULET_TERV`) | 2026-07-14, leszállítás után | „Olyan, mint a többi száz stat-oldal, felesleges." |
| **Daily Draft** (`WEB_DRAFT_TERV`) | 2026-07-16, leszállítás és kipróbálás után | „Nem elég szórakoztató" + „nem látom a közönségét". |
| **War Room** (`WEB_WARROOM_TERV`) | 2026-07-16, **még a kód előtt** — a terv §6 verifikációs lépése ölte meg | A piaci állítás megdőlt (lásd §1). |

**A mintázat:** kétszer ugyanazon buktunk — *„ilyen már van, sok"*. A koncepció-műhelyek
következetesen **alábecsülték a versenyt**: a júliusi piactérkép a Clash-scoutingot
„alulszolgált niche"-nek írta le, miközben három élő ingyenes eszköz és maga a Riot
szolgálja ki. A tanulság nem az, hogy rosszul ötleteltünk, hanem hogy **a webes LoL-tér
telített** — minden szabadon kitalálható web-funkciót vagy megcsinált valaki, vagy a Riot
ad ingyen a kliensben.

**Ahol viszont egyedül vagyunk** (és amit senki nem tud lemásolni web-oldalról):
lokális LLM, élő champ select-olvasás az LCU-n, counter-loadout **automatikus injektálása**
a kliensbe, read-only in-game overlay. Ez a termék. Ide megy az energia.

---

## 1. A War Room bukásának bizonyítéka (2026-07-16, ellenőrizve)

A terv első munkalépése a ToS-feltevés igazolása volt. **Az igazolódott** — a Clash-nek
hivatalos, 7 perces, beépített scouting-fázisa van, tehát az identitás-scouting itt
legitim. Ugyanez a keresés viszont **megölte a piaci tézist**:

| Ki | Mit ad | Következmény a War Roomra |
|---|---|---|
| **Riot, a kliensben** ([Clash FAQ](https://support-leagueoflegends.riotgames.com/hc/en-us/articles/360000951548-Clash-FAQ)) | rank, top championök + winrate + KDA, mastery, korábbi Clash-adat — ingyen, 0 súrlódás | a **játékos-kártya réteg** feleslegessé válik |
| [clash.tips](https://clash.tips/about) | scouting + **ban-ajánlás** + per-játékos ban-winrate, ingyen | a **ban-terv réteg** foglalt |
| [clashanalyzer.gg](https://www.clashanalyzer.gg/) | „Advised Bans", meccstörténet, legjobb championök | ugyanaz, másodszor |
| [wards.lol](https://wards.lol/clash/) | Clash-scouting + 2026-os naptár, aktívan karbantartott | a niche lakott |

A koncepció állítása („a legközelebbi az op.gg multisearch, nulla szintézissel") **téves volt**.

> **Költség-tanulság:** a verifikáció 10 percbe került és 2 hét fejlesztést mentett meg.
> Minden jövőbeli irány első lépése maradjon: *„ki csinálja ezt ma, és mit ad a Riot ingyen?"*

---

## 2. Mi a web dolga mostantól

**Egy mondat:** megmutatni, mit tud az app, hitelesíteni, hogy megéri telepíteni, és
letöltésre vinni. Semmi több — de azt jól.

| Route | Szerep | Státusz |
|---|---|---|
| `/` | Termék-hero + a két élő eszköz mint belépő | **ÉL** |
| `/draft` (Draft Lab), `/d/{code}` | **A demó**: az app draft-intelligenciájának publikus, telepítés-mentes íze; megosztható permalink = organikus terjedés | **ÉL** |
| `/audit` (pool-audit) | Személyre szabás: „hol lyukas a poolod" → az app élőben foltozza | **ÉL** |
| `/download` | A bizalom-oldal: 100% lokális, no Overwolf, read-only in-game | **ÉL** |
| `/summoner`, `/match`, `/leaderboard`, `/champions` | Kivezetés alatt (noindex, 90 napos ablak) | **ÉL, noindex** |

**A web kész.** Nincs több gerinc-keresés. Karbantartás és apró csiszolás igen; új
web-termékvonal nem — hacsak nem jön olyan ötlet, ami átmegy az §1 verifikációs szűrőn.

---

## 3. Ami a webből megmaradt és értékes

- **Draft Lab** — az egyetlen webes draft-szimulátor, ami mögött motor van (a draftlol
  szimulátort ad adat nélkül; a Clash-eszközök adatot szimulátor nélkül). Ez az app
  legjobb demója, nem kell hozzá telepítés.
- **A draft-motor portja + paritás-híd** — a desktop és a web ugyanazt a motort futtatja,
  teszt védi a driftet.
- **A hosztolt adatréteg** (~100k Match-V5 meccs, aggregációk, benchmarkok) — az appot
  táplálja (`SYLQON_META_URL`), nem a webet.
- **Discord-bot** — post-game advice a linkelt fiókoknak; élő push-csatorna.

---

## 4. Nyitott ügyek (nem web-stratégia, de itt a helyük)

- **Prod táblák:** `daily_puzzles`, `gym_puzzles`, `gym_runs`, `puzzle_deliveries` — a kód
  már nem hivatkozza őket, üresen ülnek. Törlésük a tulajdonos explicit engedélyére vár.
- **Seed-crawl hiba:** `crawl_targets_pkey` duplikátum a bot-ban időnként megöl egy teljes
  crawl-kört (külön feladatként fut).
- **Ready Check / Pre-Flight** — a második műhely befutója (személyes meccs-brief a kész
  advice-motorra). Elvetve *most*, de a legolcsóbb elővehető opció, **ha** az app-oldali
  munka után visszatérünk a webhez — és **csak** az §1 szűrő után (a Mobalytics ezt csinálja).
