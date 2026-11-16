#requires -Version 7.0
<#
.SYNOPSIS
Push the committed develop branch, test/build on the server, then deploy.
.EXAMPLE
./deploy.ps1
.EXAMPLE
./deploy.ps1 -CheckOnly
.EXAMPLE
./deploy.ps1 -AllowMigration
#>
[CmdletBinding()]
param(
    [ValidatePattern('^[a-zA-Z0-9_.@-]+$')][string]$SshHost = '132.232.176.201',
    [ValidatePattern('^/[a-zA-Z0-9_/-]+$')][string]$ServerRoot = '/srv/zeichen',
    [switch]$CheckOnly,
    [switch]$AllowMigration
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
function Invoke-Git {
    & git @args
    if ($LASTEXITCODE -ne 0) { throw "git failed ($LASTEXITCODE)" }
}
Push-Location $PSScriptRoot
try {
    if ((Invoke-Git branch --show-current) -ne 'develop') { throw 'Switch to develop before publishing.' }
    if (Invoke-Git status --porcelain) { throw 'Commit or stash changes before publishing; only committed files are deployed.' }
    $revision = (Invoke-Git rev-parse HEAD).Trim()
    if ($revision -notmatch '^[0-9a-f]{40}$') { throw 'Invalid commit.' }
    Invoke-Git push origin develop
    # Transfer the exact pushed commit over SSH as well: the server need not
    # reach GitHub or store GitHub credentials to deploy it.
    $bundle = Join-Path $PSScriptRoot ".git/release-$revision.bundle"
    $upload = "/tmp/zeichen-$revision-$([guid]::NewGuid().ToString('N')).bundle"
    Invoke-Git bundle create $bundle develop
    & scp -q -o BatchMode=yes -o ClearAllForwardings=yes $bundle "${SshHost}:$upload"
    if ($LASTEXITCODE -ne 0) { throw 'Could not transfer the release bundle.' }
    $flags = ''
    if ($CheckOnly) { $flags += ' --check-only' }
    if ($AllowMigration) { $flags += ' --allow-migration' }
    # The bootstrap touches Git objects only. Production source is never pulled
    # before verification; the release runner serializes all activation work.
    $remoteScript = @"
set -euo pipefail
cd '$ServerRoot'
git fetch '$upload' refs/heads/develop:refs/remotes/origin/develop
git merge-base --is-ancestor '$revision' origin/develop
staging=`$(mktemp -d /tmp/zeichen-release.XXXXXXXX)
trap 'rm -rf -- "`$staging"; rm -f -- "$upload"' EXIT
git archive '$revision' | tar -x -C "`$staging"
umask 077
mkdir -p '$ServerRoot/.release/logs'
python3 -u "`$staging/deploy/remote_release.py" --root '$ServerRoot' --commit '$revision'$flags 2>&1 | tee '$ServerRoot/.release/logs/'`$(date -u +%Y%m%dT%H%M%SZ)'-$revision.log'
"@
    $remoteScript.Replace("`r", '') | & ssh -o BatchMode=yes -o ClearAllForwardings=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=4 $SshHost 'tr -d ''\r'' | bash -s'
    if ($LASTEXITCODE -ne 0) { throw "Remote release failed ($LASTEXITCODE). See the remote release log; production is never updated after a failed check." }
} finally { Pop-Location }
