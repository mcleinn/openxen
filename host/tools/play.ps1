<#
Start a playing session: SuperCollider piano (default) or amsynth (Church Organ freexen) + xentool for the openxen
module(s), optionally a Wooting next to it. Defaults: 53-EDO.

    powershell -ExecutionPolicy Bypass -File host\tools\play.ps1                 # openxen only
    powershell -ExecutionPolicy Bypass -File host\tools\play.ps1 -Wooting        # + Wooting (--no-mts)
    powershell -ExecutionPolicy Bypass -File host\tools\play.ps1 -Edo 31
    powershell -ExecutionPolicy Bypass -File host\tools\play.ps1 -Synth amsynth   # amsynth (Church Organ freexen) instead of the SuperCollider piano
    powershell -ExecutionPolicy Bypass -File host\tools\play.ps1 -Tutor          # + tutor MCP server (this machine only)
    powershell -ExecutionPolicy Bypass -File host\tools\play.ps1 -TutorLan       # + tutor MCP server for the local network
    powershell -ExecutionPolicy Bypass -File host\tools\play.ps1 -TutorTailscale # + tutor MCP server for the tailnet only
    powershell -ExecutionPolicy Bypass -File host\tools\play.ps1 -Stop           # stop xentool and the tutor, clear notes

Key behaviour (aftertouch mode, velocity, thresholds) comes from the openxen section of
%LOCALAPPDATA%\xentool\config\settings.json (currently: aftertouch_mode "depth").
Running xentools are restarted; afterwards All Notes Off is sent so nothing keeps sounding.

Tutor (docs/tutor.md): -Tutor starts xentool with its local API and the tutor MCP server on
http://127.0.0.1:9097/mcp. -TutorLan listens on all interfaces instead and needs a token in the
environment variable OPENXEN_TUTOR_TOKEN (the MCP client sends it as a bearer token).
-TutorTailscale listens on this machine's Tailscale address only (same token); other tailnet
machines reach it encrypted, the local network does not see it. The token may be stored as a
user environment variable; it is read from there if this shell does not have it yet.
-Mridangam: also start the mridangam sample player (host\synth\mridangam.scd, a second SuperCollider
instance) and let the tutor's rhythm tools use it.
-Tabla: the same for the tabla sample player (host\synth\tabla.scd, a SuperCollider instance of its
own; its kit is prepared once with python host\synth\tabla_kit.py).
-Mridangam and -Tabla start the tutor too (as -Tutor) if none of the tutor switches is given.
-Tilt: how the keyfield lies in front of the player: 0 = key rows level (a single module square
on the desk), 'lumatone' = the assembled case (16.1 degrees).
#>
param([int]$Edo = 53, [switch]$Wooting, [switch]$Stop,
      [ValidateSet('supercollider', 'amsynth')][string]$Synth = 'supercollider',
      [switch]$Tutor, [switch]$TutorLan, [switch]$TutorTailscale, [string]$Tilt = '0', [switch]$Mridangam, [switch]$Tabla)

$Repo     = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Xentool  = 'C:\Dev-Free\xentool\target\release\xentool.exe'
$XenDir   = 'C:\Dev-Free\xentool'
$Amsynth  = 'C:\Dev-Free\amsynth_multichannel\win\x64\Release\amsynth_standalone.exe'
$Sclang   = 'C:\Program Files\SuperCollider-3.12.1\sclang.exe'
$ScPatch  = 'C:\Dev-Free\xentool\supercollider\midi_piano_xentool.scd'
$Layouts  = Join-Path $Repo "build\layouts"   # .otn converted from the freexen Lumatone presets
$Wtn      = "wtn\edo$Edo.wtn"
$Panic    = Join-Path $PSScriptRoot 'midi_panic.py'

Get-Process xentool -ErrorAction SilentlyContinue | Stop-Process -Force
# a tutor server left from an earlier session (python -m tutor)
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match '-m tutor\b' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 500
python $Panic
if ($Stop) { return }

