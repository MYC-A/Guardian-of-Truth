param([switch]$Probe)
$ErrorActionPreference = 'Stop'
$workspace = 'C:\Users\Igor\Guardian-v3-threshold-data-lora-20261019'
$evidence = 'A:\Guardian-submissions\guardian-v3-20261019\overnight'
$deadline = [DateTimeOffset]::Parse('2026-10-19T02:48:43Z')
$rollout = 'C:\Users\Igor\.codex\sessions\2026\10\04\rollout-2026-10-04T11-14-55-01a105fa-f70e-76d1-bb0f-87b2790e48cc.jsonl'
[IO.Directory]::CreateDirectory($evidence) | Out-Null
$stamp = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss')
$log = Join-Path $evidence ($stamp + '.log')
if ([DateTimeOffset]::UtcNow -gt $deadline) {
    Disable-ScheduledTask -TaskName 'Guardian-V3-Overnight-20261018' | Out-Null
    'EXPIRED: disabled own scheduled task' | Out-File $log
    exit 0
}
$ErrorActionPreference = 'Continue' # SSH's informational stderr is not a failed SSH exit.
& 'C:\Program Files\Git\usr\bin\ssh.exe' -T -n -i C:/Users/Igor/.ssh/guardian_vast_me -o BatchMode=yes -o ConnectTimeout=15 -p 18293 root@209.137.198.14 'supervisorctl status; nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader' 2>&1 | Out-File $log
$sshExit = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($sshExit -ne 0) { 'SSH_UNAVAILABLE: no automatic restart' | Out-File $log -Append; exit 1 }
if ($Probe) { 'PROBE_OK: no Codex launched' | Out-File $log -Append; exit 0 }
if (([DateTime]::UtcNow - (Get-Item -LiteralPath $rollout).LastWriteTimeUtc).TotalMinutes -lt 20) {
    'ACTIVE_ORIGINAL_CHAT: no concurrent Codex launched' | Out-File $log -Append
    exit 0
}
$counterFile = Join-Path $evidence 'codex-runs.txt'
$count = 0
if (Test-Path -LiteralPath $counterFile) { $count = [int](Get-Content -LiteralPath $counterFile) }
if ($count -ge 4) { 'CODEX_RUN_CAP: monitoring only' | Out-File $log -Append; exit 0 }
($count + 1).ToString() | Set-Content -LiteralPath $counterFile
$prompt = 'Scheduled continuation explicitly requested by the user. Read docs/judge_20261013/V3_AUTOMATION_HANDOFF.md and follow it. Check original chat activity before writes, skip if active within20min. Inspect live server jobs and preserve checkpoint/log evidence; continue only authorized v3 preparation/training/evaluation within the frozen six-hour budget. Do not create subagents or change production/ZIP. Update handoff and write status. Finish within35min; do not wait for long jobs. If Codex quota unavailable leave server jobs running to their finite timeout.'
Push-Location $workspace
try {
    $ErrorActionPreference = 'Continue'
    & 'C:\Users\Igor\AppData\Local\Programs\OpenAI\Codex\bin\codex.exe' exec -C $workspace -s danger-full-access --json -o (Join-Path $evidence ($stamp + '-status.md')) $prompt 2>&1 | Out-File (Join-Path $evidence ($stamp + '-codex.jsonl'))
    $result = $LASTEXITCODE
    ('CODEX_EXIT=' + $result) | Out-File $log -Append
    exit $result
} finally { Pop-Location }
