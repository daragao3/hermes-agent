# Dependency remediation and SR-605 execution plan

Goal: remove verified, patchable dependency vulnerabilities, then verify enabled Claude scheduled dispatches.
Architecture: retain exact prior identities, change one consumer at a time, reuse accepted recovery evidence. Keep known no-fix findings visible. No new monitoring framework or unrelated upgrades.

- [ ] Freeze the current scanner inventory; deduplicate package/advisory aliases and identify fixed versions from official metadata.
- [ ] Patch the isolated Hermes environment: httpx2/httpcore2 2.12.0, httplib2 0.32.0, pydantic-settings 2.14.2, tornado 6.5.8. Resolve only required support dependencies. Update pyproject and uv lock; verify dependency consistency, actual HTTP/MCP/Codex compatibility and audit before deployment. Keep prior packages for rollback.
- [ ] Evaluate the 16 running Compose image findings. Patch compatible fixable components with retained images and service-specific checks. Record remaining no-fix or separately gated changes explicitly; do not claim them fixed.
- [ ] Refresh SR-501 once after deployment and retain before/after evidence.
- [ ] Reuse the existing SR-605 scheduled-dispatch audit for current enabled tasks, check account/profile/content/completion, preserve disabled definitions, and correct proven defects only.
- [ ] Commit exact changed files with hooks, update completion evidence and shared memory.
