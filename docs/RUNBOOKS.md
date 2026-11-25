# Runbooks for monitor issues

The daily `monitor` workflow opens GitHub issues; scheduled agents pick them up by label. Each issue body contains
the evidence (what changed / the failure output), the entry's current status, and reproduce commands. One open
issue per (source, label); new information arrives as comments.

General rules for every runbook:
- Work on a branch, open a PR whose body says `Fixes #<issue>`, and keep the PR to the one source.
- Before the PR: `odc validate`, `pytest -m "not live" -q`, `odc contract <id>`. Paste the contract output in the PR.
- If you change adapter behaviour, bump `adapter_version` in the adapter and the catalog entry together.
- Set `last_verified` to today whenever contract tests pass after your change.

## source-changed

The publisher's change signal moved (new release, file replaced, metadata changed, page edited).

1. **Understand the change.** Open the `URL polled` from the issue. Compare `Previous` vs `Now`. Typical causes:
   new data vintage/year; new/renamed columns; moved or deprecated endpoint; methodology note; license/terms edit.
2. **Re-check the license** (mandatory, POLICY §Licensing): `python scripts/snapshot_license.py <id> <terms urls...>`
   (URLs are in `evidence/licenses/<id>/NOTES.md`). Diff the new snapshot against the previous one
   (`diff evidence/licenses/<id>/<old>.txt evidence/licenses/<id>/<new>.txt`). Update NOTES.md and `license.checked_at`.
   If terms became restrictive or unclear → `redistribution: link_only`; if they now forbid our use → `quarantined`
   with reason `license changed: ...`.
3. **Run `odc contract <id>`.** If it fails → also follow [needs-repair](#needs-repair) in the same PR.
4. **Update the entry** for what changed: `coverage.time_range.end`, `key_variables`, new `caveats` (methodology
   changes are caveats!), endpoints, `update` notes. If the adapter needs a new default (e.g. latest year), change it.
5. **If the change signal itself is noisy** (fires without meaningful change — e.g. a page with a rotating token),
   fix `change_detection` to a more stable signal and explain in the PR.
6. If nothing material changed, comment on the issue explaining why, update `last_verified` and `license.checked_at`
   in a small PR (or just close the issue if nothing needed updating).

## needs-repair

Contract tests failed, or the change-detection URL was unreachable twice in a row.

**You get one repair attempt** (one PR). If the PR can't make `odc contract <id>` pass, the same PR must change the
status (POLICY §Status transitions): `degraded` if partially usable (say exactly what works), else `quarantined`.
Never leave a broken source `healthy`.

1. Reproduce: `odc contract <id>`. If it now passes (transient), comment with the output and close the issue.
2. Diagnose by failure kind:

| kind | Usually means | Try |
|---|---|---|
| `network` | DNS/TLS/timeout/connection refused | Is the host in `ops/network-allowlist.txt` and reachable from your environment? If blocked by the environment → don't work around: note it in the issue, queue `reason: network` only if it's a permanent block. If the publisher moved domains → update endpoints + allowlist. |
| `http` 404/410 | file or endpoint moved/removed | Find the new location in the publisher's docs/release notes; update URL patterns. Removed for good → `retired` (if publisher discontinued) or `quarantined`. |
| `http` 401/403 | now requires a key, or bot protection | If a key is now required → convert to a catalog-only entry: `access.method: restricted`, `auth: credentials_required`, `restricted_reason`, `adapter: null`, `adapter_version: null`, `change_detection.method: none`; delete the adapter module; explain in `status_reason`. If bot protection → look for an official API/bulk host; never spoof browsers. |
| `http` 429/5xx | rate limiting / outage | Usually transient; check again later. Persisting > 3 days → `degraded`. |
| `parse` | format changed (HTML error page, new encoding, zip layout) | Fetch the URL with curl and look. Update parsing. |
| `empty` | no rows for the contract filters | Filter semantics/codes changed, or data withdrawn. Check publisher. Maybe the contract case used non-stable data — fix the case (and say why). |
| `schema` | columns missing/renamed | Update the adapter's column handling, `key_variables`, and add a caveat if the meaning changed. Bump minor/major version. |
| `value` | values outside declared ranges | Unit/coding change (e.g. dollars→thousands), or a real outlier. Investigate before loosening a check; add a caveat for real methodology changes. |
| `filter` | adapter rejected its own contract filters | Adapter bug (filter spec changed). Fix the adapter/contract. |
| `error` | exception in adapter code | Read the traceback; fix the bug; add an offline test if possible. |

3. Fix, bump `adapter_version`, run the checks, open the PR (`Fixes #N`).
4. If not fixed: set `status`, `status_reason` (specific: "BLS moved LAUS files to ...; parser not updated"),
   `status_since` = today. Leave the issue open (remove nothing); the monitor keeps retrying quarantined sources with
   backoff and will open a new issue when the source passes again or at 30 days.

### Quarantined source recovered (issue "quarantined source recovered")
Run `odc contract <id>`; if green, set `status: healthy`, `status_reason: Recovered: <what changed>`, `status_since` and
`last_verified` = today. PR with `Fixes #N`.

### Quarantined 30+ days (issue "fix or retire")
Make one last repair attempt. If it fails: `status: retired`, `status_reason: Retired after 30 days quarantined: <cause>`,
`status_since` = today. Keep the catalog file and evidence (ids are never reused). The adapter module may stay; the
server refuses retired sources.

## needs-human

Opened for systemic failures (≥ 4 sources and ≥ 40% of those checked failing in one run), spend/usage anomalies, or
policy questions. **Agents do not act on these** beyond adding factual diagnostic comments if asked.
