"""Incident events, projections, access grants, and reconciliation services."""

from .access import (
    AccessGrant,
    GrantStore,
    InMemoryGrantStore,
    Principal,
    ROLE_AED_RUNNER,
    ROLE_AMBULANCE_GREETER,
    ROLE_CAPABILITIES,
    ROLE_EMS_VIEWER,
    ROLE_PRIMARY,
    resolve_principal,
)
from .clock import Clock, FixedClock, ManualClock, iso, utc
from .errors import RetentionPolicy, ServiceError
from .event_store import (
    DuplicateEventError,
    EventStore,
    IncidentStore,
    InMemoryEventStore,
    InMemoryIncidentStore,
)
from .handoff import build_handoff_timeline, project_mist
from .ingestion import IncidentEventService, ordered_events, parse_envelope
from .models import (
    Acknowledgement,
    EventBatchResult,
    EventConflict,
    EventEnvelope,
    IncidentRecord,
    MistReport,
    Provenance,
    ReportedAction,
    SceneSnapshot,
    SnapshotField,
    StoredEvent,
    TimelineEntry,
    TimelinePage,
)
from .reconciliation import ReconciliationResult, ReconciliationService, ResyncRequest
from .read_models import HandoffReadModel, IncidentReadModelService
from .scene_snapshot import FreshnessPolicy, project_scene_snapshot

__all__ = [
    "AccessGrant",
    "Acknowledgement",
    "Clock",
    "DuplicateEventError",
    "EventBatchResult",
    "EventConflict",
    "EventEnvelope",
    "EventStore",
    "FixedClock",
    "FreshnessPolicy",
    "GrantStore",
    "HandoffReadModel",
    "IncidentEventService",
    "IncidentRecord",
    "IncidentReadModelService",
    "IncidentStore",
    "InMemoryEventStore",
    "InMemoryGrantStore",
    "InMemoryIncidentStore",
    "ManualClock",
    "MistReport",
    "Principal",
    "Provenance",
    "ROLE_AED_RUNNER",
    "ROLE_AMBULANCE_GREETER",
    "ROLE_CAPABILITIES",
    "ROLE_EMS_VIEWER",
    "ROLE_PRIMARY",
    "ReconciliationResult",
    "ReconciliationService",
    "ReportedAction",
    "RetentionPolicy",
    "ResyncRequest",
    "SceneSnapshot",
    "ServiceError",
    "SnapshotField",
    "StoredEvent",
    "TimelineEntry",
    "TimelinePage",
    "build_handoff_timeline",
    "iso",
    "ordered_events",
    "parse_envelope",
    "project_mist",
    "project_scene_snapshot",
    "resolve_principal",
    "utc",
]
