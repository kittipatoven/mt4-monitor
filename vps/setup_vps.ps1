<#
  MT4 Trading Monitor V1 - Windows VPS setup.  Run in PowerShell **as Administrator**.

  Normally you paste the ONE line that the Pi installer prints (or `sudo mt4mon vps` on the Pi):
    powershell -NoProfile -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create((irm https://raw.githubusercontent.com/kittipatoven/mt4-monitor/main/vps/setup_vps.ps1))) -PiIp 100.x.y.z -ApiKey <key>"

  Optional:  -TsKey tskey-auth-...   join Tailscale with an auth key (no browser login)
             -Magic 52025            magic number of the EA to watch (-1 = none)

  What it does: installs + joins Tailscale, checks the Pi and the key, copies MonitorEA
  into every MT4 data folder it finds, writes the key file, sets the Pi URL, compiles.
  It never touches other EAs, charts, settings or orders.
#>
param(
  [Parameter(Mandatory = $true)][string]$PiIp,
  [Parameter(Mandatory = $true)][string]$ApiKey,
  [string]$TsKey = "",
  [int]$Magic = -1,
  [string]$Repo = "kittipatoven/mt4-monitor",
  [string]$Branch = "main"
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

function Step($t) { Write-Host "`n==> $t" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "   [OK] $t" -ForegroundColor Green }
function Warn($t) { Write-Host "   [!!] $t" -ForegroundColor Yellow }
function Fail($t) { Write-Host "`n[ERROR] $t" -ForegroundColor Red; exit 1 }

function Invoke-Native([string]$exe, [string[]]$argList) {
  # Run a native tool without PowerShell turning its stderr into errors.
  $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  $out = & $exe @argList 2>&1 | Out-String
  $code = $LASTEXITCODE
  $ErrorActionPreference = $old
  return [pscustomobject]@{ Code = $code; Out = $out.Trim() }
}

# ---------------------------------------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Fail "Open PowerShell as Administrator (right-click > Run as administrator) and paste the line again." }
if ($ApiKey -notmatch '^[0-9a-fA-F]{16,128}$') { Fail "-ApiKey looks wrong. On the Pi run:  sudo mt4mon vps" }
if ($PiIp -notmatch '^[0-9A-Za-z.\-]+(:\d+)?$') { Fail "-PiIp looks wrong (example: 100.101.102.103)" }
Write-Host "MT4 Trading Monitor V1 - VPS setup  (Pi: $PiIp)"

# ---------------------------------------------------------------------
Step "1/5 Tailscale"
$ts = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
if (-not (Test-Path $ts)) {
  $msi = Join-Path $env:TEMP 'tailscale-setup.msi'
  Invoke-WebRequest -UseBasicParsing 'https://pkgs.tailscale.com/stable/tailscale-setup-latest-amd64.msi' -OutFile $msi
  $sig = Get-AuthenticodeSignature $msi
  if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'O=Tailscale Inc') {
    Fail "the Tailscale installer is not signed by Tailscale Inc. - stopped for safety"
  }
  $p = Start-Process msiexec.exe -ArgumentList '/i', "`"$msi`"", '/quiet', '/norestart', 'TS_UNATTENDEDMODE=always' -Wait -PassThru
  if ($p.ExitCode -ne 0) { Fail "Tailscale install failed (msiexec code $($p.ExitCode))" }
  Start-Sleep -Seconds 5
  Ok "installed (signature checked)"
} else {
  Ok "already installed"
}

$ip = Invoke-Native $ts @('ip', '-4')
if ($ip.Code -eq 0 -and $ip.Out -match '^100\.') {
  Ok "already logged in: $($ip.Out.Split("`n")[0].Trim())"
} else {
  if (-not $TsKey) {
    $TsKey = Read-Host "   Tailscale auth key (tskey-auth-...), or just press Enter to log in with a browser link"
  }
  if ($TsKey) {
    $r = Invoke-Native $ts @('up', '--unattended', '--hostname=mt4-vps', "--auth-key=$TsKey")
    if ($r.Code -ne 0) { Fail "Tailscale did not accept the auth key: $($r.Out)" }
  } else {
    Write-Host "   Open the link below, sign in with the SAME account as the Pi, press Connect."
    $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    & $ts up --unattended --hostname=mt4-vps
    $ErrorActionPreference = $old
  }
  $ip = Invoke-Native $ts @('ip', '-4')
  if ($ip.Code -ne 0) { Fail "Tailscale is not logged in yet - run this line again" }
  Ok "logged in: $($ip.Out.Split("`n")[0].Trim())"
}

# ---------------------------------------------------------------------
Step "2/5 Pi connection"
$health = $null
for ($i = 1; $i -le 10 -and -not $health; $i++) {
  try { $health = Invoke-RestMethod "http://$PiIp/health" -TimeoutSec 5 } catch { Start-Sleep -Seconds 3 }
}
if (-not $health) { Fail "cannot reach http://$PiIp - is the Pi on and logged in to the same Tailscale account?" }
Ok "Pi answers at http://$PiIp"
try {
  Invoke-RestMethod "http://$PiIp/api/status" -Headers @{ 'X-API-Key' = $ApiKey } -TimeoutSec 5 | Out-Null
  Ok "API key accepted"
} catch {
  Fail "the Pi rejected the API key - copy the line again from:  sudo mt4mon vps"
}

# ---------------------------------------------------------------------
Step "3/5 MT4 data folders"
$termRoot = Join-Path $env:APPDATA 'MetaQuotes\Terminal'
$terms = @(Get-ChildItem $termRoot -Directory -ErrorAction SilentlyContinue |
  Where-Object { Test-Path (Join-Path $_.FullName 'MQL4\Experts') })
if ($terms.Count -eq 0) { Fail "no MT4 data folder in $termRoot - start MT4 once, then run this again" }
foreach ($t in $terms) {
  $origin = (Get-Content (Join-Path $t.FullName 'origin.txt') -ErrorAction SilentlyContinue | Select-Object -First 1)
  Ok "$($t.Name)  ($origin)"
}

# ---------------------------------------------------------------------
Step "4/5 MonitorEA + key"
$url = "http://$PiIp/api/update"
$src = Invoke-RestMethod "https://raw.githubusercontent.com/$Repo/$Branch/mt4/MonitorEA.mq4"
$src = $src -replace '(?m)^(input string\s+InpUrl\s*=\s*)"[^"]*"', ('${1}"' + $url + '"')
$src = $src -replace '(?m)^(input int\s+InpCapybaraMagic\s*=\s*)-?\d+', ('${1}' + $Magic)
if (-not $src.Contains($url)) { Fail "could not set the Pi URL inside MonitorEA.mq4" }
$src = $src -replace "`r?`n", "`r`n"
$ascii = New-Object System.Text.ASCIIEncoding

$compiled = 0
foreach ($t in $terms) {
  $mql = Join-Path $t.FullName 'MQL4'
  $eaPath = Join-Path $mql 'Experts\MonitorEA.mq4'
  New-Item -ItemType Directory -Force -Path (Join-Path $mql 'Files') | Out-Null
  [IO.File]::WriteAllText($eaPath, $src, $ascii)
  [IO.File]::WriteAllText((Join-Path $mql 'Files\MonitorEA_key.txt'), $ApiKey, $ascii)
  Ok "$($t.Name): MonitorEA.mq4 + MonitorEA_key.txt written"

  $origin = (Get-Content (Join-Path $t.FullName 'origin.txt') -ErrorAction SilentlyContinue | Select-Object -First 1)
  $me = if ($origin) { Join-Path $origin.Trim() 'metaeditor.exe' } else { $null }
  if (-not $me -or -not (Test-Path $me)) { Warn "MetaEditor not found - compile it yourself (F4, then F7)"; continue }
  $log = Join-Path $env:TEMP 'monitorea_compile.log'
  Remove-Item $log -ErrorAction SilentlyContinue
  Start-Process -FilePath $me -ArgumentList "/compile:`"$eaPath`"", "/log:`"$log`"" -Wait | Out-Null
  $result = (Get-Content $log -Encoding Unicode -ErrorAction SilentlyContinue | Select-String 'Result:' | Select-Object -Last 1)
  if ("$result" -match '\b0 errors') { Ok "compiled: $("$result".Trim())"; $compiled++ }
  else { Warn "compile problem: $result  (log: $log)" }
}
if ($compiled -eq 0) { Fail "MonitorEA did not compile - send the log above" }

# ---------------------------------------------------------------------
Step "5/5 Three clicks left in MT4"
try { Set-Clipboard -Value "http://$PiIp" } catch { }
Write-Host @"

   1. Tools > Options > Expert Advisors > tick 'Allow WebRequest for listed URL'
      > add   http://$PiIp      (already copied - just paste)  > OK
   2. File > New Chart > any symbol (NOT the chart where your trading EA runs)
   3. Navigator > Expert Advisors > right-click > Refresh > double-click MonitorEA
      > Common tab: untick 'Allow live trading' (not needed) > OK

   MonitorEA already attached from before? Nothing to do - it reloaded with the new build.
   The Pi screen switches from 'Waiting for MT4' to live data within 5 seconds.
"@
Write-Host "VPS SETUP DONE" -ForegroundColor Green
