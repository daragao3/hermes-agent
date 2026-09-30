Evidence for https://github.com/NousResearch/hermes-agent/issues/128804
(Windows Hermes-Setup.exe hangs on Launch after a successful bootstrap).

Source: daragao3/hermes-agent Install & Update E2E run 36443943377, job 109004533254
(windows: installer-script -> desktop-installer@latest, v2026.8.3 -> HEAD), artifact
install-e2e-logs-windows-installer-script---desktop-installer-latest-v2026.8.3---HEAD-.
Files are copied verbatim from that artifact. This branch is an orphan: it carries no
source and exists only so the images can be linked inline from the issue.

frames/00-before-installer.png  desktop before Hermes-Setup.exe was started
frames/frame-0165.png, 0166     success screen with the Launch button, before the click
frames/frame-0167.png           first frame after the click: [ LAUNCHING ] spinner
frames/frame-0184.png           one minute later, unchanged apart from the taskbar clock
frames/frame-0264.png           last frame, 15:54 local, still LAUNCHING, no error
ahk.log                         AutoHotkey driver log
bootstrap-installer.log         the installer's own log, complete
launch-handoff-update/          process list, exe check, release dir at timeout
shas.json                       current / old refs of the run
