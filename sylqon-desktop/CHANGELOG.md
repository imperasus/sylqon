# Changelog

All notable changes to this project will be documented in this file. See [standard-version](https://github.com/conventional-changelog/standard-version) for commit guidelines.

## [1.29.0](https://github.com/imperasus/sylqon/compare/v1.28.0...v1.29.0) (2026-07-14)


### Features

* **web:** Draft Gauntlet (/gym) — ten drafts, thirty points, honest board ([ef534a5](https://github.com/imperasus/sylqon/commit/ef534a531b65b87e388cd33c61b00577f0b6863b))

## [1.28.0](https://github.com/imperasus/sylqon/compare/v1.27.0...v1.28.0) (2026-07-14)


### Features

* **web:** Draft Lab (/draft) — the simulator that talks back ([4255603](https://github.com/imperasus/sylqon/commit/4255603250d5ec40cd62dc491b61b035ad5bffcf))

## [1.27.0](https://github.com/imperasus/sylqon/compare/v1.26.0...v1.27.0) (2026-07-14)


### Features

* **bot:** daily Daily-Draft teaser embed into guild channels ([369f315](https://github.com/imperasus/sylqon/commit/369f315a8fb47ab0abd55d49e3a4dc51a1dd5518))

## [1.26.0](https://github.com/imperasus/sylqon/compare/v1.25.0...v1.26.0) (2026-07-14)


### Features

* **web:** the radical cut — puzzle-first homepage, /audit, /download, noindex sunset ([426f2eb](https://github.com/imperasus/sylqon/commit/426f2eb6dd87cc858077195103d8a1c0ef6b1ea9))

## [1.25.0](https://github.com/imperasus/sylqon/compare/v1.24.11...v1.25.0) (2026-07-14)


### Features

* **ingestion-svc:** draft-intel engine port with cross-suite parity bridge ([8d7f101](https://github.com/imperasus/sylqon/commit/8d7f10185503fe82440169fba08a3e06e153d518))
* **web:** Daily Draft puzzle (/daily) — generator, pages, curation CLI ([339c711](https://github.com/imperasus/sylqon/commit/339c711fab1f9f2d3e168d6259b434380dcbdd08))

### [1.24.11](https://github.com/imperasus/sylqon/compare/v1.24.10...v1.24.11) (2026-07-13)


### Bug Fixes

* **ingestion-svc:** survive the deploy-time index-creation race ([1ffb1f8](https://github.com/imperasus/sylqon/commit/1ffb1f838da112d798a3b9e6830ba0af380b7808))

### [1.24.10](https://github.com/imperasus/sylqon/compare/v1.24.9...v1.24.10) (2026-07-13)


### Performance

* **web:** champion pages — composite index, stale-serve, startup warmer ([a1d9213](https://github.com/imperasus/sylqon/commit/a1d92133b5237a7c9a3ecf83e5a39e7202c6e220))

### [1.24.9](https://github.com/imperasus/sylqon/compare/v1.24.8...v1.24.9) (2026-07-13)


### Bug Fixes

* **web:** /champions/{name} redirects to the champion page ([aab5625](https://github.com/imperasus/sylqon/commit/aab5625b8aca0196a9dc927d83e6a25f456b07c3))

### [1.24.8](https://github.com/imperasus/sylqon/compare/v1.24.7...v1.24.8) (2026-07-13)


### Bug Fixes

* **ingestion-svc:** bound and stream the full-history aggregation scans ([9c86f29](https://github.com/imperasus/sylqon/commit/9c86f294de3dcb9b4fb1191daa4f5a652c2b2a8a))

### [1.24.7](https://github.com/imperasus/sylqon/compare/v1.24.6...v1.24.7) (2026-07-12)


### Performance

* **ingestion-svc:** raise prod Postgres buffers past the 128MB default ([4cdf9d0](https://github.com/imperasus/sylqon/commit/4cdf9d09a218e28a354fe1e82a4d71d54b6f7694))

### [1.24.6](https://github.com/imperasus/sylqon/compare/v1.24.5...v1.24.6) (2026-07-12)


### Performance

* **ingestion-svc:** cache rendered champion pages ([2fbf5f6](https://github.com/imperasus/sylqon/commit/2fbf5f6290a8a31dc572127aee9eebecfcf05023))

### [1.24.5](https://github.com/imperasus/sylqon/compare/v1.24.4...v1.24.5) (2026-07-12)


### Performance

* **ingestion-svc:** index the champion page's hot paths ([67e6a18](https://github.com/imperasus/sylqon/commit/67e6a1821676fc7cff919b9dfa03214c2dbf5fa0))

### [1.24.4](https://github.com/imperasus/sylqon/compare/v1.24.3...v1.24.4) (2026-07-10)


### Bug Fixes

* **web:** leaderboard names resolve from puuid; bare /leaderboard redirects ([c48b48d](https://github.com/imperasus/sylqon/commit/c48b48d0021f517eb2d82d7c59080a3460990fe3))

### [1.24.3](https://github.com/imperasus/sylqon/compare/v1.24.2...v1.24.3) (2026-07-10)


### Performance

* **ingestion-svc:** SQL self-join aggregate replaces ORM row scan in matchup() ([f027aaa](https://github.com/imperasus/sylqon/commit/f027aaaba863e17d299b907d1e05857a486bfe18))

### [1.24.2](https://github.com/imperasus/sylqon/compare/v1.24.1...v1.24.2) (2026-07-10)


### Performance

* **web:** SQL slot extraction on the public champion page ([3cde7f4](https://github.com/imperasus/sylqon/commit/3cde7f4d9c6b822277ec2834d7955f8852ec1533))

### [1.24.1](https://github.com/imperasus/sylqon/compare/v1.24.0...v1.24.1) (2026-07-10)

## [1.24.0](https://github.com/imperasus/sylqon/compare/v1.23.0...v1.24.0) (2026-07-10)


### Features

* **deploy:** serve sylqon.com via Caddy with automatic TLS ([9acae1f](https://github.com/imperasus/sylqon/commit/9acae1fa5c44295b28c5a6e0f5d31eabd3f45e59))
* **web:** apex leaderboard page + champion-meta polish ([b41f4c5](https://github.com/imperasus/sylqon/commit/b41f4c580fb70ec57c5c201adc4ab462caaf1859))
* **web:** coaching insights on the summoner profile ([ee047d1](https://github.com/imperasus/sylqon/commit/ee047d1fc5696e76aad27411271834be23fdfb1c))
* **web:** gold-difference timeline chart on match detail ([66b8763](https://github.com/imperasus/sylqon/commit/66b87638bd4ca0b8c6ac7b5a97903fe4e6fcfcb7))
* **web:** Graphite Volt public site — branded home + summoner profile ([7cf525c](https://github.com/imperasus/sylqon/commit/7cf525c9999b8c3fdf1ab23f2fdf668f16d7b083))
* **web:** match history + match detail pages ([0625456](https://github.com/imperasus/sylqon/commit/062545685070552eb590adbd9d8a04b15a4f3fe0))
* **web:** region-aware summoner search ([0fcc263](https://github.com/imperasus/sylqon/commit/0fcc2634ad4ff96630c0a30bb6ede50f47e6745a))
* **web:** resolve leaderboard names to Riot IDs ([973ddf4](https://github.com/imperasus/sylqon/commit/973ddf453c55e74429df9115fe5b3af01f335e23))


### Performance

* **web:** SQL aggregates replace full-raw scans on public pages ([cf47d6a](https://github.com/imperasus/sylqon/commit/cf47d6a5c12860ae65226f37f455f4e14788381b))

## [1.23.0](https://github.com/imperasus/sylqon/compare/v1.22.0...v1.23.0) (2026-07-09)


### Features

* **brand:** extend Graphite Volt to remaining surfaces ([18dc990](https://github.com/imperasus/sylqon/commit/18dc990e3178c9ec4579dbbc65c2b6d3568fa833))

## [1.22.0](https://github.com/imperasus/sylqon/compare/v1.21.0...v1.22.0) (2026-07-09)


### Features

* **landing:** refresh product screenshots to Graphite Volt (v1.20.0) ([af2cced](https://github.com/imperasus/sylqon/commit/af2ccedfcdedbfef50e4e333d7f88b41840f32b5))

## [1.21.0](https://github.com/imperasus/sylqon/compare/v1.20.0...v1.21.0) (2026-07-08)


### Features

* **landing:** Graphite Volt repaint + Signal-S brand + favicon ([41b1973](https://github.com/imperasus/sylqon/commit/41b1973174ef3f59d7b8716758901aa3193b8ed2))

## [1.20.0](https://github.com/imperasus/sylqon/compare/v1.19.0...v1.20.0) (2026-07-08)


### Features

* **brand:** Signal-S mark - icon, favicon, splash pages, window bg ([b1c8519](https://github.com/imperasus/sylqon/commit/b1c8519c3ed41d2611fa2bdc20d1a13636e76f8b))
* **ui:** Graphite Volt foundation - tokens, typography, radii ([87ac342](https://github.com/imperasus/sylqon/commit/87ac342002e39b6583cac214a747525503d31489))
* **ui:** flat surface language - hairline panels, no glow/glass ([fb06cc8](https://github.com/imperasus/sylqon/commit/fb06cc898f3560bdbc479fbef872c3a0e42e4ec9))
* **ui:** restyle shared primitives for the flat analytics language ([0835705](https://github.com/imperasus/sylqon/commit/0835705f231d920ad84aea11d83fa9e9b4ef8af1))
* **ui:** left icon rail + slim status strip app frame ([9a32dcc](https://github.com/imperasus/sylqon/commit/9a32dcc825b69584f1ca369a328afa46a49650fc))
* **ui:** Home analytics layout - hero KPI strip + merged right column ([91c9d9e](https://github.com/imperasus/sylqon/commit/91c9d9e69ddce56d5fb3882ec7d37128443efd69))
* **ui:** Draft board as one surface with hairline-divided columns ([b1672d9](https://github.com/imperasus/sylqon/commit/b1672d9c854d27ca5d3855ea8e9427ce442b2cd7))
* **ui:** Postlock gauge + callout banner, modals on the elevated surface ([6282f79](https://github.com/imperasus/sylqon/commit/6282f79780d958b7345ac1a00ad53ffb23a4032f))
* **ui:** LiveBoard palette sweep for Graphite Volt ([9dc8e38](https://github.com/imperasus/sylqon/commit/9dc8e387b0d71b167197f303bd18c410a6314d02))
* **ui:** dense team tables for Players and LiveBoard ([50d95b2](https://github.com/imperasus/sylqon/commit/50d95b2951c7c2020b7d7db39a23b2e3e67f8720))
* **ui:** overlay pass - no blur, BrandMark header, arcane Baron ([6635b4d](https://github.com/imperasus/sylqon/commit/6635b4d20a4538ec6a07dfc2bd9d041709c63e14))

## [1.19.0](https://github.com/imperasus/sylqon/compare/v1.18.0...v1.19.0) (2026-07-07)


### Features

* hosted meta service is the default data source ([959f7ec](https://github.com/imperasus/sylqon/commit/959f7ec2edb71706db7af223d742feb6e26db0aa))

## [1.18.0](https://github.com/imperasus/sylqon/compare/v1.17.2...v1.18.0) (2026-07-07)


### Features

* **services:** production compose for the VPS (api + bot + db + redis) ([d7ad19e](https://github.com/imperasus/sylqon/commit/d7ad19ea3302a234438fb3a12c535da5cb090353))

### [1.17.2](https://github.com/imperasus/sylqon/compare/v1.17.1...v1.17.2) (2026-07-06)


### Bug Fixes

* **services:** pad thin situational pools to a 6-item minimum ([c98fb77](https://github.com/imperasus/sylqon/commit/c98fb77213cc2c1931681691c8b603c651547467))

### [1.17.1](https://github.com/imperasus/sylqon/compare/v1.17.0...v1.17.1) (2026-07-06)


### Bug Fixes

* **services:** run_stack.ps1 - plain dashes + UTF-8 BOM for PowerShell 5.1 ([95e5f28](https://github.com/imperasus/sylqon/commit/95e5f28a9712f603d956f1529d0b12bda787edfe))

## [1.17.0](https://github.com/imperasus/sylqon/compare/v1.16.0...v1.17.0) (2026-07-06)


### Features

* local pilot tooling - manual sync endpoint + one-command stack ([42faa5d](https://github.com/imperasus/sylqon/commit/42faa5de258b32d98cfcc7b42621010b18d6cc52))

## [1.16.0](https://github.com/imperasus/sylqon/compare/v1.15.0...v1.16.0) (2026-07-06)


### Features

* complete op.gg replaceability - bulk meta-sync from own data ([6f274f9](https://github.com/imperasus/sylqon/commit/6f274f93d87528422951521e5765993ce8cc7930))

## [1.15.0](https://github.com/imperasus/sylqon/compare/v1.14.0...v1.15.0) (2026-07-06)


### Features

* own-data meta builds - the op.gg replacement path (roadmap 3.3) ([ade2fb9](https://github.com/imperasus/sylqon/commit/ade2fb9b080e20c10dcee8cc7fd76d6160457f23))

## [1.14.0](https://github.com/imperasus/sylqon/compare/v1.13.0...v1.14.0) (2026-07-06)


### Features

* **services:** public web pages - the S3 website MVP ([83a7255](https://github.com/imperasus/sylqon/commit/83a72558fb765ebac57f9e8ef78e27529f45b420))

## [1.13.0](https://github.com/imperasus/sylqon/compare/v1.12.0...v1.13.0) (2026-07-06)


### Features

* **services:** /pool command, weekly auto-reports, pool calibration ([ce532bb](https://github.com/imperasus/sylqon/commit/ce532bb9789a789c008e26574fd6d7a6b388db6e))

## [1.12.0](https://github.com/imperasus/sylqon/compare/v1.11.1...v1.12.0) (2026-07-06)


### Features

* **services:** champion-pool coverage analysis (Phase 2 / S3 core) ([dbd1b11](https://github.com/imperasus/sylqon/commit/dbd1b116ec224e837099cd2d996e6e7eb2bd9bcf))

### [1.11.1](https://github.com/imperasus/sylqon/compare/v1.11.0...v1.11.1) (2026-07-05)

## [1.11.0](https://github.com/imperasus/sylqon/compare/v1.10.2...v1.11.0) (2026-07-05)


### Features

* **landing:** replace placeholder SVGs with real product screenshots ([2dffbc8](https://github.com/imperasus/sylqon/commit/2dffbc8ff1521e63aa95eda1e22fcb20d8cc4af4))

### [1.10.2](https://github.com/imperasus/sylqon/compare/v1.10.1...v1.10.2) (2026-07-05)


### Bug Fixes

* **landing:** real download CTA + repo GitHub link ([a23ccdf](https://github.com/imperasus/sylqon/commit/a23ccdf2d364e88987c4d33b76a7398667ad5420))

### [1.10.1](https://github.com/imperasus/sylqon/compare/v1.10.0...v1.10.1) (2026-07-05)

## [1.10.0](https://github.com/imperasus/sylqon/compare/v1.9.1...v1.10.0) (2026-07-05)


### Features

* **services:** add co-player seed crawl to widen the data pool ([4401bb0](https://github.com/imperasus/sylqon/commit/4401bb09c8c3823c1c68769bfbff55d052209a54))
* **services:** add Discord bot with slash commands and feedback loop ([709542f](https://github.com/imperasus/sylqon/commit/709542f9dd9237b5437ad4a31d8203236c46985f))
* **services:** add ingestion-svc — Match-V5 ingestion + post-game advice ([019feae](https://github.com/imperasus/sylqon/commit/019feae4862465cc1a1d1e325cac000c942979a0))
* **services:** rank-banded benchmarks from own League-V4 data ([7bd2966](https://github.com/imperasus/sylqon/commit/7bd2966235aa72734ad0c905d26a791506cf2954))

### [1.9.1](https://github.com/imperasus/sylqon/compare/v1.9.0...v1.9.1) (2026-07-01)

## [1.9.0](https://github.com/imperasus/sylqon/compare/v1.8.0...v1.9.0) (2026-07-01)


### Features

* **draft:** live countdown timer, hover state, and real pick order ([7110a6e](https://github.com/imperasus/sylqon/commit/7110a6e85fafa25cd4b5ca2c1d4df0f9495f33bb))
* **landing:** add marketing landing page ([0f336d1](https://github.com/imperasus/sylqon/commit/0f336d1a8bd0381e9bca16d99b9c3e2311c7b44f))
* **ui:** global view navigation + dashboard Settings panel ([579255e](https://github.com/imperasus/sylqon/commit/579255e459ff075fd7d4e1a65a513ec02c7e9129))


### Bug Fixes

* **cache:** avoid NameError in opgg_to_build under-resolution warning ([0c931d3](https://github.com/imperasus/sylqon/commit/0c931d3a58dbdc4d865de1329e9e4285e6897f73))


### Refactoring

* extract AppState + serializers into sylqon/state.py ([bcb5071](https://github.com/imperasus/sylqon/commit/bcb50715fb3a2c9c7060352539dd4d4f762c6a2f))

## [1.8.0](https://github.com/imperasus/sylqon/compare/v1.7.0...v1.8.0) (2026-06-29)


### Features

* **overlay:** voice coaching for missions and objectives ([a0f0376](https://github.com/imperasus/sylqon/commit/a0f0376aea92879116c0a137232e9cb346046816))


### Bug Fixes

* **deps:** add web-server stack to requirements.txt ([537a0f3](https://github.com/imperasus/sylqon/commit/537a0f3baeef7a14daae1af8d9ed3c997b92bd39))

## [1.7.0](https://github.com/imperasus/sylqon/compare/v1.6.0...v1.7.0) (2026-06-29)


### Features

* **scout:** stream the live board in two phases + cache match fetches ([9c616f1](https://github.com/imperasus/sylqon/commit/9c616f1920748e9ebb53718cb25075da53e69caf))

## [1.6.0](https://github.com/imperasus/sylqon/compare/v1.5.2...v1.6.0) (2026-06-29)


### Features

* **draft:** full-universe build cache + roster-wide counter/synergy picks ([c994ff1](https://github.com/imperasus/sylqon/commit/c994ff17f8775a5ec053969a766609060a2a1a67))

### [1.5.2](https://github.com/imperasus/sylqon/compare/v1.5.1...v1.5.2) (2026-06-27)


### Features

* meta-aware item/rune/shard enforcement with champion damage type filtering ([ffdbde7](https://github.com/imperasus/sylqon/commit/ffdbde7782bbc0a826eb01d7875acb9b2cb13962))

### [1.5.1](https://github.com/imperasus/sylqon/compare/v1.5.0...v1.5.1) (2026-06-26)


### Features

* **draft:** elevate the ban suggestion during the ban turn ([37c9386](https://github.com/imperasus/sylqon/commit/37c93865b6a422e3349acb453577977086e4ac04)), closes [#1](https://github.com/imperasus/sylqon/issues/1)

## [1.5.0](https://github.com/imperasus/sylqon/compare/v1.4.3...v1.5.0) (2026-06-26)


### Features

* **coach:** add account-level AI macro coach ([03cd553](https://github.com/imperasus/sylqon/commit/03cd553dbf424ab46f77fa5936d8648441bb049e))
* **draft:** add estimated draft win% scorecard ([468ecd3](https://github.com/imperasus/sylqon/commit/468ecd30de8def00bad2e6c7e670f5a2da55e032))
* **overlay:** add dragon-soul and power-spike tactical signals ([c409d37](https://github.com/imperasus/sylqon/commit/c409d371a05be1b3decf41fc0bf7646e07d5591e))
* **overlay:** auto show/hide the overlay on game state ([80f2141](https://github.com/imperasus/sylqon/commit/80f21413dbfa0ec3f74152878d07bf2cf9d357d5))

### [1.4.3](https://github.com/imperasus/sylqon/compare/v1.4.2...v1.4.3) (2026-06-24)


### Bug Fixes

* **live:** dedupe live-scout roster by name when puuids differ ([be5209a](https://github.com/imperasus/sylqon/commit/be5209a))

### [1.4.2](https://github.com/imperasus/sylqon/compare/v1.4.1...v1.4.2) (2026-06-24)


### Bug Fixes

* **ui:** align Patch Meta 2-up header and portal the match-review modal ([efcc6a3](https://github.com/imperasus/sylqon/commit/efcc6a369745df23a051e84ed1c4bf13eedb6b6e))

### [1.4.1](https://github.com/imperasus/sylqon/compare/v1.4.0...v1.4.1) (2026-06-23)


### Bug Fixes

* **spectator:** retry logic ([27a3eee](https://github.com/imperasus/sylqon/commit/27a3eee7009a92dcd8142fbfc882b389fcd18736))

## [1.4.0](https://github.com/imperasus/sylqon/compare/v1.3.6...v1.4.0) (2026-06-23)


### Features

* **rag:** semantic RAG over Data Dragon for builds, runes, kits and enemy scouting ([8feaf5c](https://github.com/imperasus/sylqon/commit/8feaf5c789e9bbd9c365d0faf1da0521e308e11a))

### [1.3.5](https://github.com/imperasus/sylqon/compare/v1.3.4...v1.3.5) (2026-06-22)


### Bug Fixes

* **live:** render the live board mid-game without a captured lobby ([dec8855](https://github.com/imperasus/sylqon/commit/dec8855b591b80bd82e7eb35c93e4e3ac48d3d63))
* **riot:** use RIOT_SELF_PUUID when the LCU returns a non-PUUID id ([b4d5ad7](https://github.com/imperasus/sylqon/commit/b4d5ad733ed8e24c4303134f0a000be39d308112))


### Performance

* **riot:** lower default RIOT_MATCH_COUNT to 20 ([4d1b3cc](https://github.com/imperasus/sylqon/commit/4d1b3cc98f097882668a959e9b44866aa22aea52))

### [1.3.4](https://github.com/imperasus/sylqon/compare/v1.3.3...v1.3.4) (2026-06-21)


### Features

* **live:** show the local player's own rank from the LCU ([a3f0076](https://github.com/imperasus/sylqon/commit/a3f0076f429ca03d075669818b02d9ccefe7949f))


### Bug Fixes

* **live:** correct spell/rune display on non-English clients + CS/min readout ([91be5b6](https://github.com/imperasus/sylqon/commit/91be5b61949d9bb90bf45e8d4b437da5898afa27))

### [1.3.3](https://github.com/imperasus/sylqon/compare/v1.3.2...v1.3.3) (2026-06-21)


### Bug Fixes

* **live:** label premade parties up to a 5-stack ([4e0d116](https://github.com/imperasus/sylqon/commit/4e0d116e2dcbcc869860d9031d7461cf5d105049))

### [1.3.2](https://github.com/imperasus/sylqon/compare/v1.3.1...v1.3.2) (2026-06-21)


### Bug Fixes

* show LiveBoard as soon as phase is InProgress, not just when live.active ([ce3eb8d](https://github.com/imperasus/sylqon/commit/ce3eb8d89358aa227eeed21318c2b7f4c8fa6955))

### [1.3.1](https://github.com/imperasus/sylqon/compare/v1.3.0...v1.3.1) (2026-06-21)

### [1.0.1](https://github.com/imperasus/sylqon/compare/v1.0.0...v1.0.1) (2026-06-16)


### Features

* add automated Windows release pipeline and auto-update ([36fba14](https://github.com/imperasus/sylqon/commit/36fba14d1577db208583f85dcc76b98ccded1cd7))
