# Releasing Sylqon Desktop

How new versions are built, published, and delivered to users.

## TL;DR — cut a release

From `sylqon-desktop/`:

```powershell
./scripts/release.ps1            # patch bump (1.0.0 -> 1.0.1)
./scripts/release.ps1 minor      # minor bump (1.0.0 -> 1.1.0)
./scripts/release.ps1 major      # major bump (1.0.0 -> 2.0.0)
```

That single command bumps the version, updates `CHANGELOG.md`, commits, tags
`vX.Y.Z`, and pushes. GitHub Actions takes it from there.

## What the release script does

`scripts/release.ps1` is a thin wrapper around [`standard-version`](https://github.com/conventional-changelog/standard-version)
(configured in [`.versionrc.json`](.versionrc.json)). It:

1. Refuses to run on a dirty working tree.
2. Runs `npm run release:<patch|minor|major>`, which:
   - bumps `version` in `package.json`,
   - regenerates `CHANGELOG.md` from your Conventional Commit messages,
   - creates a `chore(release): vX.Y.Z` commit,
   - creates the matching `vX.Y.Z` git tag.
3. Runs `git push` and `git push --tags`.

### Doing it by hand instead

```powershell
# 1. Bump the version in package.json (e.g. 1.0.0 -> 1.1.0)
# 2. Commit
git commit -am "chore: bump version to 1.1.0"
# 3. Tag
git tag v1.1.0
# 4. Push
git push && git push --tags
```

## What GitHub Actions does automatically

Pushing a `vX.Y.Z` tag triggers [`.github/workflows/release.yml`](../.github/workflows/release.yml),
which on a `windows-latest` runner:

1. **Validates the tag** with the `semver` package and checks it matches
   `package.json` — a malformed or mismatched tag fails fast.
2. **Sets up Node 20 and Python 3.11** (the build needs both — see below).
3. **Installs dependencies** — `npm ci` for the desktop app and the `ui/` React
   app, plus the Python build requirements.
4. **Builds the backend + UI** (`npm run build:backend`) — bundles the Python
   backend into a standalone exe with PyInstaller and builds the React UI.
5. **Compiles the Electron main process** (`npm run build:main`).
6. **Packages and publishes** (`npm run dist` → `electron-builder --publish always`).
   electron-builder creates the GitHub Release and uploads:
   - `Sylqon-Setup-<version>.exe` — the NSIS installer
   - `latest.yml` — update metadata consumed by electron-updater
   - blockmap files — for delta downloads

The release then appears at:
`https://github.com/imperasus/sylqon/releases`

> Why both Node and Python? The packaged app embeds the Python/FastAPI backend
> as a standalone executable. The CI build runs PyInstaller (Python) and the
> Electron/TypeScript build (Node) in the same job.

Build guards keep this within GitHub's free tier: a 20-minute job timeout, npm +
pip caching, and a `concurrency` group so only one release build runs per tag.

## How auto-updates reach end users

Sylqon checks for updates automatically on startup. When a new version is
available, a banner appears in the app — click **Download**, then **Restart** to
apply. Updates are never forced and never interrupt you with OS dialog boxes.

Under the hood, [`electron-updater`](https://www.electron.build/auto-update)
reads `latest.yml` from the latest GitHub Release on launch, downloads the new
installer in the background, and applies it on the next restart.

## Code signing (optional, not yet enabled)

Builds are currently **unsigned**. They install and auto-update fine, but
Windows SmartScreen shows a "Windows protected your PC" warning on first run
until your publisher reputation builds up. Signing removes that warning. The
scaffolding (commented) lives in the `win:` block of
[`electron-builder.yml`](electron-builder.yml).

### What you'll need later to enable it

1. **Get a code-signing certificate** — a standard OV certificate (`.pfx`/`.p12`
   file + password) from a CA (DigiCert, Sectigo, SSL.com, …), or an EV
   certificate on a hardware token. OV is simplest for CI.
2. **Provide the cert to the build via env vars** (no secrets in the repo):
   - `CSC_LINK` — path to the `.pfx`/`.p12`, or its base64 contents
   - `CSC_KEY_PASSWORD` — the certificate password

   electron-builder auto-detects these — no `electron-builder.yml` change needed
   for the env-var route. Locally:
   ```powershell
   $env:CSC_LINK = "C:\path\to\cert.pfx"
   $env:CSC_KEY_PASSWORD = "••••••"
   npm run dist
   ```
3. **In GitHub Actions**, add `CSC_LINK` (base64 of the `.pfx`) and
   `CSC_KEY_PASSWORD` as repository **secrets**, then expose them as `env` on the
   "Package installer and publish" step alongside `GH_TOKEN`:
   ```yaml
   env:
     GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
     CSC_LINK: ${{ secrets.CSC_LINK }}
     CSC_KEY_PASSWORD: ${{ secrets.CSC_KEY_PASSWORD }}
   ```
4. **Add a timestamp server** so signatures remain valid after the cert expires.
   Uncomment one line in `electron-builder.yml`, e.g.
   `rfc3161TimeStampServer: http://timestamp.digicert.com`.

> **EV certificates** usually live on a hardware token and require interactive
> signing, which generally can't run in CI — sign on a machine with the token,
> or use a CA that offers cloud-based EV signing.

Until any of this is set up, releasing works exactly as documented above; the
only difference is the SmartScreen prompt for end users.

## Manual downloads

Prefer to install or update by hand? Grab the latest
`Sylqon-Setup-<version>.exe` from:
`https://github.com/imperasus/sylqon/releases`

## Commit message guide

Sylqon uses [Conventional Commits](https://www.conventionalcommits.org/) so
version bumps and the changelog are automatic:

| Commit prefix | Example | Effect |
|---------------|---------|--------|
| `feat:` | `feat: add overlay click-through toggle` | minor bump (1.0.0 → 1.1.0) |
| `fix:` | `fix: overlay position not saved on exit` | patch bump (1.0.0 → 1.0.1) |
| `feat!:` / `BREAKING CHANGE:` | `feat!: redesign champion scoring API` | major bump (1.0.0 → 2.0.0) |
| `chore:` | `chore: bump dependencies` | no bump (hidden from changelog) |
| `docs:` | `docs: update readme` | no bump (hidden from changelog) |
| `perf:` `refactor:` | shown in changelog, no implicit bump | |
| `style:` `test:` | hidden from changelog | |

```powershell
git commit -m "feat: add overlay click-through toggle"
git commit -m "fix: overlay position not saved on exit"
git commit -m "feat!: redesign champion scoring API"
```

> `npm run release` (no suffix) auto-detects the bump type from these messages
> since the last tag. The `release.ps1` helper forces an explicit
> patch/minor/major bump instead, which is usually what you want for an app.
