# Registers AIUsageCollector: runs the collector every 15 minutes at user logon.
#
# Provenance: the live AIUsageCollector task on the primary host was registered
# by this script but the script itself was never committed, so the task's
# parameters existed only in the Task Scheduler database. Committing it makes
# the registration reproducible and reviewable.
#
# The runner path is derived from $env:USERPROFILE rather than hardcoded: no
# other tracked script in scripts/ embeds a developer's home directory, and on
# the host this was written for the derived path is byte-identical to the
# original literal. Pass -Runner to point it elsewhere.
[CmdletBinding()]
param(
    [string]$Runner = (Join-Path $env:USERPROFILE '.hermes\bin\ai_usage_collector_run.ps1'),
    [string]$HostExe = (Join-Path $env:USERPROFILE '.hermes\bin\run-hidden-job.exe'),
    [string]$TaskName = 'AIUsageCollector'
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $Runner)) {
    throw "Runner script not found at '$Runner'. Pass -Runner <path> to override."
}

# Launch through bin\run-hidden-job.exe, never powershell.exe directly (2026-09-06).
# A console the task creates VISIBLY is delegated into Windows Terminal, and when
# that terminal closes every console it hosts gets CTRL_CLOSE: on 2026-09-04
# 18:30:22 EDT this task died 0xC000013A that way, 13 seconds into a run, along
# with four other task actions (loops task-console-wt-hosting-harden-20260906).
# The wrapper is a GUI-subsystem host that creates powershell.exe with
# CREATE_NO_WINDOW -- hidden from birth, so conhost never delegates -- and holds
# the tree in a kill-on-close job object, so the 6-minute limit now reaps the
# python child too instead of orphaning it. Same contract as every other hidden
# task on the box (ops\convert-task-to-jobhost.ps1 in ~/.hermes). The
# -WindowStyle Hidden argument stays: harmless, and it documents the intent.
if (-not (Test-Path $HostExe)) {
    throw "Hidden launcher not found at '$HostExe'. Pass -HostExe <path> to override."
}
$action = New-ScheduledTaskAction -Execute $HostExe `
    -Argument "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Runner`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 15)
# ExecutionTimeLimit stays at 6 minutes. It is NOT derived from the repetition
# interval: -MultipleInstances IgnoreNew is what guarantees runs never stack, so
# the interval and the limit move independently. The interval went 5 -> 15 min on
# 2026-08-26 to cut cold interpreter starts 288 -> 96/day; terminations (event 329)
# were dose-responsive to host memory pressure, not to the limit, and a run that
# overruns 6 minutes is still a wedged run worth killing.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 6) `
    -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description 'AI token/quota collector -> ai-tokens.json' -Force
Write-Host "Registered $TaskName"
