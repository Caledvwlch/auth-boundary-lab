# Design Plan: `auth-boundary-lab`

## 1. Scope and Framing

`auth-boundary-lab` is a standalone, offline, synthetic Python 3.9+ educational and regression lab. It models authorization boundaries across asynchronous token preparation, 401 credential refresh/replay, and scoped retry-cooldown computation.

- **Motivation**: Inspired by public engineering patterns in merged OpenCodex PRs [#7621](https://github.com/lidge-jun/opencodex/pull/7621) and [#7622](https://github.com/lidge-jun/opencodex/pull/7622) authored by `Caledvwlch` (with maintainer-lane integration work by `lidge-jun` at commit `d5fdae7bd` documented in the upstream #7622 integration record).
- **Boundary**: All code, state stores, tokens, and transports in this directory are newly written and synthetic. No upstream source code is copied, concurrent quota-read coalescing is not implemented, no network calls or servers are used, and no CVE or live vulnerability claim is made.

## 2. Security Invariants Modeled

1. **Separation of Authority Store from Token Material**:
   - `AuthorityStore` is the single source of truth for account status, provider status, credit-renewal consent, namespace-to-account binding, `credential_generation`, and monotonic revision counters (`binding_revision`, `consent_revision`, `provider_revision`, `account_revision`).
   - `PreparedToken` contains synthetic secret material plus `(account_id, credential_generation)`. Checks reject mismatched account/generation or unauthorized namespace/consent state. The process and store are trusted; this model does not authenticate token originality, cryptographically validate secret material, or defend against direct Python object mutation.
2. **Post-Wait Dispatch Re-verification (TOCTOU Defense)**:
   - Asynchronous token preparation yields control between initial admission and request dispatch.
   - `UnsafeCheckOnceDispatcher` demonstrates the counterexample: checking authority only before `await` allows dispatch (`dispatch_count=1`) after consent withdrawal, namespace unbinding, or credential rotation.
   - `HardenedDispatcher` captures an `AuthoritySnapshot` at admission and re-verifies against `AuthorityStore` immediately before dispatch (`dispatch_count=0` when revoked).
3. **ABA Transition Detection (Revoke/Regrant, Unbind/Rebind, and Same-ID Re-registration)**:
   - `HardenedDispatcher` compares admission `AuthoritySnapshot` revisions against live `AuthorityStore` state (including monotonic history across same-ID `register_account` replacements), blocking in-flight operations that spanned an intermediate revocation or rebinding epoch. These generalized per-field revision counters are specific to this educational lab rather than upstream internals.
4. **401 Refresh and Replay Boundary**:
   - `DispatchOutcome` separates actual transport attempts (`dispatched`, `dispatch_count`, `replayed`) from HTTP 200 completion (`succeeded`, `status_code`). On a synthetic `401 Unauthorized` response (`dispatched=True, dispatch_count=1`), refreshing credentials and replaying requires re-verifying live authority before rotating credentials and again before sending the replay (`replayed=False, dispatch_count=1` when blocked).
5. **Scoped Retry-After Hold Composition and Unknown Evidence Handling**:
   - `compute_retry_advice` computes the effective hold for `(account_id, selected_scope)` as `min(MAX_RETRY_AFTER_SECONDS, max(account_hold_seconds, selected_scope_hold_seconds))`, preventing a shorter account-wide hold (600s) from masking a longer selected-scope hold (900s) while excluding sibling scope holds (1800s).
   - `unsafe_compute_retry_advice` demonstrates the pre-fix counterexample where returning the account-wide hold early masks a longer selected-scope hold.
   - Unavailable (`"unknown"`) credit evidence never grants spending authority, clears an active hold/denial, or switches the bound account; even `"available"` evidence requires explicit `spending_consent=True`.
6. **Scoped Secret Redaction**:
   - Synthetic secrets (`SYN_SECRET_*`) are omitted from `repr()`, `str()`, `PreparedToken.safe_dict()`, `DispatchOutcome.as_dict()`, and CLI JSON output.

## 3. Module Layout

- `auth_boundary_lab/__init__.py`: Public exports.
- `auth_boundary_lab/core.py`: `AuthorityStore`, `AuthoritySnapshot`, `PreparedToken`, `HardenedDispatcher`, `UnsafeCheckOnceDispatcher`, `compute_retry_advice`, `unsafe_compute_retry_advice`.
- `auth_boundary_lab/cli.py` & `auth_boundary_lab/__main__.py`: Deterministic scenario runner emitting compact JSON and exiting non-zero if any invariant check fails.
- `tests/test_auth_boundary_lab.py`: `unittest` suite covering interleaving revocations, positive control, ABA transitions, same-ID re-registration, caller-token spoofing separation, 401 replay checks, scoped retry holds, and secret redaction.
