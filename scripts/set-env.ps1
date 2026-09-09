<#
.SYNOPSIS
    Fills in the .env file from the terminal, one value at a time.

.DESCRIPTION
    Windows ships no terminal editor and .env has no file extension, so this
    asks for every setting and rewrites only the matching lines (comments and
    values you do not touch stay exactly as they are).

    Press Enter to keep the current value. A value that fails validation is
    asked again instead of aborting the whole run.

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

function Ask {
    param(
        [string]$Key,
        [string]$Label,
        [string]$Supplied,
        [scriptblock]$Validate,
        [string]$Hint,
        [switch]$Secret
    )
    $current = Get-EnvValue $Key

    if ($Supplied) {
        $value = $Supplied.Trim()
        if ($Validate -and -not (& $Validate $value)) {
            throw "$Key noto'g'ri. $Hint  (kiritilgan: $value)"
        }
        return $value
    }
    if ($NonInteractive) { return $current }

    if ($Secret) { $shown = Mask $current } else { $shown = $current }
    Write-Host ''
    Write-Host $Label -ForegroundColor Cyan
    Write-Host "  hozirgi qiymat: $shown" -ForegroundColor DarkGray

    while ($true) {
        $answer = Read-Host '  yangi qiymat (Enter = o''zgartirmaslik)'
        if ([string]::IsNullOrWhiteSpace($answer)) { return $current }
        $answer = $answer.Trim()
        if (-not $Validate -or (& $Validate $answer)) { return $answer }
        # Wrong value: explain and ask again, so nothing entered so far is lost.
        Write-Host "  ! $Hint" -ForegroundColor Yellow
    }
}

$isDigits   = { param($v) $v -match '^\d+$' }
$isChatId   = { param($v) $v -match '^-?\d+$' }
$isAdminIds = { param($v) $v -match '^\d+([,\s]+\d+)*$' }
$isToken    = { param($v) $v -match '^\d+:[A-Za-z0-9_\-]+$' }
$isHash     = { param($v) $v -match '^[A-Za-z0-9]{16,}$' }

Write-Host 'TG-Guard .env sozlash' -ForegroundColor Green
Write-Host "Fayl: $Path"
Write-Host 'Enter bosilsa qiymat o''zgarmaydi. Xato qiymat qayta so''raladi.' -ForegroundColor DarkGray

$values = [ordered]@{}

$values.BOT_TOKEN = Ask -Key 'BOT_TOKEN' -Supplied $BotToken -Secret `
    -Label '1) Bot tokeni  (@BotFather -> /newbot)' `
    -Validate $isToken `
    -Hint 'Token "123456789:AAH..." ko''rinishida bo''ladi (raqam, ikki nuqta, harflar).'

$values.TG_API_ID = Ask -Key 'TG_API_ID' -Supplied $ApiId `
    -Label '2) api_id  (my.telegram.org -> API development tools -> "App api_id")' `
    -Validate $isDigits `
    -Hint 'Faqat raqam, 6-8 xona (masalan 2468013). "149.154.167.50:443" - bu server manzili, api_id EMAS.'

$values.TG_API_HASH = Ask -Key 'TG_API_HASH' -Supplied $ApiHash -Secret `
    -Label '3) api_hash  (o''sha sahifada "App api_hash")' `
    -Validate $isHash `
    -Hint '32 ta harf-raqamdan iborat uzun satr (masalan a1b2c3d4e5f6...).'

$values.ADMIN_IDS = Ask -Key 'ADMIN_IDS' -Supplied $AdminIds `
    -Label '4) Sizning user id  (@userinfobot). Bir nechta bo''lsa: 111,222' `
    -Validate $isAdminIds `
    -Hint 'Faqat raqam(lar), vergul bilan ajratilgan. Manfiy emas - bu sizning shaxsiy id ingiz.'

$values.CHANNEL_ID = Ask -Key 'CHANNEL_ID' -Supplied $ChannelId `
    -Label '5) Himoyalanadigan kanal id  (-100... ; `tgguard chats` ko''rsatadi)' `
    -Validate $isChatId `
    -Hint 'Butun son, odatda -100 bilan boshlanadi (masalan -1001122334455).'

$values.DISCUSSION_GROUP_ID = Ask -Key 'DISCUSSION_GROUP_ID' -Supplied $DiscussionGroupId `
    -Label '6) Muhokama guruhi id  (-100...)' `
    -Validate $isChatId `
    -Hint 'Butun son, odatda -100 bilan boshlanadi.'

$values.REVIEW_CHANNEL_ID = Ask -Key 'REVIEW_CHANNEL_ID' -Supplied $ReviewChannelId `
    -Label '7) Yopiq review kanal id  (-100...)' `
    -Validate $isChatId `
    -Hint 'Butun son, odatda -100 bilan boshlanadi.'

foreach ($key in 'CHANNEL_ID', 'DISCUSSION_GROUP_ID', 'REVIEW_CHANNEL_ID') {
    $value = $values[$key]
    if ($value -and $value -ne '0' -and -not ($value -like '-100*')) {
        Write-Host "  ! $key odatda -100 bilan boshlanadi. Kiritilgan: $value" -ForegroundColor Yellow
    }
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
Write-Host '  .\.venv\Scripts\tgguard.exe chats     # kanal id larini ko''rish'
Write-Host '  .\.venv\Scripts\tgguard.exe whoami    # ulanishni tekshirish'
