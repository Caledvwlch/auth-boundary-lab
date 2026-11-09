# Maintaining authorization boundaries in asynchronous account recovery

This retrospective documents public OpenCodex contributions submitted by the GitHub account **Caledvwlch** in October 2026. It separates the accepted upstream changes from a newly written, synthetic offline teaching lab. The publication date of this retrospective is November 10, 2026; the upstream pull requests were merged on October 26, 2026.

Both contributions are credited to `@Caledvwlch` in the public [OpenCodex v2.93.0 release notes](https://github.com/lidge-jun/opencodex/releases/tag/v2.93.0), published October 27, 2026. This establishes release inclusion as well as PR acceptance.

## Public contribution record

| Contribution | Public acceptance | Relevant engineering work |
| --- | --- | --- |
| [OpenCodex #7621](https://github.com/lidge-jun/opencodex/pull/7621) | Merged into upstream `dev`, merge commit `a3e22148ab4a4bea62a5e97e4e35ab65110f8147` | Renewal of stale credit observations for explicitly bound Direct-mode accounts, with renewed checks of consent, binding and credential generation across asynchronous token preparation and 401 recovery. |
| [OpenCodex #7622](https://github.com/lidge-jun/opencodex/pull/7622) | Merged into upstream `dev`, merge commit `0f642c45a93d241bc05755a17a6fd0c6b02cceed` | Retry advice that preserves account-wide and selected-model holds, separates unknown evidence from a known denial, and does not let missing information authorize spending or select another account. |

The original PR descriptions still contain historical draft/readiness notes. Current merge metadata and the later maintainer integration records establish acceptance; the old prose does not describe the final PR state. These were contributions to an existing project, not authorship of the whole upstream project or appointment as its security maintainer.

The initial contributor-submitted heads were `9995b64a2ffaa68d9a04fc3ee2f865a9e559eff0` (#7621) and `a74dbb3f65f21edab44252ceb032729bc08790e1` (#7622). The accepted heads linked below include subsequent maintainer integration work; the scoped-hold correction described later belongs to that integration work.

## The operational problem and the security boundary

The original Direct-mode failure was an availability problem: an exhausted, explicitly bound stored account could remain locally refused after its credit observation became stale because the renewal path admitted only Pool mode. The same investigation addressed a pre-existing authorization gap in the Pool-mode path: a metadata request already waiting for token preparation could still dispatch after the operator revoked its authority. The fresh comparison below reproduces that existing path, independently of the new Direct-mode feature.

Token preparation is asynchronous. Between selecting an account and sending a metadata request, an operator may remove a namespace binding, withdraw credit consent, pause or remove the account, replace its credentials, or disable or replace the provider. A check made only before the delay cannot establish authority afterward. A 401 refresh/replay creates a second boundary at which current authority must be checked again.

The accepted contribution carries a dispatch guard through the quota-read path and rechecks the current credential generation and renewal eligibility. It also separates ordinary metadata reads from a renewal owner's revocable authority when reads overlap. This is security-sensitive account and credential handling attached to an availability fix. It is not evidence of a demonstrated cross-tenant exploit, a paid-spending incident, or a previously assigned CVE.

## Validation in the upstream record

The contribution includes controlled interleaving tests: prepare a synthetic token, change authority while the preparation is blocked, release it, and assert that no metadata request is dispatched. Positive controls matter too: an unchanged, eligible account must still be able to recover. Related tests exercise credential replacement, binding changes, provider state and 401 replay.

The accepted source can be inspected directly at the recorded heads:

- [Controlled revocation tests in #7621](https://github.com/lidge-jun/opencodex/blob/9dba82f178d43e6a06b131bc61cb541b6f2f9000/tests/codex-integration/codex-direct-renewal-revocation.test.ts).
- [Quota dispatch and recovery implementation in #7621](https://github.com/lidge-jun/opencodex/blob/9dba82f178d43e6a06b131bc61cb541b6f2f9000/src/codex/auth-api/pool-quota-probe.ts).
- [Integrated scoped-retry regressions in #7622](https://github.com/lidge-jun/opencodex/blob/4bd96fe3ab779d1fde0e1f655ea5e8a8a8e7b05f/tests/codex-integration/codex-credit-scoped-retry.test.ts).

The [maintainer integration record for #7621](https://github.com/lidge-jun/opencodex/pull/7621#issuecomment-6423576279) records integration at head `9dba82f178d43e6a06b131bc61cb541b6f2f9000`, successful required CI and a separate security review. The record explicitly describes maintainer integration rather than a formal approving review. The later [#7622 integration record](https://github.com/lidge-jun/opencodex/pull/7622#issuecomment-6426939827) records integration at head `4bd96fe3ab779d1fde0e1f655ea5e8a8a8e7b05f`, its CI results and security-review scope. A separate automated Codex code-review attempt failed to complete; it must not be presented as a successful review.

Those records describe historical upstream validation. The new offline lab does not rerun that upstream suite or independently certify its historical counts. The upstream tests use synthetic accounts and controlled HTTP; they do not demonstrate real upstream billing, real-account traffic, or production stability.

### Fresh check of the real upstream regression

On November 10, 2026, the original upstream tests were also run locally against two isolated, pinned source snapshots: pre-fix `c4d4bb2da2162e23c314befafc5ec104292902a0` and accepted #7621 head `9dba82f178d43e6a06b131bc61cb541b6f2f9000`. The accepted revocation test file was copied unchanged into the pre-fix snapshot; production source was not changed in either snapshot. Both runs used Bun 1.4.3 on macOS and the repository's isolated-home preload.

The selection contained four Pool-mode tests that revoke consent, pause the account, disable the provider, or remove the account while token preparation is suspended, plus two normal-renewal positive controls. The pre-fix snapshot produced **2 passing positive controls and 4 failing revocation checks**: its mocked metadata transport received a request after authority changed. The accepted snapshot produced **6 passes and 0 failures**. The source-byte verification after execution matched the pinned Git blobs in both snapshots.

This is a fresh execution of the real production-source path with controlled token timing and mocked HTTP, distinct from the new Python model. It establishes a narrow post-revocation metadata-dispatch failure under that controlled ordering. It does not establish a live external request, a paid inference operation, a cross-account data breach, attacker-controlled remote exploitation, production race frequency, or an affected release range. See [the reproduction record](UPSTREAM_REPLAY.md) for the exact selection and scope.

## Preserving scoped retry holds

Retry advice is a separate concern from granting authority. When an account has both an account-wide hold and a hold for the selected model scope, advice must retain the later applicable deadline. A shorter account-wide hold must not hide a longer selected-scope hold. A sibling model's hold does not automatically apply to the selected scope.

The maintainer's #7622 record identifies and fixes an integration defect in this area: a shorter account-wide hold could mask a longer selected-scope hold. That correction is credited to the maintainer integration lane, not silently attributed to the original contributor. The final integrated tree and the original submitted contribution are distinct artifacts.

Unknown credit evidence is also distinct from permission. A parser may establish that an observation is unavailable, but that absence cannot grant spending consent, erase a current explicit denial, or authorize changing accounts. Recovery advice should preserve uncertainty without treating it as an affirmative authorization.

## The accompanying offline lab

The separately authored Python lab illustrates these mechanisms using synthetic identities and deterministic, controlled interleavings. It has no service credentials, network requests, account discovery, or live model calls. It is a teaching and regression artifact inspired by the public contributions; it is not a port of the upstream implementation or a newly discovered vulnerability in upstream OpenCodex.

The lab's 600-second versus 900-second hold example illustrates the correction contributed by maintainer `lidge-jun` during #7622 integration (`d5fdae7bd`). Its monotonic consent, binding and provider revision counters are a generalized design extension; they are not a claim that #7621 implemented those same counters. The lab also does not implement upstream request coalescing.

The intentionally unsafe comparison is local and synthetic. Its purpose is to show why an invariant fails when authority is checked only before a delay, then show that the hardened comparison enforces the invariant while permitting the positive control. Passing the lab establishes behavior of the lab under its tests, not that every real integration has the same properties.

## Scope and disclosure status

This is a public engineering case study of already public, accepted contributions. No CVE, bug-bounty payment, formal vulnerability-advisory acceptance, exploit severity, user-adoption count, institutional affiliation or security-maintainer appointment is claimed. A maintainer's merge of a hardening contribution does not automatically confer any of those statuses.

The underlying work supports a verifiable history of account-boundary testing and defensive engineering. Any application or professional profile should describe that work accurately and link to the original PRs and integration records so a reviewer can assess its significance directly.

Prepared with AI assistance. Original upstream code and maintainer work remain attributable to their respective authors; this retrospective links to those sources rather than republishing their code.
