"""Synthetic educational model for async authorization boundaries and scoped retry holds."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Mapping, Optional, Tuple

MAX_RETRY_AFTER_SECONDS = 86400

AsyncHook = Optional[Callable[[], Awaitable[None]]]
SyntheticTransport = Callable[[str, str, int], Awaitable[int]]


@dataclass
class AccountRecord:
    account_id: str
    credit_consent: bool = True
    account_enabled: bool = True
    provider_enabled: bool = True
    credential_generation: int = 1
    consent_revision: int = 1
    provider_revision: int = 1
    account_revision: int = 1


@dataclass(frozen=True)
class AuthoritySnapshot:
    namespace: str
    account_id: str
    credential_generation: int
    binding_revision: int
    consent_revision: int
    provider_revision: int
    account_revision: int


class PreparedToken:
    """Synthetic token whose secret material is omitted from repr/str/safe_dict."""

    __slots__ = ("account_id", "credential_generation", "_secret_material")

    def __init__(self, account_id: str, credential_generation: int, secret_material: str) -> None:
        self.account_id = account_id
        self.credential_generation = credential_generation
        self._secret_material = secret_material

    def safe_dict(self) -> Dict[str, object]:
        return {
            "account_id": self.account_id,
            "credential_generation": self.credential_generation,
            "secret": "[REDACTED]",
        }

    def __repr__(self) -> str:
        return (
            f"PreparedToken(account_id={self.account_id!r}, "
            f"credential_generation={self.credential_generation}, secret='[REDACTED]')"
        )

    __str__ = __repr__


@dataclass(frozen=True)
class DispatchOutcome:
    dispatched: bool
    dispatch_count: int
    replayed: bool
    succeeded: bool
    status_code: Optional[int]
    reason: str
    account_id: str
    namespace: str

    def as_dict(self) -> Dict[str, object]:
        return {
            "dispatched": self.dispatched,
            "dispatch_count": self.dispatch_count,
            "replayed": self.replayed,
            "succeeded": self.succeeded,
            "status_code": self.status_code,
            "reason": self.reason,
            "account_id": self.account_id,
            "namespace": self.namespace,
        }


@dataclass(frozen=True)
class RetryAdvice:
    selected_account_id: str
    selected_scope: str
    retry_after_seconds: int
    can_spend: bool
    reason: str

    def as_dict(self) -> Dict[str, object]:
        return {
            "selected_account_id": self.selected_account_id,
            "selected_scope": self.selected_scope,
            "retry_after_seconds": self.retry_after_seconds,
            "can_spend": self.can_spend,
            "reason": self.reason,
        }


class AuthorityStore:
    """Authoritative live store kept separate from caller-supplied tokens."""

    def __init__(self) -> None:
        self._accounts: Dict[str, AccountRecord] = {}
        self._account_history: Dict[str, AccountRecord] = {}
        self._namespace_bindings: Dict[str, Optional[str]] = {}
        self._binding_revisions: Dict[str, int] = {}

    def register_account(
        self,
        account_id: str,
        *,
        credit_consent: bool = True,
        account_enabled: bool = True,
        provider_enabled: bool = True,
    ) -> AccountRecord:
        prior = self._accounts.get(account_id) or self._account_history.get(account_id)
        if prior is None:
            record = AccountRecord(
                account_id=account_id,
                credit_consent=credit_consent,
                account_enabled=account_enabled,
                provider_enabled=provider_enabled,
            )
        else:
            record = AccountRecord(
                account_id=account_id,
                credit_consent=credit_consent,
                account_enabled=account_enabled,
                provider_enabled=provider_enabled,
                credential_generation=prior.credential_generation + 1,
                consent_revision=prior.consent_revision + 1,
                provider_revision=prior.provider_revision + 1,
                account_revision=prior.account_revision + 1,
            )
        self._accounts[account_id] = record
        self._account_history[account_id] = record
        return record

    def remove_account(self, account_id: str) -> None:
        acct = self._accounts.pop(account_id, None)
        if acct is not None:
            acct.account_enabled = False
            acct.account_revision += 1
            self._account_history[account_id] = acct

    def bind_namespace(self, namespace: str, account_id: Optional[str]) -> None:
        self._namespace_bindings[namespace] = account_id
        self._binding_revisions[namespace] = self._binding_revisions.get(namespace, 0) + 1

    def set_credit_consent(self, account_id: str, consented: bool) -> None:
        acct = self._accounts[account_id]
        acct.credit_consent = consented
        acct.consent_revision += 1

    def set_account_enabled(self, account_id: str, enabled: bool) -> None:
        acct = self._accounts[account_id]
        acct.account_enabled = enabled
        acct.account_revision += 1

    def set_provider_enabled(self, account_id: str, enabled: bool) -> None:
        acct = self._accounts[account_id]
        acct.provider_enabled = enabled
        acct.provider_revision += 1

    def rotate_credentials(self, account_id: str) -> int:
        acct = self._accounts[account_id]
        acct.credential_generation += 1
        return acct.credential_generation

    def mint_synthetic_token(self, account_id: str) -> PreparedToken:
        acct = self._accounts[account_id]
        return PreparedToken(
            account_id=account_id,
            credential_generation=acct.credential_generation,
            secret_material=f"SYN_SECRET_{account_id}_GEN_{acct.credential_generation}",
        )

    def check_live_authority(self, namespace: str, account_id: str) -> Tuple[bool, str]:
        acct = self._accounts.get(account_id)
        if acct is None or not acct.account_enabled:
            return False, "account_disabled"
        if not acct.provider_enabled:
            return False, "provider_disabled"
        if self._namespace_bindings.get(namespace) != account_id:
            return False, "namespace_binding_mismatch"
        if not acct.credit_consent:
            return False, "consent_revoked"
        return True, "ok"

    def capture_snapshot(self, namespace: str, account_id: str) -> AuthoritySnapshot:
        acct = self._accounts[account_id]
        return AuthoritySnapshot(
            namespace=namespace,
            account_id=account_id,
            credential_generation=acct.credential_generation,
            binding_revision=self._binding_revisions.get(namespace, 0),
            consent_revision=acct.consent_revision,
            provider_revision=acct.provider_revision,
            account_revision=acct.account_revision,
        )

    def verify_snapshot_and_token(
        self, snapshot: AuthoritySnapshot, token: PreparedToken
    ) -> Tuple[bool, str]:
        if token.account_id != snapshot.account_id:
            return False, "token_account_mismatch"
        live_ok, live_reason = self.check_live_authority(snapshot.namespace, snapshot.account_id)
        if not live_ok:
            return False, live_reason
        acct = self._accounts[snapshot.account_id]
        if (
            acct.credential_generation != snapshot.credential_generation
            or token.credential_generation != acct.credential_generation
        ):
            return False, "credential_generation_mismatch"
        if self._binding_revisions.get(snapshot.namespace, 0) != snapshot.binding_revision:
            return False, "binding_revision_drift"
        if acct.consent_revision != snapshot.consent_revision:
            return False, "consent_revision_drift"
        if acct.provider_revision != snapshot.provider_revision:
            return False, "provider_revision_drift"
        if acct.account_revision != snapshot.account_revision:
            return False, "account_revision_drift"
        return True, "ok"


class UnsafeCheckOnceDispatcher:
    """Deliberately unsafe offline counterexample: checks authority only before async wait."""

    def __init__(self, store: AuthorityStore, transport: SyntheticTransport) -> None:
        self.store = store
        self.transport = transport

    async def renew_credit(
        self,
        namespace: str,
        account_id: str,
        *,
        on_token_prep: AsyncHook = None,
    ) -> DispatchOutcome:
        ok, reason = self.store.check_live_authority(namespace, account_id)
        if not ok:
            return DispatchOutcome(False, 0, False, False, None, reason, account_id, namespace)
        token = self.store.mint_synthetic_token(account_id)
        await asyncio.sleep(0)
        if on_token_prep is not None:
            await on_token_prep()
        # UNSAFE COUNTEREXAMPLE: dispatches after async suspension without re-verifying authority.
        status = await self.transport(account_id, namespace, token.credential_generation)
        return DispatchOutcome(
            True, 1, False, status == 200, status, "unsafe_dispatched_without_recheck", account_id, namespace
        )


class HardenedDispatcher:
    """Hardened dispatcher: re-verifies live authority, snapshot revisions, and token binding."""

    def __init__(self, store: AuthorityStore, transport: SyntheticTransport) -> None:
        self.store = store
        self.transport = transport

    async def renew_credit(
        self,
        namespace: str,
        account_id: str,
        *,
        on_token_prep: AsyncHook = None,
        on_401_refresh: AsyncHook = None,
        caller_supplied_token: Optional[PreparedToken] = None,
    ) -> DispatchOutcome:
        ok, reason = self.store.check_live_authority(namespace, account_id)
        if not ok:
            return DispatchOutcome(False, 0, False, False, None, reason, account_id, namespace)

        snapshot = self.store.capture_snapshot(namespace, account_id)
        token = caller_supplied_token or self.store.mint_synthetic_token(account_id)

        await asyncio.sleep(0)
        if on_token_prep is not None:
            await on_token_prep()

        ok, reason = self.store.verify_snapshot_and_token(snapshot, token)
        if not ok:
            return DispatchOutcome(False, 0, False, False, None, reason, account_id, namespace)

        status = await self.transport(account_id, namespace, token.credential_generation)
        if status != 401:
            return DispatchOutcome(
                True,
                1,
                False,
                status == 200,
                status,
                "ok" if status == 200 else "http_error",
                account_id,
                namespace,
            )

        # 401 refresh boundary: verify authority before rotating/minting and again after refresh wait.
        ok, reason = self.store.verify_snapshot_and_token(snapshot, token)
        if not ok:
            return DispatchOutcome(True, 1, False, False, 401, reason, account_id, namespace)

        self.store.rotate_credentials(account_id)
        refresh_snapshot = self.store.capture_snapshot(namespace, account_id)
        refreshed_token = self.store.mint_synthetic_token(account_id)

        await asyncio.sleep(0)
        if on_401_refresh is not None:
            await on_401_refresh()

        ok, reason = self.store.verify_snapshot_and_token(refresh_snapshot, refreshed_token)
        if not ok:
            return DispatchOutcome(True, 1, False, False, 401, reason, account_id, namespace)

        replay_status = await self.transport(account_id, namespace, refreshed_token.credential_generation)
        return DispatchOutcome(
            True,
            2,
            True,
            replay_status == 200,
            replay_status,
            "ok" if replay_status == 200 else "http_error",
            account_id,
            namespace,
        )


def unsafe_compute_retry_advice(
    account_id: str,
    selected_scope: str,
    account_hold_seconds: int,
    scoped_holds: Mapping[str, int],
) -> RetryAdvice:
    """Deliberately unsafe counterexample: early account-wide return masks longer selected-scope hold."""
    if account_hold_seconds > 0:
        hold = min(MAX_RETRY_AFTER_SECONDS, account_hold_seconds)
    else:
        hold = min(MAX_RETRY_AFTER_SECONDS, max(0, int(scoped_holds.get(selected_scope, 0))))
    return RetryAdvice(account_id, selected_scope, hold, hold == 0, "unsafe_early_account_hold")


def compute_retry_advice(
    account_id: str,
    selected_scope: str,
    account_hold_seconds: int,
    scoped_holds: Mapping[str, int],
    credit_evidence: str = "denied",
    spending_consent: bool = False,
) -> RetryAdvice:
    """Hardened retry policy: retains max(account_hold, selected_scope_hold), excludes sibling scopes."""
    acct_hold = max(0, int(account_hold_seconds))
    selected_hold = max(0, int(scoped_holds.get(selected_scope, 0)))
    effective_hold = min(MAX_RETRY_AFTER_SECONDS, max(acct_hold, selected_hold))

    if credit_evidence == "unknown":
        return RetryAdvice(account_id, selected_scope, effective_hold, False, "credit_evidence_unknown")
    if effective_hold > 0:
        return RetryAdvice(account_id, selected_scope, effective_hold, False, "retry_hold_active")
    if credit_evidence != "available":
        return RetryAdvice(account_id, selected_scope, 0, False, "credit_denied")
    if not spending_consent:
        return RetryAdvice(account_id, selected_scope, 0, False, "spending_consent_required")
    return RetryAdvice(account_id, selected_scope, 0, True, "ok")
