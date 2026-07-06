# Changelog

All notable changes to this project will be documented in this file. See [standard-version](https://github.com/conventional-changelog/standard-version) for commit guidelines.

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
