"""CLI runner emitting compact JSON scenario results and exiting non-zero on failure."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Dict, List, Optional

from .core import (
    AuthorityStore,
    HardenedDispatcher,
    UnsafeCheckOnceDispatcher,
    compute_retry_advice,
    unsafe_compute_retry_advice,
)


async def _run_scenarios(expect_unsafe_to_pass: bool = False) -> Dict[str, object]:
    scenarios: List[Dict[str, object]] = []

    # 1. Counterexample vs Hardened: mid-preparation consent revocation
    u_store = AuthorityStore()
    u_store.register_account("acct-direct-1", credit_consent=True)
    u_store.bind_namespace("ns-alpha", "acct-direct-1")
    u_dispatcher = UnsafeCheckOnceDispatcher(u_store, lambda a, n, g: asyncio.sleep(0, result=200))

    async def revoke_u() -> None:
        u_store.set_credit_consent("acct-direct-1", False)

    u_out = await u_dispatcher.renew_credit("ns-alpha", "acct-direct-1", on_token_prep=revoke_u)

    h_store = AuthorityStore()
    h_store.register_account("acct-direct-1", credit_consent=True)
    h_store.bind_namespace("ns-alpha", "acct-direct-1")
    h_dispatcher = HardenedDispatcher(h_store, lambda a, n, g: asyncio.sleep(0, result=200))

    async def revoke_h() -> None:
        h_store.set_credit_consent("acct-direct-1", False)

    h_out = await h_dispatcher.renew_credit("ns-alpha", "acct-direct-1", on_token_prep=revoke_h)
    s1_passed = (
        (u_out.dispatch_count == 0)
        if expect_unsafe_to_pass
        else (u_out.dispatch_count == 1 and h_out.dispatch_count == 0 and h_out.reason == "consent_revoked")
    )
    scenarios.append({
        "scenario": "interleaving_consent_revocation",
        "unsafe_counterexample_dispatch_count": u_out.dispatch_count,
        "hardened_dispatch_count": h_out.dispatch_count,
        "hardened_reason": h_out.reason,
        "invariant_passed": s1_passed,
    })

    # 2. Positive control: unchanged authority dispatches cleanly
    pos_store = AuthorityStore()
    pos_store.register_account("acct-direct-1", credit_consent=True)
    pos_store.bind_namespace("ns-alpha", "acct-direct-1")
    pos_dispatcher = HardenedDispatcher(pos_store, lambda a, n, g: asyncio.sleep(0, result=200))
    pos_out = await pos_dispatcher.renew_credit("ns-alpha", "acct-direct-1")
    scenarios.append({
        "scenario": "positive_control_unchanged_authority",
        "hardened_dispatch_count": pos_out.dispatch_count,
        "succeeded": pos_out.succeeded,
        "status_code": pos_out.status_code,
        "invariant_passed": pos_out.dispatch_count == 1 and pos_out.succeeded and pos_out.status_code == 200,
    })

    # 3. ABA rebind and same-ID re-registration during async token preparation are blocked
    aba_store = AuthorityStore()
    aba_store.register_account("acct-direct-1", credit_consent=True)
    aba_store.register_account("acct-direct-2", credit_consent=True)
    aba_store.bind_namespace("ns-alpha", "acct-direct-1")
    aba_dispatcher = HardenedDispatcher(aba_store, lambda a, n, g: asyncio.sleep(0, result=200))

    async def aba_rebind() -> None:
        aba_store.bind_namespace("ns-alpha", "acct-direct-2")
        aba_store.bind_namespace("ns-alpha", "acct-direct-1")

    aba_out = await aba_dispatcher.renew_credit("ns-alpha", "acct-direct-1", on_token_prep=aba_rebind)

    async def aba_reregister() -> None:
        aba_store.set_credit_consent("acct-direct-1", False)
        aba_store.register_account("acct-direct-1", credit_consent=True)

    rereg_out = await aba_dispatcher.renew_credit("ns-alpha", "acct-direct-1", on_token_prep=aba_reregister)
    scenarios.append({
        "scenario": "aba_rebind_and_reregister_during_token_prep",
        "rebind_dispatch_count": aba_out.dispatch_count,
        "rebind_reason": aba_out.reason,
        "reregister_dispatch_count": rereg_out.dispatch_count,
        "reregister_reason": rereg_out.reason,
        "invariant_passed": (
            aba_out.dispatch_count == 0
            and aba_out.reason == "binding_revision_drift"
            and rereg_out.dispatch_count == 0
            and rereg_out.reason == "credential_generation_mismatch"
        ),
    })

    # 4. 401 replay checks authority before replay (initial call dispatches, replay is blocked)
    r_store = AuthorityStore()
    r_store.register_account("acct-direct-1", credit_consent=True)
    r_store.bind_namespace("ns-alpha", "acct-direct-1")
    r_dispatcher = HardenedDispatcher(r_store, lambda a, n, g: asyncio.sleep(0, result=401))

    async def revoke_on_401() -> None:
        r_store.set_credit_consent("acct-direct-1", False)

    r_out = await r_dispatcher.renew_credit("ns-alpha", "acct-direct-1", on_401_refresh=revoke_on_401)
    scenarios.append({
        "scenario": "401_replay_revocation_guard",
        "initial_dispatched": r_out.dispatched,
        "dispatch_count": r_out.dispatch_count,
        "replayed": r_out.replayed,
        "hardened_reason": r_out.reason,
        "invariant_passed": (
            r_out.dispatched
            and r_out.dispatch_count == 1
            and not r_out.replayed
            and not r_out.succeeded
            and r_out.reason == "consent_revoked"
        ),
    })

    # 5. Scoped retry hold max(account, selected_scope) & sibling exclusion
    scoped_holds = {"model-selected": 900, "model-sibling": 1800}
    unsafe_hold = unsafe_compute_retry_advice("acct-direct-1", "model-selected", 600, scoped_holds)
    hardened_hold = compute_retry_advice("acct-direct-1", "model-selected", 600, scoped_holds)
    scenarios.append({
        "scenario": "scoped_retry_hold_composition",
        "unsafe_counterexample_seconds": unsafe_hold.retry_after_seconds,
        "hardened_seconds": hardened_hold.retry_after_seconds,
        "sibling_excluded": hardened_hold.retry_after_seconds == 900,
        "invariant_passed": unsafe_hold.retry_after_seconds == 600 and hardened_hold.retry_after_seconds == 900,
    })

    all_passed = all(bool(item["invariant_passed"]) for item in scenarios)
    return {
        "lab": "auth-boundary-lab",
        "synthetic_only": True,
        "scenarios": scenarios,
        "all_invariants_passed": all_passed,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run offline synthetic auth-boundary-lab scenarios.")
    parser.add_argument(
        "--assert-unhardened-safe",
        action="store_true",
        help="Deliberately assert that the unsafe counterexample is safe (exits non-zero to demonstrate failure).",
    )
    args = parser.parse_args(argv)
    payload = asyncio.run(_run_scenarios(expect_unsafe_to_pass=args.assert_unhardened_safe))
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    return 0 if payload["all_invariants_passed"] else 1
