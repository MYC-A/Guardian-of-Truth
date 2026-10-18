$ErrorActionPreference = 'Stop'
$deadline = [DateTimeOffset]::Parse('2026-10-19T02:48:43Z')
$guard = New-Object Threading.Mutex($false, 'Local\GuardianV3OvernightAwake20261018')
if (-not $guard.WaitOne(0)) { exit 0 }
Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
public static class GuardianV3Awake {
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern uint SetThreadExecutionState(uint flags);
}
'@
try {
    if ([GuardianV3Awake]::SetThreadExecutionState([uint32]2147483649) -eq 0) { throw 'KEEP_AWAKE_FAILED' }
    while ([DateTimeOffset]::UtcNow -lt $deadline) { Start-Sleep -Seconds 30 }
} finally {
    [GuardianV3Awake]::SetThreadExecutionState([uint32]2147483648) | Out-Null
    $guard.ReleaseMutex();$guard.Dispose()
}
