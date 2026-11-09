# Real upstream regression replay

Executed on November 10, 2026 with Bun 1.4.3 on macOS. This record concerns the existing OpenCodex production source and its accepted regression tests, rather than the separately written Python teaching model.

## Pinned inputs

| Input | Revision |
| --- | --- |
| Pre-fix source | `c4d4bb2da2162e23c314befafc5ec104292902a0` |
| Accepted #7621 source | `9dba82f178d43e6a06b131bc61cb541b6f2f9000` |
| Revocation test | `tests/codex-integration/codex-direct-renewal-revocation.test.ts` from accepted #7621 source |
| Positive-control test | `tests/codex-integration/codex-quota-prime.test.ts` from each snapshot |

The accepted revocation test file was copied byte-for-byte into the pre-fix snapshot. No production source was patched or replaced. Dependencies already installed for the local project were shared read-only through a symlink; this was not a clean dependency installation. Both snapshots used the same installed Bun version.

The tests run with the repository's `bunfig.toml` and isolated-home preload. Account records and transport responses are synthetic. The selected test fixtures replace external HTTP and reject unexpected URLs. No live provider, model, production proxy, actual credential or billing transaction was used.

## Exact selection

From the root of each isolated source snapshot:

```sh
bun test \
  ./tests/codex-integration/codex-direct-renewal-revocation.test.ts \
  ./tests/codex-integration/codex-quota-prime.test.ts \
  -t 'Pool renewal also rechecks|credit renewal at .*reads WHAM'
```

Run from that snapshot root so that its isolated-home preload is loaded. This command is a focused selection, not the entire upstream test suite. It assumes the public project and its dependencies have already been obtained and prepared in a disposable checkout.

Pool mode was selected because it already reached token preparation in the pre-fix source. Direct mode returned early there, so its no-dispatch checks could succeed simply because renewal was not implemented. The four Pool-mode checks and two functioning-renewal controls isolate the pre-existing authorization gap. Other regressions, including 401 refresh and coalescing, were not part of this fresh six-test execution.

## Observed outcomes

| Check | Pre-fix | Accepted #7621 |
| --- | --- | --- |
| Consent withdrawn while token preparation is suspended | Failure: mocked metadata request dispatched | Pass: no dispatch |
| Account paused during the delay | Failure: mocked metadata request dispatched | Pass: no dispatch |
| Provider disabled during the delay | Failure: mocked metadata request dispatched | Pass: no dispatch |
| Account removed during the delay | Failure: mocked metadata request dispatched | Pass: no dispatch |
| Eligible normal renewal with older observation, first positive control | Pass | Pass |
| Eligible normal renewal with older observation, second positive control | Pass | Pass |

Observed summaries:

```text
Pre-fix:             2 pass, 4 fail, 49 filtered out; exit 1
Accepted #7621:      6 pass, 0 fail, 49 filtered out; exit 0
```

The failing assertion expects the transport's request list to stay empty after revocation. In the pre-fix run it instead contains one synthetic metadata request. The positive controls rule out the trivial explanation that every metadata operation is disabled in the fixed snapshot.

After both runs, all extracted production files under `src/` were compared to the Git blob identities of their respective pinned revisions and matched. The regression test bytes were identical in both copies.

## Interpretation and limits

The demonstrated condition is that an account's local metadata renewal can cross a consent/pause/provider/removal change while token preparation is already in flight. The fixed source rechecks current authority before dispatch. This is a security-sensitive lifecycle boundary; it is not evidence that another user can steal the account, that a model inference is sent, or that credit is spent.

The scheduler interleaving is controlled by the test fixture. Its frequency in production was not measured. No first affected release, complete affected-version range, CVSS severity or CVE is assigned here. The exact public revisions identify the code that was actually tested. The current tip and all other releases were not retested by this focused exercise.

Original sources and acceptance: [#7621](https://github.com/lidge-jun/opencodex/pull/7621), [accepted regression file](https://github.com/lidge-jun/opencodex/blob/9dba82f178d43e6a06b131bc61cb541b6f2f9000/tests/codex-integration/codex-direct-renewal-revocation.test.ts), [maintainer integration record](https://github.com/lidge-jun/opencodex/pull/7621#issuecomment-6423576279).
