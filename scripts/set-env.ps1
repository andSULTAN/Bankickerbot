<#
.SYNOPSIS
    Fills in the .env file from the terminal, one value at a time.

.DESCRIPTION
    Windows has no terminal editor out of the box, so this asks for every
    setting and rewrites only the matching lines of .env (comments and the
    values you do not touch stay exactly as they are).

    Press Enter to keep the current value.

.EXAMPLE
    .\scripts\set-env.ps1

.EXAMPLE
    .\scripts\set-env.ps1 -AdminIds 123456789 -ChannelId -1001122334455
#>
[CmdletBinding()]
param(
    [string]$Path,
    [string]$BotToken,
    [string]$ApiId,
    [string]$ApiHash,
    [string]$AdminIds,
    [string]$ChannelId,
    [string]$DiscussionGroupId,
    [string]$ReviewChannelId,
    [switch]$NonInteractive
)

$ErrorActionPreference = 'Stop'

if (-not $Path) {
    $Path = Join-Path (Split-Path -Parent $PSScriptRoot) '.env'
}
if (-not (Test-Path $Path)) {
    $sample = Join-Path (Split-Path -Parent $PSScriptRoot) '.env.example'
    if (Test-Path $sample) {
        Copy-Item $sample $Path
        Write-Host ".env yaratildi ($Path)" -ForegroundColor Yellow
    } else {
        throw ".env topilmadi: $Path"
    }
}

$lines = @(Get-Content -LiteralPath $Path -Encoding UTF8)

function Get-EnvValue([string]$Key) {
    foreach ($line in $lines) {
        if ($line -match "^\s*$Key\s*=(.*)$") { return $Matches[1].Trim() }
    }
    return ''
}

function Set-EnvValue([string]$Key, [string]$Value) {
    $found = $false
    $result = foreach ($line in $lines) {
        if ($line -match "^\s*$Key\s*=") {
            $found = $true
            "$Key=$Value"
        } else {
            $line
        }
    }
    if (-not $found) { $result = @($result) + "$Key=$Value" }
    $script:lines = @($result)
}

function Mask([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return '(bo''sh)' }
    if ($Value.Length -le 8) { return '***' }
    return $Value.Substring(0, 4) + '...' + $Value.Substring($Value.Length - 4)
}

function Ask([string]$Key, [string]$Label, [string]$Supplied, [switch]$Secret) {
    $current = Get-EnvValue $Key
    if ($Supplied) { return $Supplied.Trim() }
    if ($NonInteractive) { return $current }

    if ($Secret) { $shown = Mask $current } else { $shown = $current }
    Write-Host ''
    Write-Host $Label -ForegroundColor Cyan
    Write-Host "  hozirgi qiymat: $shown" -ForegroundColor DarkGray
    $answer = Read-Host '  yangi qiymat (Enter = o''zgartirmaslik)'
    if ([string]::IsNullOrWhiteSpace($answer)) { return $current }
    return $answer.Trim()
}

function Test-ChatId([string]$Key, [string]$Value) {
    if ($Value -and $Value -ne '0' -and -not ($Value -like '-100*')) {
        Write-Host "  ! $Key odatda -100 bilan boshlanadi. Kiritilgan: $Value" -ForegroundColor Yellow
    }
}

Write-Host 'TG-Guard .env sozlash' -ForegroundColor Green
Write-Host "Fayl: $Path"

$values = [ordered]@{
    BOT_TOKEN           = Ask 'BOT_TOKEN' '1) Bot tokeni  (@BotFather -> /newbot)' $BotToken -Secret
    TG_API_ID           = Ask 'TG_API_ID' '2) api_id  (my.telegram.org -> API development tools)' $ApiId
    TG_API_HASH         = Ask 'TG_API_HASH' '3) api_hash  (o''sha sahifada)' $ApiHash -Secret
    ADMIN_IDS           = Ask 'ADMIN_IDS' '4) Sizning user id  (@userinfobot). Bir nechta bo''lsa: 111,222' $AdminIds
    CHANNEL_ID          = Ask 'CHANNEL_ID' '5) Himoyalanadigan kanal id  (-100...)' $ChannelId
    DISCUSSION_GROUP_ID = Ask 'DISCUSSION_GROUP_ID' '6) Muhokama guruhi id  (-100...)' $DiscussionGroupId
    REVIEW_CHANNEL_ID   = Ask 'REVIEW_CHANNEL_ID' '7) Yopiq review kanal id  (-100...)' $ReviewChannelId
}

if ($values.TG_API_ID -and $values.TG_API_ID -notmatch '^\d+$') {
    throw "TG_API_ID faqat raqam bo'lishi kerak. Kiritilgan: $($values.TG_API_ID)"
}
foreach ($key in 'CHANNEL_ID', 'DISCUSSION_GROUP_ID', 'REVIEW_CHANNEL_ID') {
    Test-ChatId $key $values[$key]
}

foreach ($key in $values.Keys) {
    $value = $values[$key]
    if ([string]::IsNullOrWhiteSpace($value)) { $value = '' }
    Set-EnvValue $key $value
}

# UTF-8 without BOM: a BOM would end up inside the first key on some tools.
$encoding = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($Path, $lines, $encoding)

Write-Host ''
Write-Host 'Saqlandi:' -ForegroundColor Green
foreach ($key in $values.Keys) {
    if ($key -eq 'BOT_TOKEN' -or $key -eq 'TG_API_HASH') {
        Write-Host ("  {0,-20} {1}" -f $key, (Mask $values[$key]))
    } else {
        Write-Host ("  {0,-20} {1}" -f $key, $values[$key])
    }
}
Write-Host ''
Write-Host 'Keyingi qadam:' -ForegroundColor Cyan
Write-Host '  .\.venv\Scripts\tgguard.exe whoami'
