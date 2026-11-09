# Post-Revocation Metadata Dispatch During Asynchronous Token Preparation in OpenCodex

*Self-published retrospective technical report (published November 10, 2026) documenting an upstream code fix authored by `Caledvwlch` and merged into [`lidge-jun/opencodex#7621`](https://github.com/lidge-jun/opencodex/pull/7621) on October 26, 2026 UTC (October 27, 2026 KST; merge commit `a3e22148a`, [maintainer integration record](https://github.com/lidge-jun/opencodex/pull/7621#issuecomment-6423576279)). Prepared with AI assistance. This document is not a CVE record, a GitHub Security Advisory (GHSA), a bug-bounty report, or an official vendor security advisory.*

## Executive Summary

In pre-fix `lidge-jun/opencodex` releases `v2.90.0` through `v2.92.0`, the background quota-priming worker in `src/codex/auth-api/pool-mode-gate.ts` and `src/codex/auth-api/pool-quota-probe.ts` checked whether a stored Pool account was eligible for credit-evidence renewal before awaiting asynchronous token preparation, but did not re-verify that eligibility after `await getValidToken(accountId)` resolved. When a local operator withdrew credit-renewal consent, paused the account, disabled the OpenAI provider, or removed the account while token preparation was suspended, `fetchFreshPoolAccountQuota` still called `fetchCodexUsage` for `https://chatgpt.com/backend-api/wham/usage`.

No external attacker position is established by this defect. Triggering the issue required local configuration changes made while an eligible Pool account's background credit-renewal pass was suspended in `getValidToken`. The narrowest demonstrated impact is a single post-revocation metadata `GET` request to the mocked WHAM usage endpoint inside the local test harness; it does not establish unauthenticated remote exploitation, cross-account credential theft, or unauthorized paid model inference.

The vulnerable `credit-renewal` sweep path was introduced on October 19, 2026 in commit `d3dafd39e` (pull request #7393). Source inspection confirms that `src/codex/auth-api/pool-mode-gate.ts` (Git blob `e024473cd`) and `src/codex/auth-api/pool-quota-probe.ts` (Git blob `55d30da19`) are byte-for-byte identical across release commits [`v2.90.0`](https://github.com/lidge-jun/opencodex/releases/tag/v2.90.0) (`994d15e8a`), [`v2.91.0`](https://github.com/lidge-jun/opencodex/releases/tag/v2.91.0) (`83ec4f75a`), [`v2.92.0`](https://github.com/lidge-jun/opencodex/releases/tag/v2.92.0) (`9f0d40a25`), and the runtime-executed pre-fix `dev` snapshot `c4d4bb2da`. The fix was merged in [pull request #7621](https://github.com/lidge-jun/opencodex/pull/7621) (`a3e22148a`, tested head `9dba82f1`) and is source-confirmed in [`v2.93.0`](https://github.com/lidge-jun/opencodex/releases/tag/v2.93.0) (`88aaa7545`). I inspected the introducing change, the release targets, and the pre-fix and fixed source files directly in Git, and I verified the execution logs from a deterministic six-test Bun run comparing unmodified pre-fix snapshot `c4d4bb2da` against fixed snapshot `9dba82f1` using mocked HTTP and synthetic fixture credentials; the tagged release builds themselves were source-verified rather than separately runtime-executed, and the HTTP 401 refresh/replay and in-flight coalescing guards were verified by source and PR test inspection rather than freshly re-run in that six-test selection.

## Background

OpenCodex can route requests across stored OpenAI accounts in Pool mode (`codexAccountMode: "pool"`). When a stored account exhausts its included usage window (for example, `weeklyPercent: 100`) and the local operator has explicitly opted that account into `creditCodexAccountIds`, a background sweeper periodically re-queries the upstream WHAM usage endpoint (`https://chatgpt.com/backend-api/wham/usage`) once the cached credit observation is at least three minutes old (`MAIN_CREDIT_RENEWAL_AGE_MS = 3 * 60_000`).

This renewal path is opt-in rather than active by default: it requires an enabled canonical OpenAI forward provider in `pool` mode, a stored non-main account with an exhausted usage window, and the account ID listed in `creditCodexAccountIds`. How frequently deployments enable these settings in production is unknown.

Because token preparation (`getValidToken`) is asynchronous and may await token resolution or refresh, the local operator can change account or provider policy while preparation is in flight—by removing the account from `creditCodexAccountIds`, adding it to `pausedCodexAccountIds`, setting `providers.openai.disabled = true`, or removing the account from `codexAccounts`. Once any of those revocations occurs, the background renewal worker should abort before dispatching an upstream WHAM metadata request for that account.

## Vulnerability Details

In commit `d3dafd39e` (pull request #7393), `registerCodexCooldownRecoveryProbeWorker` began scheduling `primeCodexPoolQuotas(config, "credit-renewal")`, which checks account eligibility via `poolCreditRenewalDue` in [`src/codex/auth-api/pool-mode-gate.ts`](https://github.com/lidge-jun/opencodex/blob/c4d4bb2da2162e23c314befafc5ec104292902a0/src/codex/auth-api/pool-mode-gate.ts) (lines 82–94) and re-checks it once at line 381 before calling `fetchPoolAccountQuota`:

```ts
// src/codex/auth-api/pool-mode-gate.ts (v2.90.0-v2.92.0 & pre-fix snapshot c4d4bb2da, lines 380-387)
if (!getCodexAccountCredential(a.id)) return;
if (reason === "credit-renewal" && !poolCreditRenewalDue(getRuntimeConfig(config), a.id)) return;
let result: PoolQuotaResult;
try {
  const quota = getAccountQuota(a.id);
  const bypassCachedQuota = reason === "credit-renewal" || (reason === "priority-failback" && quota !== null
    && !codexQuotaHasFreshUsage(quota, a.plan, Date.now(), CODEX_PRIORITY_FAILBACK_REFRESH_MS));
  result = await fetchPoolAccountQuota(a.id, bypassCachedQuota, a.plan, getValidPoolTokenForPrime);
```

`fetchPoolAccountQuota` calls `fetchFreshPoolAccountQuota` in [`src/codex/auth-api/pool-quota-probe.ts`](https://github.com/lidge-jun/opencodex/blob/c4d4bb2da2162e23c314befafc5ec104292902a0/src/codex/auth-api/pool-quota-probe.ts). At line 402, execution suspends at `await getValidToken(accountId)`. When that promise resolves, lines 406–412 in `v2.90.0`–`v2.92.0` (`c4d4bb2da`) immediately invoked `fetchCodexUsage` without rechecking whether renewal authority still held:

```ts
// src/codex/auth-api/pool-quota-probe.ts (v2.90.0-v2.92.0 & pre-fix snapshot c4d4bb2da, lines 402-410)
const { accessToken, chatgptAccountId, generation } = await getValidToken(accountId);
const poolWriter = capturePoolQuotaWriter(accountId, { accessToken, chatgptAccountId, generation });
requestCredentialGeneration = generation;
onCredentialGeneration?.(generation);
const admission = await fetchCodexUsage<PoolQuotaResult>(
  `pool:${accountId}:${writerGeneration}:${generation}${afterDispatchSequence === undefined ? "" : `:post-reset:${afterDispatchSequence}`}`, {
  headers: { Authorization: `Bearer ${accessToken}`, "ChatGPT-Account-Id": chatgptAccountId },
  signal: AbortSignal.timeout(8000),
}, () => markQuotaProbeAttempted(quotaProbeEvidence, generation),
```

Source inspection of `src/codex/auth-api/pool-quota-probe.ts` in `c4d4bb2da` also shows the same missing caller-authority check in `recoverPoolQuotaFrom401` (lines 256–268) after an HTTP 401 token refresh, as well as in-flight coalescing in `fetchPoolAccountQuota` (lines 536–546) that did not separate revocable renewal flights from ordinary metadata reads. Those 401-replay and coalescing paths were verified by source inspection and the inspected PR #7621 regression suite ([`tests/codex-integration/codex-direct-renewal-revocation.test.ts`](https://github.com/lidge-jun/opencodex/blob/9dba82f178d43e6a06b131bc61cb541b6f2f9000/tests/codex-integration/codex-direct-renewal-revocation.test.ts)), and were not freshly executed in the six-test pre-fix versus post-fix comparison run below.

Comparing Git tree objects across the release history confirms that `src/codex/auth-api/pool-mode-gate.ts` (blob `e024473cdb9eff674a4cd7ba634395cfee06d29a`) and `src/codex/auth-api/pool-quota-probe.ts` (blob `55d30da198c93c0f10dc87f204fe6c0848d03b6a`) are identical in `v2.90.0` (`994d15e8a3d071e231ff0de41eab9dfbee8817aa`), `v2.91.0` (`83ec4f75a4cc97030c2fa7857e05e2ce222f376f`), `v2.92.0` (`9f0d40a25f8b842c33ab233d466d0bd991d86052`), and the runtime-tested pre-fix snapshot `c4d4bb2da2162e23c314befafc5ec104292902a0`. Direct source inspection of release `v2.93.0` (`88aaa754566d119b6b8fc898f8fb47602387d82e`) confirms that `v2.93.0` includes the `mayDispatch` and `dispatchGuarded` remediation from pull request #7621 (`a3e22148ab4a4bea62a5e97e4e35ab65110f8147`).

## Exploitability Analysis

The demonstrated primitive is narrow: when `getValidToken(accountId)` is suspended during a Pool `credit-renewal` pass and the local operator revokes consent, pauses the account, disables the provider, or removes the account before `getValidToken` returns, the pre-fix worker still invokes the WHAM metadata transport once for that account.

No external network attacker or cross-tenant boundary crossing is involved. Triggering the condition requires local state changes coinciding with the asynchronous window between line 381 of `src/codex/auth-api/pool-mode-gate.ts` and line 406 of `src/codex/auth-api/pool-quota-probe.ts`. In the verification run, that window is held open deterministically with a test resolver hook; natural race frequency in production was not measured. Even if a stale metadata probe completes, downstream request admission still checks live credit consent and account state before permitting model inference.

The six-test run includes two positive controls from `tests/codex-integration/codex-quota-prime.test.ts` (`credit renewal at 180000 ms` and `credit renewal at 360000 ms`). Both pass on both `c4d4bb2da` and `9dba82f1`, ruling out the alternative explanation that the fixed revision simply disables Pool credit-renewal probes.

## Proof of Concept

The runtime reproduction compares unmodified pre-fix snapshot `c4d4bb2da` against fixed snapshot `9dba82f1` (not separate builds of the `v2.90.0`–`v2.92.0` release tags), with the accepted test file [`tests/codex-integration/codex-direct-renewal-revocation.test.ts`](https://github.com/lidge-jun/opencodex/blob/9dba82f178d43e6a06b131bc61cb541b6f2f9000/tests/codex-integration/codex-direct-renewal-revocation.test.ts) from `9dba82f1` copied byte-for-byte into the pre-fix checkout. The test preload isolates `OPENCODEX_HOME` to a temporary directory and replaces `globalThis.fetch` with an in-memory spy that records requests to `https://chatgpt.com/backend-api/wham/usage` and throws on any unexpected URL. The header values `Bearer fixture-access` and `fixture-workspace` are synthetic fixture strings; no real credentials or network calls are used.

Only the four `Pool renewal also rechecks ...` cases and two positive controls were selected (`49 filtered out`) because Direct-mode credit renewal did not exist in `c4d4bb2da` and would return early before token preparation. From the root of each snapshot checkout, run:

```sh
bun test \
  ./tests/codex-integration/codex-direct-renewal-revocation.test.ts \
  ./tests/codex-integration/codex-quota-prime.test.ts \
  -t 'Pool renewal also rechecks|credit renewal at .*reads WHAM'
```

On pre-fix snapshot `c4d4bb2da`, all four Pool revocation checks fail because the mocked transport receives the synthetic request after revocation, while the two positive controls pass (selected log excerpt below; repeated per-case failure blocks and local checkout path prefix `<repo_root>` omitted for brevity):

```text
bun test v1.4.3 (c6da4a4d3)

tests/codex-integration/codex-direct-renewal-revocation.test.ts:
138 |     expect(calls).toEqual([]);
                        ^
error: expect(received).toEqual(expected)
- []
+ [ { "account": "fixture-workspace", "bearer": "Bearer fixture-access" } ]
      at <anonymous> (<repo_root>/tests/codex-integration/codex-direct-renewal-revocation.test.ts:138:19)
(fail) credit renewal rechecks authority after token preparation > Pool renewal also rechecks consent after token preparation [14.14ms]
[... 3 identical failure blocks for pause, provider, and removal omitted ...]
(fail) credit renewal rechecks authority after token preparation > Pool renewal also rechecks pause after token preparation [2.67ms]
(fail) credit renewal rechecks authority after token preparation > Pool renewal also rechecks provider after token preparation [2.38ms]
(fail) credit renewal rechecks authority after token preparation > Pool renewal also rechecks removal after token preparation [2.41ms]

tests/codex-integration/codex-quota-prime.test.ts:
(pass) primeCodexPoolQuotas > credit renewal at 180000 ms reads WHAM despite fresh traffic headers and never touches native main (#7377) [4.14ms]
(pass) primeCodexPoolQuotas > credit renewal at 360000 ms reads WHAM despite fresh traffic headers and never touches native main (#7377) [2.36ms]

 2 pass / 49 filtered out / 4 fail / 36 expect() calls — Ran 6 tests across 2 files. [204.00ms]
```

On fixed snapshot `9dba82f1`, the same command exits 0 with `6 pass, 49 filtered out, 0 fail` across the same 6 tests (`114.00ms`).

## Remediation

To close the post-await gap, the caller must pass a synchronous dispatch predicate into `fetchPoolAccountQuota` and evaluate it immediately before each `fetchCodexUsage` call, using the live configuration and the credential generation returned by token preparation.

In [pull request #7621](https://github.com/lidge-jun/opencodex/pull/7621) (integrated at `9dba82f1`, squash-merged as `a3e22148a`, and shipped in [`v2.93.0`](https://github.com/lidge-jun/opencodex/releases/tag/v2.93.0)), `primeCodexPoolQuotas` passes a `mayDispatch` predicate for `credit-renewal` passes in [`src/codex/auth-api/pool-mode-gate.ts`](https://github.com/lidge-jun/opencodex/blob/9dba82f178d43e6a06b131bc61cb541b6f2f9000/src/codex/auth-api/pool-mode-gate.ts) (lines 396–400):

```ts
result = await fetchPoolAccountQuota(a.id, bypassCachedQuota, a.plan, getValidPoolTokenForPrime,
  false, undefined, undefined, false, reason === "credit-renewal"
    ? generation => isCodexAccountGenerationLive(a.id, generation)
      && poolCreditRenewalDue(getRuntimeConfig(config), a.id)
    : undefined);
```

Inside [`src/codex/auth-api/pool-quota-probe.ts`](https://github.com/lidge-jun/opencodex/blob/9dba82f178d43e6a06b131bc61cb541b6f2f9000/src/codex/auth-api/pool-quota-probe.ts), `fetchFreshPoolAccountQuota` (lines 413–415) and `recoverPoolQuotaFrom401` (lines 261–263) abort before `fetchCodexUsage` when `mayDispatch(generation)` returns `false`, and `fetchPoolAccountQuota` (lines 541–542) sets `dispatchGuarded` so unguarded metadata reads do not join a revocable renewal flight:

```ts
if (quotaProbeEvidence.mayDispatch?.(generation) === false) {
  return { quota: getAccountQuota(accountId), needsReauth: false, credentialGeneration: generation, quotaProbeSkipped: true };
}
```

## Summary

In OpenCodex releases `v2.90.0` (`994d15e8a`), `v2.91.0` (`83ec4f75a`), and `v2.92.0` (`9f0d40a25`)—introduced in commit `d3dafd39e` (#7393) and runtime-reproduced on pre-fix snapshot `c4d4bb2da`—background Pool credit-renewal probes checked account eligibility before `await getValidToken(accountId)` but not before dispatching the subsequent WHAM usage request. Under a controlled test interleaving where local consent, pause state, provider enablement, or account membership is revoked during token preparation, the pre-fix code dispatches one synthetic WHAM metadata request (`2 pass / 4 fail`), whereas fixed revision `9dba82f1` (merged as `a3e22148a` and source-confirmed in release `v2.93.0`, `88aaa7545`) aborts dispatch and passes all six checks (`6 pass / 0 fail`).
