# Changelog

All notable changes to this project will be documented in this file. See [standard-version](https://github.com/conventional-changelog/standard-version) for commit guidelines.

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
