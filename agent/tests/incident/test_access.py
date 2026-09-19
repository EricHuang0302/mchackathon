"""Incident-scoped grants and the role capability matrix.

These are the service-side authorization cases for PostgreSQL-backed grants.
Database credentials never establish the caller's incident scope.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.services.incident import ServiceError
from app.services.incident.access import (
    MANAGE_SHARES,
    READ_MIST,
    READ_SCENE_SNAPSHOT,
    READ_TIMELINE,
    ROLE_AED_RUNNER,
    ROLE_AMBULANCE_GREETER,
    ROLE_CAPABILITIES,
    ROLE_EMS_VIEWER,
    ROLE_PRIMARY,
    WRITE_INCIDENT_EVENTS,
    WRITE_OWN_HELPER_UPDATES,
    AccessGrant,
    InMemoryGrantStore,
    resolve_principal,
)

from .conftest import BASE_TIME, INCIDENT_ID, OWNER_UID

OTHER_INCIDENT_ID = "33333333-4444-4555-8666-777777777777"


def grant(
    uid: str,
    scope: str,
    *,
    incident_id: str = INCIDENT_ID,
    helper_id: str | None = None,
    expires_in: float = 3600,
    revoked_at=None,
) -> AccessGrant:
    return AccessGrant(
        grant_id=f"grant-{uid}",
        incident_id=incident_id,
        uid=uid,
        scope=scope,
        helper_id=helper_id,
        expires_at=BASE_TIME + timedelta(seconds=expires_in),
        revoked_at=revoked_at,
    )


def resolve(store: InMemoryGrantStore, uid: str, *, at=BASE_TIME, incident_id=INCIDENT_ID):
    return resolve_principal(
        incident_id=incident_id,
        owner_uid=OWNER_UID,
        uid=uid,
        now=at,
        grants=store,
    )


# -- capability matrix ------------------------------------------------------


def test_an_aed_runner_has_no_clinical_capability() -> None:
    capabilities = ROLE_CAPABILITIES[ROLE_AED_RUNNER]
    assert READ_SCENE_SNAPSHOT not in capabilities
    assert READ_MIST not in capabilities
    assert READ_TIMELINE not in capabilities
    assert WRITE_INCIDENT_EVENTS not in capabilities
    assert WRITE_OWN_HELPER_UPDATES in capabilities


def test_an_ambulance_greeter_reads_the_snapshot_but_not_the_timeline() -> None:
    capabilities = ROLE_CAPABILITIES[ROLE_AMBULANCE_GREETER]
    assert READ_SCENE_SNAPSHOT in capabilities
    assert READ_TIMELINE not in capabilities
    assert READ_MIST not in capabilities


def test_an_ems_viewer_is_read_only() -> None:
    capabilities = ROLE_CAPABILITIES[ROLE_EMS_VIEWER]
    assert {READ_SCENE_SNAPSHOT, READ_MIST, READ_TIMELINE} <= capabilities
    assert not {c for c in capabilities if c.startswith("write:")}
    assert MANAGE_SHARES not in capabilities


def test_no_grant_role_can_manage_shares_except_the_primary() -> None:
    for role, capabilities in ROLE_CAPABILITIES.items():
        assert (MANAGE_SHARES in capabilities) is (role == ROLE_PRIMARY)


# -- grant resolution -------------------------------------------------------


def test_the_owner_is_the_primary_without_needing_a_grant() -> None:
    principal = resolve(InMemoryGrantStore(), OWNER_UID)
    assert principal.role == ROLE_PRIMARY
    assert principal.capabilities == ROLE_CAPABILITIES[ROLE_PRIMARY]


def test_a_uid_without_a_grant_is_refused() -> None:
    with pytest.raises(ServiceError) as excinfo:
        resolve(InMemoryGrantStore(), "stranger-uid")
    assert (excinfo.value.code, excinfo.value.reason) == (
        "unauthorized",
        "no_grant_for_incident",
    )


def test_a_grant_for_another_incident_does_not_open_this_one() -> None:
    store = InMemoryGrantStore([grant("ems-uid", ROLE_EMS_VIEWER, incident_id=OTHER_INCIDENT_ID)])
    with pytest.raises(ServiceError) as excinfo:
        resolve(store, "ems-uid")
    assert excinfo.value.reason == "no_grant_for_incident"

    # The same grant does resolve for the incident it was issued for.
    principal = resolve(store, "ems-uid", incident_id=OTHER_INCIDENT_ID)
    assert principal.role == ROLE_EMS_VIEWER


def test_an_expired_grant_is_refused_at_expiry(  ) -> None:
    store = InMemoryGrantStore([grant("ems-uid", ROLE_EMS_VIEWER, expires_in=600)])

    assert resolve(store, "ems-uid", at=BASE_TIME + timedelta(seconds=599)).role == ROLE_EMS_VIEWER

    with pytest.raises(ServiceError) as excinfo:
        resolve(store, "ems-uid", at=BASE_TIME + timedelta(seconds=600))
    assert (excinfo.value.code, excinfo.value.reason) == ("expired", "grant_expired")


def test_revocation_stops_future_access() -> None:
    store = InMemoryGrantStore([grant("greeter-uid", ROLE_AMBULANCE_GREETER, helper_id="greeter-1")])
    assert resolve(store, "greeter-uid").role == ROLE_AMBULANCE_GREETER

    store.revoke(INCIDENT_ID, "greeter-uid", BASE_TIME + timedelta(seconds=30))

    assert resolve(store, "greeter-uid", at=BASE_TIME).role == ROLE_AMBULANCE_GREETER
    with pytest.raises(ServiceError) as excinfo:
        resolve(store, "greeter-uid", at=BASE_TIME + timedelta(seconds=30))
    assert (excinfo.value.code, excinfo.value.reason) == ("expired", "grant_revoked")


def test_a_helper_grant_carries_its_helper_id() -> None:
    store = InMemoryGrantStore([grant("runner-uid", ROLE_AED_RUNNER, helper_id="runner-1")])
    principal = resolve(store, "runner-uid")
    assert principal.helper_id == "runner-1"
    assert principal.grant_id == "grant-runner-uid"


def test_a_helper_grant_without_a_helper_id_is_rejected() -> None:
    with pytest.raises(ServiceError) as excinfo:
        InMemoryGrantStore([grant("runner-uid", ROLE_AED_RUNNER)])
    assert excinfo.value.reason == "helper_grant_requires_helper_id"


def test_an_unknown_scope_is_rejected() -> None:
    with pytest.raises(ServiceError) as excinfo:
        InMemoryGrantStore([grant("someone", "auditor")])
    assert excinfo.value.reason == "unknown_scope"


def test_require_raises_for_a_missing_capability() -> None:
    store = InMemoryGrantStore([grant("runner-uid", ROLE_AED_RUNNER, helper_id="runner-1")])
    principal = resolve(store, "runner-uid")
    principal.require(WRITE_OWN_HELPER_UPDATES)
    with pytest.raises(ServiceError) as excinfo:
        principal.require(READ_TIMELINE)
    assert excinfo.value.code == "unauthorized"
