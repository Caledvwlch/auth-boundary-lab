# auth-boundary-lab

`auth-boundary-lab` is a small, offline, dependency-free Python 3.9+ educational and regression lab. It models asynchronous authorization revocation, credential-generation continuity, namespace-to-account binding, 401 refresh/replay guards, and scoped retry-cooldown composition.

## Evidence and reproduction

Start with the [public evidence guide](EVIDENCE.md), [post-revocation technical report](POST_REVOCATION_REPORT.md), [engineering case study](CASE_STUDY.md), and [actual upstream replay](UPSTREAM_REPLAY.md). The replay tests pinned OpenCodex source; the Python lab below illustrates the broader design.

## Context and Attribution

This lab is a synthetic educational model motivated by two merged OpenCodex pull requests authored by **Caledvwlch** (`@Caledvwlch`):

- [OpenCodex PR #7621](https://github.com/lidge-jun/opencodex/pull/7621) (`fix(codex): renew credit evidence for namespace-bound Direct accounts`, merge commit `a3e22148ab4a4bea62a5e97e4e35ab65110f8147`, [maintainer integration record](https://github.com/lidge-jun/opencodex/pull/7621#issuecomment-6423576279)).
- [OpenCodex PR #7622](https://github.com/lidge-jun/opencodex/pull/7622) (`fix(codex): preserve credit recovery retry hints and scoped cooldowns`, merge commit `0f642c45a93d241bc05755a17a6fd0c6b02cceed`, [maintainer integration record](https://github.com/lidge-jun/opencodex/pull/7622#issuecomment-6426939827)). In #7622, maintainer `lidge-jun` (commit `d5fdae7bd`) identified and fixed the scoping defect where a shorter 600-second account-wide hold could mask a longer 900-second selected-scope hold.

The Python package contains newly written standard-library code; it is not a port of upstream OpenCodex. Separate documents describe the historical accepted contribution and actual upstream regression replay. No CVE or external-program approval is claimed.

## Architecture and Invariants

- **Separated Authority Store (`AuthorityStore` vs. `PreparedToken`)**: `AuthorityStore` owns live consent, namespace bindings, account/provider state, `credential_generation`, and monotonic revision counters. Caller-supplied tokens cannot self-assert namespace bindings or bypass store generations.
- **Interleaving Dispatch Guard (`HardenedDispatcher` vs. `UnsafeCheckOnceDispatcher`)**: `UnsafeCheckOnceDispatcher` checks authority only before `await`, dispatching (`dispatch_count=1`) even if consent is revoked mid-preparation. `HardenedDispatcher` re-verifies live state and snapshot revisions immediately before dispatch (`dispatch_count=0` on revocation).
- **ABA Revision Continuity**: Monotonic revision counters (`consent_revision`, `binding_revision`, `provider_revision`, `account_revision`, `credential_generation`) and per-account history across same-ID `register_account` replacements block stale in-flight preparations after revoke/regrant or unbind/rebind cycles. These generalized revision counters are specific to this educational model rather than upstream internals.
- **401 Replay Boundary**: `DispatchOutcome` separates transport attempts (`dispatched`, `dispatch_count`, `replayed`) from HTTP 200 completion (`succeeded`, `status_code`). After an initial `401` (`dispatched=True, dispatch_count=1`), authority is rechecked before credential rotation and before replay (`replayed=False, dispatch_count=1` if revoked during refresh).
- **Scoped Retry Holds (`compute_retry_advice`)**: Retains `min(86400, max(account_hold_seconds, selected_scope_hold_seconds))` (e.g., 900s over 600s) while excluding sibling model scopes (e.g., 1800s). Unavailable (`"unknown"`) credit evidence never grants spending or switches accounts, and `"available"` evidence still requires explicit `spending_consent=True`.
- **Scoped Secret Redaction**: Synthetic secrets (`SYN_SECRET_*`) are omitted from `repr()`, `str()`, `PreparedToken.safe_dict()`, `DispatchOutcome.as_dict()`, and CLI JSON output.

## Demo and Test Commands

```bash
python3 -m unittest discover -s tests -v
python3 -m auth_boundary_lab
python3 -m auth_boundary_lab --assert-unhardened-safe  # exits 1
```

## Limitations

- Purely offline in-memory simulation; does not implement concurrent quota-read coalescing, network I/O, or live provider authentication.
- The process and `AuthorityStore` are trusted. Token account/generation checks model authorization continuity; they do not cryptographically authenticate caller-supplied secret material or defend against arbitrary mutation of Python objects.
- Redaction covers `repr`/`str`, `safe_dict()`, `DispatchOutcome.as_dict()`, and CLI JSON, not direct inspection of private `_secret_material` attributes.

## License and Credits

MIT License ([LICENSE](./LICENSE)). Authored by **Caledvwlch** (`@Caledvwlch`) with AI assistance.