python (Join-Path $Repo 'host\layouts\from_lumatone.py') $Edo | Out-Null
$Otn = (Get-ChildItem $Layouts -Filter "${Edo}ET-*.otn" | Sort-Object Name | Select-Object -First 1).FullName
if (-not $Otn) { throw "no ${Edo}ET layout in $Layouts" }
$ServeArgs = @('serve', "`"$Otn`"")
if ($Synth -eq 'amsynth') {
    Get-Process sclang, scsynth -ErrorAction SilentlyContinue | Stop-Process -Force
    if (-not (Get-Process amsynth_standalone -ErrorAction SilentlyContinue)) {
        Start-Process -FilePath $Amsynth -WorkingDirectory (Split-Path $Amsynth)
        Start-Sleep 3
    }
} else {
    # SuperCollider has no MTS-ESP client: xentool sends EDO and pitch offset over OSC
    Get-Process amsynth_standalone -ErrorAction SilentlyContinue | Stop-Process -Force
    if (-not (Get-Process sclang -ErrorAction SilentlyContinue)) {
        Start-Process -FilePath $Sclang -ArgumentList "`"$ScPatch`"" -WorkingDirectory (Split-Path $Sclang)
        Start-Sleep 8
    }
    $ServeArgs += '--tune-supercollider'
    # SuperCollider forgets the piano-studio settings on every restart: re-send the studio's
    # current state, or start the studio (it pushes its saved default at startup).
    try {
        $state = (Invoke-RestMethod 'http://127.0.0.1:9101/api/state' -TimeoutSec 2).state
        Invoke-RestMethod -Method Post 'http://127.0.0.1:9101/api/batch' -ContentType 'application/json' `
            -Body (@{ params = $state } | ConvertTo-Json) -TimeoutSec 2 | Out-Null
    } catch {
        Start-Process -FilePath python -ArgumentList 'server.py' -WorkingDirectory 'C:\Dev-Free\xentool\supercollider\piano_studio'
    }
}
$TutorNet = $TutorLan -or $TutorTailscale
if (($Mridangam -or $Tabla) -and -not $TutorNet) { $Tutor = $true }     # the drums are played by the tutor
$TutorHost = $null
if ($Tutor -or $TutorNet) {
    if ($TutorNet -and -not $env:OPENXEN_TUTOR_TOKEN) {
        $env:OPENXEN_TUTOR_TOKEN = [Environment]::GetEnvironmentVariable('OPENXEN_TUTOR_TOKEN', 'User')
    }
    if ($TutorNet -and -not $env:OPENXEN_TUTOR_TOKEN) { throw 'set OPENXEN_TUTOR_TOKEN before using -TutorLan or -TutorTailscale (any long random string)' }
    if ($TutorLan) { $TutorHost = '0.0.0.0' }
    elseif ($TutorTailscale) {
        $TutorHost = (& tailscale ip -4 | Select-Object -First 1)
        if (-not $TutorHost) { throw 'Tailscale is not running: no address from "tailscale ip -4"' }
    }
    $ServeArgs += '--api'
}
Start-Process -FilePath $Xentool -ArgumentList $ServeArgs -WorkingDirectory $XenDir
if ($Tutor -or $TutorNet) {
    $TutorArgs = @('-m', 'tutor', '--tilt', $Tilt)
    if ($Mridangam) {
        $Patch = Join-Path $Repo 'host\synth\mridangam.scd'
        $Running = Get-CimInstance Win32_Process -Filter "Name='sclang.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match 'mridangam' }
        if (-not $Running) { Start-Process -FilePath $Sclang -ArgumentList "`"$Patch`"" -WorkingDirectory (Split-Path $Sclang) -WindowStyle Minimized }
        $TutorArgs += '--mridangam'
    }
    if ($Tabla) {
        $Patch = Join-Path $Repo 'host\synth\tabla.scd'
        if (-not (Test-Path (Join-Path $Repo 'reference\music\tabla\kit\kit.scd'))) { python (Join-Path $Repo 'host\synth\tabla_kit.py') }
        $Running = Get-CimInstance Win32_Process -Filter "Name='sclang.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match 'tabla\.scd' }
        if (-not $Running) { Start-Process -FilePath $Sclang -ArgumentList "`"$Patch`"" -WorkingDirectory (Split-Path $Sclang) -WindowStyle Minimized }
        $TutorArgs += '--tabla'
    }
    if ($TutorHost) { $TutorArgs += @('--host', $TutorHost) }
    Start-Sleep 2          # xentool's API is up before the tutor asks for the keyboard
    Start-Process -FilePath python -ArgumentList $TutorArgs -WorkingDirectory (Join-Path $Repo 'host')
}
if ($Wooting) {
    Start-Sleep 3          # the openxen instance registers the MTS-ESP tuning first
    Start-Process -FilePath $Xentool -ArgumentList 'serve', $Wtn, '--no-mts' -WorkingDirectory $XenDir
}
"started: $Edo-EDO, $Synth, openxen ($(Split-Path $Otn -Leaf))" + $(if ($Wooting) { ' + Wooting (--no-mts)' } else { '' }) +
    $(if ($TutorTailscale) { " + tutor on http://${TutorHost}:9097/mcp (Tailscale, token)" } elseif ($TutorLan) { ' + tutor on port 9097 (local network, token)' } elseif ($Tutor) { ' + tutor on http://127.0.0.1:9097/mcp' } else { '' })
