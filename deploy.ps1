#requires -Version 7.0
<#
.SYNOPSIS
Push the committed develop branch, test/build on the server, then deploy.
.DESCRIPTION
-CheckOnly tests a committed candidate on the server without pushing or deploying.
Use -Revision to select its full SHA, or omit it to use the current HEAD.
After the v2 cutover is active, publishing updates services on the active v2
database and file volume. Routine v2 releases require the same database schema.
.EXAMPLE
./deploy.ps1
.EXAMPLE
./deploy.ps1 -CheckOnly
.EXAMPLE
./deploy.ps1 -CheckOnly -Revision <full-commit-sha>
.EXAMPLE
./deploy.ps1 -AllowMigration
.EXAMPLE
./deploy.ps1 -V2SchemaMigration
#>
[CmdletBinding()]
param(
    [ValidatePattern('^[a-zA-Z0-9_.@-]+$')][string]$SshHost = '132.232.176.201',
    [ValidatePattern('^/[a-zA-Z0-9_/-]+$')][string]$ServerRoot = '/srv/zeichen',
    [switch]$CheckOnly,
    [ValidatePattern('^[0-9a-f]{40}$')][string]$Revision,
    [switch]$AllowMigration,
    [switch]$V2SchemaMigration
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
function Invoke-Git {
    & git @args
    if ($LASTEXITCODE -ne 0) { throw "git failed ($LASTEXITCODE)" }
}

function Invoke-RemoteScript([string]$Script) {
    $Script.Replace("`r", '') | & ssh -o BatchMode=yes -o ClearAllForwardings=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=4 $SshHost 'tr -d ''\r'' | bash -s'
    if ($LASTEXITCODE -ne 0) { throw "Remote release command failed ($LASTEXITCODE). See its output for the evidence path." }
}

function Test-CandidateCommit([string]$Commit, [string]$Bundle) {
    $kind = (Invoke-Git cat-file -t $Commit).Trim()
    if ($kind -ne 'commit') { throw 'Revision must name a Git commit.' }
    $suffix = [guid]::NewGuid().ToString('N')
    $ref = "refs/zeichen-checks/$suffix"
    $remote = "/tmp/zeichen-check-$suffix"
    Invoke-Git update-ref $ref $Commit
    try {
        Invoke-Git bundle create $Bundle $ref
    } finally {
        Invoke-Git update-ref -d $ref $Commit
    }
    # Keep the runner and the commit under test separate. Execute candidate tests
    # within disposable containers, not as Python or shell on the build host.
    Invoke-RemoteScript "set -eu; mkdir -m 700 '$remote'"
    try {
        & scp -q -o BatchMode=yes -o ClearAllForwardings=yes $Bundle (Join-Path $PSScriptRoot 'deploy/remote_release.py') "${SshHost}:$remote/"
        if ($LASTEXITCODE -ne 0) { throw 'Could not transfer the candidate bundle and runner.' }
        Invoke-RemoteScript @"
set -euo pipefail
umask 077
git init --bare -q '$remote/repository'
git --git-dir='$remote/repository' fetch -q --no-tags '$remote/release.bundle' '$ref'
test "`$(git --git-dir='$remote/repository' rev-parse FETCH_HEAD)" = '$Commit'
mkdir '$remote/source'
git --git-dir='$remote/repository' archive '$Commit' | tar -x -C '$remote/source'
python3 -u '$remote/remote_release.py' --root "`$HOME/.zeichen-checks" --commit '$Commit' --check-only --candidate-source '$remote/source'
"@
    } finally {
        try {
            Invoke-RemoteScript "rm -rf -- '$remote'"
        } catch {
            Write-Warning "Could not clean up candidate transfer directory $remote. $($_.Exception.Message)"
        }
    }
}

if ($V2SchemaMigration -and ($AllowMigration -or $CheckOnly)) { throw 'Use -V2SchemaMigration after a successful separate -CheckOnly run.' }
if ($Revision -and -not $CheckOnly) { throw '-Revision is only supported with -CheckOnly.' }
if ($CheckOnly -and $AllowMigration) { throw '-AllowMigration applies to publishing only; candidate checks always use an isolated database.' }

Push-Location $PSScriptRoot
$tempDirectory = Join-Path ([System.IO.Path]::GetTempPath()) "zeichen-release-$([guid]::NewGuid().ToString('N'))"
$bundle = Join-Path $tempDirectory 'release.bundle'
try {
    New-Item -ItemType Directory -Path $tempDirectory | Out-Null
    if ($CheckOnly) {
        if (-not $Revision) { $Revision = (Invoke-Git rev-parse HEAD).Trim() }
        Test-CandidateCommit $Revision.ToLowerInvariant() $bundle
        return
    }
    if (-not $V2SchemaMigration -and (Invoke-Git branch --show-current) -ne 'develop') { throw 'Switch to develop before publishing.' }
    if (Invoke-Git status --porcelain) { throw 'Commit or stash changes before publishing; only committed files are deployed.' }
    $revision = (Invoke-Git rev-parse HEAD).Trim()
    if ($revision -notmatch '^[0-9a-f]{40}$') { throw 'Invalid commit.' }
    Invoke-Git push origin HEAD:refs/heads/develop
    # Transfer the exact pushed commit over SSH as well: the server need not
    # reach GitHub or store GitHub credentials to deploy it.
    $upload = "/tmp/zeichen-$revision-$([guid]::NewGuid().ToString('N')).bundle"
    Invoke-Git bundle create $bundle HEAD
    & scp -q -o BatchMode=yes -o ClearAllForwardings=yes $bundle "${SshHost}:$upload"
    if ($LASTEXITCODE -ne 0) { throw 'Could not transfer the release bundle.' }
    $flags = ''
    if ($AllowMigration) { $flags += ' --allow-migration' }
    # The bootstrap touches Git objects only. Production source is never pulled
    # before verification; the release runner serializes all activation work.
    $runner = 'remote_release.py'
    if ($V2SchemaMigration) { $runner = 'migrate_v2_release.py' }
    $remoteScript = @"
set -euo pipefail
cd '$ServerRoot'
git fetch '$upload' HEAD:refs/remotes/origin/develop
git merge-base --is-ancestor '$revision' origin/develop
staging=`$(mktemp -d /tmp/zeichen-release.XXXXXXXX)
trap 'rm -rf -- "`$staging"; rm -f -- "$upload"' EXIT
git archive '$revision' | tar -x -C "`$staging"
umask 077
mkdir -p '$ServerRoot/.release/logs'
python3 -u "`$staging/deploy/$runner" --root '$ServerRoot' --commit '$revision'$flags 2>&1 | tee '$ServerRoot/.release/logs/'`$(date -u +%Y%m%dT%H%M%SZ)'-$revision.log'
"@
    Invoke-RemoteScript $remoteScript
} finally {
    if (Test-Path -LiteralPath $bundle) { Remove-Item -LiteralPath $bundle }
    if (Test-Path -LiteralPath $tempDirectory) { Remove-Item -LiteralPath $tempDirectory }
    Pop-Location
}
