<#
    sync-edge-jwt.ps1 — Single source of truth for the portal JWT signing secret.

    The canonical secret lives in the SSM SecureString parameter (default
    /3i-portal/jwt-secret). Three consumers must all agree on it:
      1. the portal backend  (JWT_SECRET in 3i-portal-backend/.env)
      2. CloudFront function  validate-data-management-jwt
      3. CloudFront function  validate-position-risk-management-jwt

    Modes:
      -Mode Check   (default) Compare the canonical secret against the backend
                    .env and both LIVE CloudFront functions. Prints a SHA-256
                    fingerprint per source (never the secret itself) and exits 1
                    if anything diverges. This is the CI drift gate.
      -Mode Export  Download both LIVE functions to *.live.js next to the
                    templates so you can diff them before an Apply.
      -Mode Apply   Render each *.template.js with the canonical secret and
                    publish both functions (update-function + publish-function).

    Required IAM on the principal running this:
      Check/Export : ssm:GetParameter, kms:Decrypt, cloudfront:GetFunction
      Apply        : + cloudfront:DescribeFunction, UpdateFunction, PublishFunction
#>

[CmdletBinding()]
param(
    [ValidateSet('Check', 'Apply', 'Export')]
    [string] $Mode = 'Check',
    [string] $Param = '/3i-portal/jwt-secret',
    [string] $Region = 'us-east-1',
    [string] $EnvFile = 'C:\portal\3i-Portal\3i-portal-backend\.env'
)

$ErrorActionPreference = 'Stop'

function Invoke-Aws {
    param([Parameter(Mandatory)] [string[]] $Arguments)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & aws @Arguments 2>$null
        return [pscustomobject]@{ Code = $LASTEXITCODE; Output = (@($out) -join "`n") }
    }
    finally {
        $ErrorActionPreference = $prev
    }
}

$Functions = @(
    [pscustomobject]@{ Name = 'validate-data-management-jwt';         Template = Join-Path $PSScriptRoot 'validate-data-management-jwt.template.js' }
    [pscustomobject]@{ Name = 'validate-position-risk-management-jwt'; Template = Join-Path $PSScriptRoot 'validate-position-risk-management-jwt.template.js' }
)

function Get-SecretFromCode([string] $code) {
    if ([string]::IsNullOrEmpty($code)) { return $null }
    $m = [regex]::Match($code, 'var\s+JWT_SECRET\s*=\s*"([^"]*)"')
    if (-not $m.Success) { return $null }
    return $m.Groups[1].Value
}

function Get-Fingerprint($secret) {
    if ($null -eq $secret) { return '(missing)' }
    if ($secret -eq '__JWT_SECRET__') { return '(placeholder-unrendered)' }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($secret)
    $hash = [System.Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
    return (([System.BitConverter]::ToString($hash) -replace '-', '').Substring(0, 12).ToLower())
}

function Get-CanonicalSecret {
    $r = Invoke-Aws -Arguments @('ssm', 'get-parameter', '--name', $Param, '--with-decryption', '--region', $Region, '--query', 'Parameter.Value', '--output', 'text')
    if ($r.Code -ne 0 -or [string]::IsNullOrWhiteSpace($r.Output)) {
        throw "Could not read SSM parameter '$Param' in $Region. Confirm it exists and the role has ssm:GetParameter + kms:Decrypt."
    }
    return $r.Output.Trim()
}

function Get-BackendSecret {
    if (-not (Test-Path $EnvFile)) { return $null }
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match '^\s*JWT_SECRET\s*=\s*(.+?)\s*$') { return $Matches[1] }
    }
    return $null
}

function Get-LiveFunctionCode([string] $name) {
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        $r = Invoke-Aws -Arguments @('cloudfront', 'get-function', '--name', $name, '--stage', 'LIVE', '--region', $Region, $tmp)
        if ($r.Code -ne 0) { return $null }
        return (Get-Content $tmp -Raw)
    }
    finally {
        Remove-Item $tmp -ErrorAction SilentlyContinue
    }
}

