<#
.SYNOPSIS
    Cut a new Sylqon Desktop release: bump version, update CHANGELOG, tag, and push.

.DESCRIPTION
    Thin wrapper around `standard-version` (configured in .versionrc.json).
    standard-version bumps the version in package.json, regenerates CHANGELOG.md
    from Conventional Commit messages, creates a "chore(release): vX.Y.Z" commit,
    and creates the matching vX.Y.Z git tag. This script then pushes the commit
    and tag, which triggers the GitHub Actions release workflow.

.PARAMETER Bump
    Release type: patch (default), minor, or major.

.EXAMPLE
    ./release.ps1            # patch bump (1.0.0 -> 1.0.1)
    ./release.ps1 minor      # minor bump (1.0.0 -> 1.1.0)
    ./release.ps1 major      # major bump (1.0.0 -> 2.0.0)
#>
[CmdletBinding()]
param(
    [ValidateSet('patch', 'minor', 'major')]
    [string]$Bump = 'patch'
)

$ErrorActionPreference = 'Stop'

# Always operate from the desktop package root (parent of this scripts/ dir),
# because standard-version bumps the package.json in its working directory.
$desktop = Split-Path -Parent $PSScriptRoot
Push-Location $desktop
try {
    # Refuse to release with a dirty tree — standard-version would fold stray
    # changes into the release commit.
    $dirty = git status --porcelain
    if ($dirty) {
        throw "Working tree is not clean. Commit or stash your changes before releasing.`n$dirty"
    }

    Write-Host "Running standard-version ($Bump bump)..." -ForegroundColor Cyan
    npm run "release:$Bump"
    if ($LASTEXITCODE -ne 0) {
        throw "standard-version failed (exit $LASTEXITCODE)."
    }

    # standard-version has now created the release commit + vX.Y.Z tag locally.
    $version = (Get-Content package.json -Raw | ConvertFrom-Json).version

    Write-Host "Pushing commit and tag v$version..." -ForegroundColor Cyan
    git push
    if ($LASTEXITCODE -ne 0) { throw "git push failed (exit $LASTEXITCODE)." }
    git push --tags
    if ($LASTEXITCODE -ne 0) { throw "git push --tags failed (exit $LASTEXITCODE)." }

    Write-Host "Release v$version pushed - GitHub Actions will build and publish the installer." -ForegroundColor Green
}
finally {
    Pop-Location
}
