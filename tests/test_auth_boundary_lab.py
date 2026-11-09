import asyncio
import json
import subprocess
import sys
import unittest
from pathlib import Path

from auth_boundary_lab import (
    MAX_RETRY_AFTER_SECONDS,
    AuthorityStore,
    HardenedDispatcher,
    PreparedToken,
    UnsafeCheckOnceDispatcher,
    compute_retry_advice,
    unsafe_compute_retry_advice,
)


class AuthBoundaryLabTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = AuthorityStore()
        self.store.register_account("acct-direct-1", credit_consent=True)
        self.store.register_account("acct-direct-2", credit_consent=True)
        self.store.bind_namespace("ns-alpha", "acct-direct-1")

    def test_interleaving_consent_revocation_blocks_hardened_and_exposes_unsafe(self) -> None:
        async def run_case() -> None:
            # 1. Counterexample: Unsafe check-once dispatcher sends request despite mid-prep consent revocation.
            unsafe_store = AuthorityStore()
            unsafe_store.register_account("acct-direct-1", credit_consent=True)
            unsafe_store.bind_namespace("ns-alpha", "acct-direct-1")
            prep_started = asyncio.Event()
            allow_finish = asyncio.Event()
            unsafe_calls = []

            async def gated_hook() -> None:
                prep_started.set()
                await allow_finish.wait()

            async def unsafe_transport(account_id: str, namespace: str, token_gen: int) -> int:
                unsafe_calls.append((account_id, namespace, token_gen))
                return 200

            unsafe_dispatcher = UnsafeCheckOnceDispatcher(unsafe_store, unsafe_transport)
            task = asyncio.create_task(
                unsafe_dispatcher.renew_credit("ns-alpha", "acct-direct-1", on_token_prep=gated_hook)
            )
            await prep_started.wait()
            unsafe_store.set_credit_consent("acct-direct-1", False)
            allow_finish.set()
            unsafe_outcome = await task
            self.assertTrue(unsafe_outcome.dispatched)
            self.assertEqual(unsafe_outcome.dispatch_count, 1)
            self.assertTrue(unsafe_outcome.succeeded)
            self.assertEqual(len(unsafe_calls), 1)

            # 2. Hardened dispatcher: blocks dispatch when consent is revoked during token preparation.
            prep_started_h = asyncio.Event()
            allow_finish_h = asyncio.Event()
            hardened_calls = []

            async def gated_hook_h() -> None:
                prep_started_h.set()
                await allow_finish_h.wait()

            async def hardened_transport(account_id: str, namespace: str, token_gen: int) -> int:
                hardened_calls.append((account_id, namespace, token_gen))
                return 200

            hardened_dispatcher = HardenedDispatcher(self.store, hardened_transport)
            task_h = asyncio.create_task(
                hardened_dispatcher.renew_credit("ns-alpha", "acct-direct-1", on_token_prep=gated_hook_h)
            )
            await prep_started_h.wait()
            self.store.set_credit_consent("acct-direct-1", False)
            allow_finish_h.set()
            hardened_outcome = await task_h
            self.assertFalse(hardened_outcome.dispatched)
            self.assertEqual(hardened_outcome.dispatch_count, 0)
            self.assertFalse(hardened_outcome.succeeded)
            self.assertEqual(hardened_outcome.reason, "consent_revoked")
            self.assertEqual(len(hardened_calls), 0)

        asyncio.run(run_case())

    def test_interleaving_namespace_unbind_and_credential_rotation_block_dispatch(self) -> None:
        async def run_case() -> None:
            calls = []

            async def transport(account_id: str, namespace: str, token_gen: int) -> int:
                calls.append((account_id, namespace, token_gen))
                return 200

            dispatcher = HardenedDispatcher(self.store, transport)

            # Case A: Namespace unbound/rebound to another account during token preparation.
            async def unbind_during_prep() -> None:
                self.store.bind_namespace("ns-alpha", "acct-direct-2")

            outcome_unbind = await dispatcher.renew_credit(
                "ns-alpha", "acct-direct-1", on_token_prep=unbind_during_prep
            )
            self.assertFalse(outcome_unbind.dispatched)
            self.assertEqual(outcome_unbind.reason, "namespace_binding_mismatch")
            self.assertEqual(len(calls), 0)

            # Restore binding and test Case B: Credential rotation during token preparation.
            self.store.bind_namespace("ns-alpha", "acct-direct-1")

            async def rotate_during_prep() -> None:
                self.store.rotate_credentials("acct-direct-1")

            outcome_rotate = await dispatcher.renew_credit(
                "ns-alpha", "acct-direct-1", on_token_prep=rotate_during_prep
            )
            self.assertFalse(outcome_rotate.dispatched)
            self.assertEqual(outcome_rotate.reason, "credential_generation_mismatch")
            self.assertEqual(len(calls), 0)

        asyncio.run(run_case())

    def test_aba_regrant_and_rebind_blocked_by_revision_epoch(self) -> None:
        async def run_case() -> None:
            calls = []

            async def transport(account_id: str, namespace: str, token_gen: int) -> int:
                calls.append((account_id, namespace, token_gen))
                return 200

            dispatcher = HardenedDispatcher(self.store, transport)

            # ABA 1: Consent revoked then re-granted during async token preparation.
            async def aba_consent() -> None:
                self.store.set_credit_consent("acct-direct-1", False)
                self.store.set_credit_consent("acct-direct-1", True)

            outcome_consent_aba = await dispatcher.renew_credit(
                "ns-alpha", "acct-direct-1", on_token_prep=aba_consent
            )
            self.assertFalse(outcome_consent_aba.dispatched)
            self.assertEqual(outcome_consent_aba.reason, "consent_revision_drift")

            # ABA 2: Namespace switched to acct-direct-2 and back to acct-direct-1 during token prep.
            async def aba_binding() -> None:
                self.store.bind_namespace("ns-alpha", "acct-direct-2")
                self.store.bind_namespace("ns-alpha", "acct-direct-1")

            outcome_binding_aba = await dispatcher.renew_credit(
                "ns-alpha", "acct-direct-1", on_token_prep=aba_binding
            )
            self.assertFalse(outcome_binding_aba.dispatched)
            self.assertEqual(outcome_binding_aba.reason, "binding_revision_drift")

            # ABA 3: Provider disabled and re-enabled during token prep.
            async def aba_provider() -> None:
                self.store.set_provider_enabled("acct-direct-1", False)
                self.store.set_provider_enabled("acct-direct-1", True)

            outcome_provider_aba = await dispatcher.renew_credit(
                "ns-alpha", "acct-direct-1", on_token_prep=aba_provider
            )
            self.assertFalse(outcome_provider_aba.dispatched)
            self.assertEqual(outcome_provider_aba.reason, "provider_revision_drift")

            # ABA 4 (Blocker 1 regression): Same-ID account re-registration after consent change during prep
            # must not reset monotonic revisions/generations back to 1 and allow stale token dispatch.
            regen_store = AuthorityStore()
            regen_store.register_account("a", credit_consent=True)
            regen_store.bind_namespace("n", "a")
            regen_dispatcher = HardenedDispatcher(regen_store, transport)

            async def aba_reregister_same_id() -> None:
                regen_store.set_credit_consent("a", False)
                regen_store.register_account("a", credit_consent=True)

            outcome_reregister = await regen_dispatcher.renew_credit(
                "n", "a", on_token_prep=aba_reregister_same_id
            )
            self.assertFalse(outcome_reregister.dispatched)
            self.assertEqual(outcome_reregister.dispatch_count, 0)
            self.assertIn(outcome_reregister.reason, ("credential_generation_mismatch", "account_revision_drift", "consent_revision_drift"))
            self.assertEqual(len(calls), 0)

        asyncio.run(run_case())

    def test_separate_authority_source_rejects_caller_supplied_token_spoofing(self) -> None:
        async def run_case() -> None:
            calls = []

            async def transport(account_id: str, namespace: str, token_gen: int) -> int:
                calls.append((account_id, namespace, token_gen))
                return 200

            dispatcher = HardenedDispatcher(self.store, transport)

            # Caller passes a token minted for acct-direct-2 while requesting acct-direct-1.
            foreign_token = PreparedToken(
                account_id="acct-direct-2",
                credential_generation=1,
                secret_material="SYN_SECRET_FOREIGN_999",
            )
            outcome_foreign = await dispatcher.renew_credit(
                "ns-alpha", "acct-direct-1", caller_supplied_token=foreign_token
            )
            self.assertFalse(outcome_foreign.dispatched)
            self.assertEqual(outcome_foreign.reason, "token_account_mismatch")

            # Caller passes a stale-generation token for acct-direct-1.
            self.store.rotate_credentials("acct-direct-1")  # generation is now 2
            stale_token = PreparedToken(
                account_id="acct-direct-1",
                credential_generation=1,
                secret_material="SYN_SECRET_STALE_111",
            )
            outcome_stale = await dispatcher.renew_credit(
                "ns-alpha", "acct-direct-1", caller_supplied_token=stale_token
            )
            self.assertFalse(outcome_stale.dispatched)
            self.assertEqual(outcome_stale.reason, "credential_generation_mismatch")
            self.assertEqual(len(calls), 0)

        asyncio.run(run_case())

    def test_positive_control_unchanged_authority_dispatches(self) -> None:
        async def run_case() -> None:
            calls = []

            async def transport(account_id: str, namespace: str, token_gen: int) -> int:
                calls.append((account_id, namespace, token_gen))
                return 200

            dispatcher = HardenedDispatcher(self.store, transport)
            outcome = await dispatcher.renew_credit("ns-alpha", "acct-direct-1")
            self.assertTrue(outcome.dispatched)
            self.assertEqual(outcome.dispatch_count, 1)
            self.assertFalse(outcome.replayed)
            self.assertTrue(outcome.succeeded)
            self.assertEqual(outcome.status_code, 200)
            self.assertEqual(outcome.reason, "ok")
            self.assertEqual(calls, [("acct-direct-1", "ns-alpha", 1)])

        asyncio.run(run_case())

    def test_401_replay_rechecks_authority_and_blocks_on_mid_refresh_revocation(self) -> None:
        async def run_case() -> None:
            # 1. Positive 401 replay when authority remains intact across token refresh.
            calls_ok = []

            async def transport_401_then_200(account_id: str, namespace: str, token_gen: int) -> int:
                calls_ok.append((account_id, namespace, token_gen))
                return 401 if len(calls_ok) == 1 else 200

            dispatcher_ok = HardenedDispatcher(self.store, transport_401_then_200)
            outcome_ok = await dispatcher_ok.renew_credit("ns-alpha", "acct-direct-1")
            self.assertTrue(outcome_ok.dispatched)
            self.assertEqual(outcome_ok.dispatch_count, 2)
            self.assertTrue(outcome_ok.replayed)
            self.assertTrue(outcome_ok.succeeded)
            self.assertEqual(outcome_ok.status_code, 200)
            self.assertEqual(calls_ok, [("acct-direct-1", "ns-alpha", 1), ("acct-direct-1", "ns-alpha", 2)])

            # 2. Negative 401 replay: consent revoked during 401 refresh blocks replay.
            # Initial dispatch happened (dispatch_count=1, dispatched=True), but replay is blocked (replayed=False).
            calls_revoked = []

            async def transport_always_401(account_id: str, namespace: str, token_gen: int) -> int:
                calls_revoked.append((account_id, namespace, token_gen))
                return 401

            async def revoke_on_refresh() -> None:
                self.store.set_credit_consent("acct-direct-1", False)

            dispatcher_rev = HardenedDispatcher(self.store, transport_always_401)
            outcome_rev = await dispatcher_rev.renew_credit(
                "ns-alpha", "acct-direct-1", on_401_refresh=revoke_on_refresh
            )
            self.assertTrue(outcome_rev.dispatched)
            self.assertEqual(outcome_rev.dispatch_count, 1)
            self.assertFalse(outcome_rev.replayed)
            self.assertFalse(outcome_rev.succeeded)
            self.assertEqual(outcome_rev.status_code, 401)
            self.assertEqual(outcome_rev.reason, "consent_revoked")
            self.assertEqual(len(calls_revoked), 1)

            # 3. Non-200 HTTP error (500) still records that initial dispatch occurred.
            self.store.set_credit_consent("acct-direct-1", True)
            calls_500 = []

            async def transport_500(account_id: str, namespace: str, token_gen: int) -> int:
                calls_500.append((account_id, namespace, token_gen))
                return 500

            dispatcher_500 = HardenedDispatcher(self.store, transport_500)
            outcome_500 = await dispatcher_500.renew_credit("ns-alpha", "acct-direct-1")
            self.assertTrue(outcome_500.dispatched)
            self.assertEqual(outcome_500.dispatch_count, 1)
            self.assertFalse(outcome_500.replayed)
            self.assertFalse(outcome_500.succeeded)
            self.assertEqual(outcome_500.status_code, 500)
            self.assertEqual(outcome_500.reason, "http_error")

        asyncio.run(run_case())

    def test_scoped_retry_hold_takes_max_applicable_excludes_sibling_and_caps_24h(self) -> None:
        scoped = {"model-selected": 900, "model-sibling": 1800}

        # Counterexample: unsafe early-return returns 600s account-wide hold, masking 900s selected scope.
        unsafe_advice = unsafe_compute_retry_advice(
            account_id="acct-direct-1",
            selected_scope="model-selected",
            account_hold_seconds=600,
            scoped_holds=scoped,
        )
        self.assertEqual(unsafe_advice.retry_after_seconds, 600)

        # Hardened policy: returns max(600, 900) = 900, and ignores model-sibling's 1800.
        advice = compute_retry_advice(
            account_id="acct-direct-1",
            selected_scope="model-selected",
            account_hold_seconds=600,
            scoped_holds=scoped,
        )
        self.assertEqual(advice.retry_after_seconds, 900)
        self.assertFalse(advice.can_spend)
        self.assertEqual(advice.selected_account_id, "acct-direct-1")

        # Account-wide hold larger than selected scope hold is preserved.
        advice_acct = compute_retry_advice(
            account_id="acct-direct-1",
            selected_scope="model-selected",
            account_hold_seconds=1200,
            scoped_holds={"model-selected": 300, "model-sibling": 1800},
        )
        self.assertEqual(advice_acct.retry_after_seconds, 1200)

        # 24-hour cap enforced.
        advice_capped = compute_retry_advice(
            account_id="acct-direct-1",
            selected_scope="model-selected",
            account_hold_seconds=172800,
            scoped_holds={"model-selected": 900},
        )
        self.assertEqual(advice_capped.retry_after_seconds, MAX_RETRY_AFTER_SECONDS)

        # Unknown credit evidence never authorizes spending or switches account.
        advice_unknown = compute_retry_advice(
            account_id="acct-direct-1",
            selected_scope="model-selected",
            account_hold_seconds=0,
            scoped_holds={},
            credit_evidence="unknown",
        )
        self.assertFalse(advice_unknown.can_spend)
        self.assertEqual(advice_unknown.reason, "credit_evidence_unknown")
        self.assertEqual(advice_unknown.selected_account_id, "acct-direct-1")

        # Available credit evidence without explicit spending_consent still denies spending.
        advice_no_consent = compute_retry_advice(
            account_id="acct-direct-1",
            selected_scope="model-selected",
            account_hold_seconds=0,
            scoped_holds={},
            credit_evidence="available",
            spending_consent=False,
        )
        self.assertFalse(advice_no_consent.can_spend)
        self.assertEqual(advice_no_consent.reason, "spending_consent_required")

        advice_with_consent = compute_retry_advice(
            account_id="acct-direct-1",
            selected_scope="model-selected",
            account_hold_seconds=0,
            scoped_holds={},
            credit_evidence="available",
            spending_consent=True,
        )
        self.assertTrue(advice_with_consent.can_spend)
        self.assertEqual(advice_with_consent.reason, "ok")

    def test_no_secrets_in_repr_outcomes_or_cli_json(self) -> None:
        token = PreparedToken(
            account_id="acct-direct-1",
            credential_generation=1,
            secret_material="SYN_SECRET_DO_NOT_LEAK_42",
        )
        self.assertNotIn("SYN_SECRET_DO_NOT_LEAK_42", repr(token))
        self.assertNotIn("SYN_SECRET_DO_NOT_LEAK_42", str(token))
        self.assertNotIn("SYN_SECRET_DO_NOT_LEAK_42", json.dumps(token.safe_dict()))

        lab_root = Path(__file__).resolve().parent.parent
        proc = subprocess.run(
            [sys.executable, "-m", "auth_boundary_lab"],
            cwd=str(lab_root),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        self.assertNotIn("SYN_SECRET_", proc.stdout)
        self.assertNotIn("SYN_SECRET_", proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["all_invariants_passed"])

        # Verify CLI exits non-zero when asserting the unhardened counterexample is safe.
        proc_fail = subprocess.run(
            [sys.executable, "-m", "auth_boundary_lab", "--assert-unhardened-safe"],
            cwd=str(lab_root),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(proc_fail.returncode, 0)


if __name__ == "__main__":
    unittest.main()
