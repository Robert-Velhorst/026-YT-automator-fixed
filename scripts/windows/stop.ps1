[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$StateFile = Join-Path $Root ".runtime\processes.json"
if (-not (Test-Path $StateFile)) {
    Write-Host "StudioPilot is not running from this workspace."
    exit 0
}
$State = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
if ([IO.Path]::GetFullPath($State.root) -ne [IO.Path]::GetFullPath($Root)) { throw "Runtime state belongs to a different workspace." }
$Markers = @{ api = "waitress"; worker = "worker.py"; ngrok = "ngrok" }
function Stop-RecordedTree([int]$RootId, [string]$Marker, [string]$Name) {
    $Processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $RootProcess = $Processes | Where-Object { $_.ProcessId -eq $RootId } | Select-Object -First 1
    if ($RootProcess -and $RootProcess.CommandLine -notmatch [Regex]::Escape($Marker)) {
        Write-Warning "Did not stop PID $RootId because it no longer matches the recorded $Name process."
        return
    }
    $Ids = [Collections.Generic.List[int]]::new()
    $Queue = [Collections.Generic.Queue[int]]::new()
    $Queue.Enqueue($RootId)
    while ($Queue.Count) {
        $Current = $Queue.Dequeue()
        $Ids.Add($Current)
        foreach ($Child in $Processes | Where-Object { $_.ParentProcessId -eq $Current }) { $Queue.Enqueue($Child.ProcessId) }
    }
    for ($Index = $Ids.Count - 1; $Index -ge 0; $Index--) {
        Stop-Process -Id $Ids[$Index] -Force -ErrorAction SilentlyContinue
    }
    Write-Host "Stopped $Name."
}
foreach ($Name in @("worker", "api", "ngrok")) {
    $Id = $State.processes.$Name
    if (-not $Id) { continue }
    Stop-RecordedTree $Id $Markers[$Name] $Name
}
Remove-Item -LiteralPath $StateFile -Force