function Invoke-Check {
    $canonical = Get-CanonicalSecret
    $canonicalFp = Get-Fingerprint $canonical
    Write-Host ("Canonical (SSM {0}) fingerprint: {1}" -f $Param, $canonicalFp)
    Write-Host ('{0,-46} {1,-26} {2}' -f 'Source', 'Fingerprint', 'Match')
    Write-Host ('-' * 84)

    $drift = $false

    $backendFp = Get-Fingerprint (Get-BackendSecret)
    $bMatch = ($backendFp -eq $canonicalFp)
    if (-not $bMatch) { $drift = $true }
    Write-Host ('{0,-46} {1,-26} {2}' -f "backend .env", $backendFp, ($(if ($bMatch) { 'OK' } else { 'DRIFT' })))

    foreach ($f in $Functions) {
        $liveFp = Get-Fingerprint (Get-SecretFromCode (Get-LiveFunctionCode $f.Name))
        $match = ($liveFp -eq $canonicalFp)
        if (-not $match) { $drift = $true }
        Write-Host ('{0,-46} {1,-26} {2}' -f "$($f.Name) (LIVE)", $liveFp, ($(if ($match) { 'OK' } else { 'DRIFT' })))
    }

    Write-Host ('-' * 84)
    if ($drift) {
        Write-Host 'RESULT: DRIFT DETECTED — the JWT secret is not aligned across all consumers.' -ForegroundColor Red
        Write-Host 'Fix: update SSM to the intended value, set backend .env to match, and run -Mode Apply.'
        exit 1
    }
    Write-Host 'RESULT: ALIGNED — backend and both edge functions match the canonical secret.' -ForegroundColor Green
    exit 0
}

function Invoke-Export {
    foreach ($f in $Functions) {
        $code = Get-LiveFunctionCode $f.Name
        if ($null -eq $code) { throw "Failed to download LIVE code for $($f.Name) (need cloudfront:GetFunction)." }
        $out = ($f.Template -replace '\.template\.js$', '.live.js')
        [System.IO.File]::WriteAllText($out, $code, (New-Object System.Text.UTF8Encoding($false)))
        Write-Host "Exported LIVE $($f.Name) -> $out"
    }
    Write-Host 'Diff each *.live.js against its *.template.js (ignoring the JWT_SECRET line) before Apply.'
}

function Invoke-Apply {
    $canonical = Get-CanonicalSecret
    Write-Host ("Applying canonical secret (fingerprint {0}) to both edge functions..." -f (Get-Fingerprint $canonical))
    foreach ($f in $Functions) {
        if (-not (Test-Path $f.Template)) { throw "Template not found: $($f.Template)" }
        $rendered = (Get-Content $f.Template -Raw).Replace('__JWT_SECRET__', $canonical)
        if ($rendered -match '__JWT_SECRET__') { throw "Placeholder not substituted in $($f.Name)" }

        $tmp = [System.IO.Path]::GetTempFileName()
        try {
            [System.IO.File]::WriteAllText($tmp, $rendered, (New-Object System.Text.UTF8Encoding($false)))

            $descR = Invoke-Aws -Arguments @('cloudfront', 'describe-function', '--name', $f.Name, '--stage', 'DEVELOPMENT', '--region', $Region)
            if ($descR.Code -ne 0) { throw "describe-function failed for $($f.Name) (need cloudfront:DescribeFunction)." }
            $desc = $descR.Output | ConvertFrom-Json
            $etag = $desc.ETag
            $comment = $desc.FunctionSummary.FunctionConfig.Comment
            $runtime = $desc.FunctionSummary.FunctionConfig.Runtime

            $upR = Invoke-Aws -Arguments @('cloudfront', 'update-function', '--name', $f.Name, '--if-match', $etag, '--function-code', "fileb://$tmp", '--function-config', "Comment=$comment,Runtime=$runtime", '--region', $Region)
            if ($upR.Code -ne 0) { throw "update-function failed for $($f.Name)" }

            $desc2R = Invoke-Aws -Arguments @('cloudfront', 'describe-function', '--name', $f.Name, '--stage', 'DEVELOPMENT', '--region', $Region)
            $desc2 = $desc2R.Output | ConvertFrom-Json
            $pubR = Invoke-Aws -Arguments @('cloudfront', 'publish-function', '--name', $f.Name, '--if-match', $desc2.ETag, '--region', $Region)
            if ($pubR.Code -ne 0) { throw "publish-function failed for $($f.Name)" }

            Write-Host "Published $($f.Name)"
        }
        finally {
            Remove-Item $tmp -ErrorAction SilentlyContinue
        }
    }
    Write-Host 'Done. Run -Mode Check to confirm alignment.'
}

try {
    switch ($Mode) {
        'Check' { Invoke-Check }
        'Export' { Invoke-Export }
        'Apply' { Invoke-Apply }
    }
}
catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
