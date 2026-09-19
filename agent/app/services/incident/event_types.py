"""Allowlisted event types, observation keys, sources and confirmation levels.

The event-type list reproduces ``docs/sdd.md`` section 9 exactly. Anything else
is rejected as ``invalid_input``; this service never stores an event type it
does not understand, because an unknown type cannot be projected, sanitized for
a handoff viewer, or retained under a known policy.
"""

from __future__ import annotations

from typing import Final

MODE_CHANGED: Final = "mode.changed"
CALL_REPORTED: Final = "call.reported"
ACTION_REPORTED: Final = "action.reported"
EVENT_CORRECTED: Final = "event.corrected"
OBSERVATION_PROPOSED: Final = "observation.proposed"
OBSERVATION_CONFIRMED: Final = "observation.confirmed"
DECISION_COMMITTED: Final = "decision.committed"
COMMAND_ISSUED: Final = "command.issued"
COMMAND_ACKNOWLEDGED: Final = "command.acknowledged"
TIMER_ELAPSED: Final = "timer.elapsed"
HELPER_UPDATED: Final = "helper.updated"
INCIDENT_STATE_UPDATED: Final = "incident_state.updated"
SCENE_SNAPSHOT_UPDATED: Final = "scene_snapshot.updated"

EVENT_TYPES: Final = (
    MODE_CHANGED,
    CALL_REPORTED,
    ACTION_REPORTED,
    EVENT_CORRECTED,
    OBSERVATION_PROPOSED,
    OBSERVATION_CONFIRMED,
    DECISION_COMMITTED,
    COMMAND_ISSUED,
    COMMAND_ACKNOWLEDGED,
    TIMER_ELAPSED,
    HELPER_UPDATED,
    INCIDENT_STATE_UPDATED,
    SCENE_SNAPSHOT_UPDATED,
)
EVENT_TYPE_SET: Final = frozenset(EVENT_TYPES)

#: Events that assert a new authoritative revision rather than merely reporting
#: something that happened. These are the only types subject to monotonic
#: revision checks; a plain report produced offline legitimately carries an old
#: revision and must not be rejected for it.
AUTHORITATIVE_EVENT_TYPES: Final = frozenset(
    {MODE_CHANGED, INCIDENT_STATE_UPDATED, DECISION_COMMITTED}
)

#: Types a client may submit. The backend projects ``scene_snapshot.updated``
#: itself, so accepting one from a client would let a client write a canonical
#: projection.
CLIENT_SUBMITTABLE_EVENT_TYPES: Final = EVENT_TYPE_SET - {SCENE_SNAPSHOT_UPDATED}

INTERACTION_MODES: Final = ("call_119", "on_call", "voice_guidance", "handover")
INTERACTION_MODE_SET: Final = frozenset(INTERACTION_MODES)

INCIDENT_STATUSES: Final = ("active", "handed_over", "closed")
INCIDENT_STATUS_SET: Final = frozenset(INCIDENT_STATUSES)

CONNECTION_MODES: Final = ("online", "offline", "resyncing")

#: Where a fact came from. A model or camera proposal can never confirm itself,
#: which is enforced by :data:`CONFIRMING_SOURCES`.
SOURCES: Final = (
    "user_report",
    "button",
    "camera_proposal",
    "model_proposal",
    "geocoder",
    "device",
    "helper_report",
    "rule_engine",
)
SOURCE_SET: Final = frozenset(SOURCES)

#: Only a human report may raise a field to ``confirmed``.
CONFIRMING_SOURCES: Final = frozenset({"user_report", "button", "helper_report"})

#: Ordered weakest to strongest. A weaker fact never replaces a stronger one.
CONFIRMATION_LEVELS: Final = ("unknown", "proposed", "reported", "confirmed")
CONFIRMATION_RANK: Final = {name: rank for rank, name in enumerate(CONFIRMATION_LEVELS)}

LOCATION: Final = "location"
CIRCUMSTANCES: Final = "circumstances"
PATIENT_CONDITION: Final = "patientCondition"
PEOPLE_PRESENT: Final = "peoplePresent"
HAZARDS: Final = "hazards"

#: Allowlisted observation keys and the scene-snapshot section each belongs to.
#: The order of this mapping fixes the field order of a rendered snapshot, so
#: the cheat sheet, greeter and EMS views can show identical fields.
OBSERVATION_KEYS: Final = {
    "location.coordinates": LOCATION,
    "location.accuracyMeters": LOCATION,
    "location.address": LOCATION,
    "location.landmark": LOCATION,
    "location.floor": LOCATION,
    "location.entrance": LOCATION,
    "location.accessNotes": LOCATION,
    "circumstances.whatHappened": CIRCUMSTANCES,
    "circumstances.occurredAt": CIRCUMSTANCES,
    "circumstances.witnessed": CIRCUMSTANCES,
    "patient.responsive": PATIENT_CONDITION,
    "patient.breathing": PATIENT_CONDITION,
    "patient.breathingNormal": PATIENT_CONDITION,
    "patient.pulse": PATIENT_CONDITION,
    "patient.airway": PATIENT_CONDITION,
    "patient.bleeding": PATIENT_CONDITION,
    "patient.skinColor": PATIENT_CONDITION,
    "patient.ageRange": PATIENT_CONDITION,
    "patient.chiefComplaint": PATIENT_CONDITION,
    "patient.injuries": PATIENT_CONDITION,
    "people.patientCount": PEOPLE_PRESENT,
    "people.bystanderCount": PEOPLE_PRESENT,
    "people.helperSummary": PEOPLE_PRESENT,
    "hazards.present": HAZARDS,
    "hazards.traffic": HAZARDS,
    "hazards.fire": HAZARDS,
    "hazards.standingWater": HAZARDS,
    "hazards.crowd": HAZARDS,
    "hazards.description": HAZARDS,
}

SNAPSHOT_SECTIONS: Final = (
    LOCATION,
    CIRCUMSTANCES,
    PATIENT_CONDITION,
    PEOPLE_PRESENT,
    HAZARDS,
)

#: Keys whose section membership is fixed above, grouped for the projector.
SECTION_KEYS: Final = {
    section: tuple(key for key, value in OBSERVATION_KEYS.items() if value == section)
    for section in SNAPSHOT_SECTIONS
}

#: MIST derivation. Every MIST entry is backed by the observation keys listed
#: here; nothing is inferred from free text.
MIST_MECHANISM_KEYS: Final = (
    "circumstances.whatHappened",
    "circumstances.occurredAt",
    "circumstances.witnessed",
)
MIST_INJURY_KEYS: Final = (
    "patient.injuries",
    "patient.chiefComplaint",
    "patient.bleeding",
)
MIST_SIGN_KEYS: Final = (
    "patient.responsive",
    "patient.breathing",
    "patient.pulse",
    "patient.airway",
    "patient.skinColor",
)

#: Boolean observations use ``True``, ``False`` or the literal string
#: ``"unknown"``. A missing observation is also unknown; it is never ``False``.
UNKNOWN: Final = "unknown"
