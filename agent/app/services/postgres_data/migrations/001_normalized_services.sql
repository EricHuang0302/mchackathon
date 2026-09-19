CREATE TABLE incidents (
    incident_id text PRIMARY KEY,
    owner_uid text NOT NULL,
    primary_client_id text NOT NULL,
    rule_version text NOT NULL,
    status text NOT NULL CHECK (status IN ('active', 'handed_over', 'closed')),
    interaction_mode text NOT NULL CHECK (
        interaction_mode IN ('call_119', 'on_call', 'voice_guidance', 'handover')
    ),
    mode_revision integer NOT NULL CHECK (mode_revision >= 0),
    clinical_state text,
    guidance_paused boolean NOT NULL,
    state_revision integer NOT NULL CHECK (state_revision >= 0),
    authority_epoch integer NOT NULL CHECK (authority_epoch >= 0),
    call_status jsonb NOT NULL DEFAULT '{}'::jsonb,
    acknowledged_client_sequences jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    CHECK (updated_at >= created_at),
    CHECK (expires_at > created_at)
);

CREATE INDEX incidents_owner_idx ON incidents (owner_uid, updated_at DESC);
CREATE INDEX incidents_expiry_idx ON incidents (expires_at);

CREATE TABLE incident_events (
    incident_id text NOT NULL REFERENCES incidents (incident_id) ON DELETE CASCADE,
    event_id text NOT NULL,
    event_type text NOT NULL,
    detail jsonb NOT NULL,
    source text NOT NULL,
    actor_id text NOT NULL,
    actor_role text NOT NULL,
    client_id text NOT NULL,
    client_instance_id text NOT NULL,
    client_sequence integer NOT NULL CHECK (client_sequence > 0),
    client_time timestamptz NOT NULL,
    client_time_uncertain boolean NOT NULL DEFAULT false,
    server_time timestamptz NOT NULL,
    server_sequence integer NOT NULL CHECK (server_sequence > 0),
    authority_epoch integer NOT NULL CHECK (authority_epoch >= 0),
    state_revision integer NOT NULL CHECK (state_revision >= 0),
    mode_revision integer NOT NULL CHECK (mode_revision >= 0),
    rule_version text NOT NULL,
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (incident_id, event_id),
    UNIQUE (incident_id, server_sequence),
    UNIQUE (incident_id, client_id, client_instance_id, client_sequence)
);

CREATE INDEX incident_events_timeline_idx
    ON incident_events (incident_id, server_sequence);
CREATE INDEX incident_events_projection_idx
    ON incident_events (incident_id, client_time, client_id, client_sequence, event_id);
CREATE INDEX incident_events_expiry_idx ON incident_events (expires_at);

CREATE TABLE scene_snapshots (
    incident_id text PRIMARY KEY REFERENCES incidents (incident_id) ON DELETE CASCADE,
    snapshot_revision integer NOT NULL CHECK (snapshot_revision >= 0),
    generated_through_revision integer NOT NULL CHECK (generated_through_revision >= 0),
    generated_through_sequence integer NOT NULL CHECK (generated_through_sequence >= 0),
    generated_through_event_id text,
    payload jsonb NOT NULL,
    updated_at timestamptz,
    expires_at timestamptz NOT NULL
);

CREATE INDEX scene_snapshots_expiry_idx ON scene_snapshots (expires_at);

CREATE TABLE access_invitations (
    invitation_id text PRIMARY KEY,
    incident_id text NOT NULL REFERENCES incidents (incident_id) ON DELETE CASCADE,
    secret_hash text NOT NULL UNIQUE CHECK (length(secret_hash) = 64),
    encrypted_secret bytea NOT NULL,
    scope text NOT NULL CHECK (
        scope IN ('aed_runner', 'ambulance_greeter', 'ems_viewer')
    ),
    helper_id text,
    idempotency_key text NOT NULL,
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    redeemed_at timestamptz,
    redeemed_by_uid text,
    revoked_at timestamptz,
    UNIQUE (incident_id, idempotency_key),
    CHECK (expires_at > created_at),
    CHECK (
        scope NOT IN ('aed_runner', 'ambulance_greeter') OR helper_id IS NOT NULL
    ),
    CHECK ((redeemed_at IS NULL) = (redeemed_by_uid IS NULL))
);

CREATE INDEX access_invitations_lookup_idx
    ON access_invitations (secret_hash) WHERE redeemed_at IS NULL AND revoked_at IS NULL;
CREATE INDEX access_invitations_expiry_idx ON access_invitations (expires_at);

CREATE TABLE access_grants (
    grant_id text PRIMARY KEY,
    incident_id text NOT NULL REFERENCES incidents (incident_id) ON DELETE CASCADE,
    uid text NOT NULL,
    scope text NOT NULL CHECK (
        scope IN ('aed_runner', 'ambulance_greeter', 'ems_viewer')
    ),
    helper_id text,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    UNIQUE (incident_id, uid),
    CHECK (
        scope NOT IN ('aed_runner', 'ambulance_greeter') OR helper_id IS NOT NULL
    )
);

CREATE INDEX access_grants_authorization_idx
    ON access_grants (incident_id, uid, expires_at) WHERE revoked_at IS NULL;
CREATE INDEX access_grants_expiry_idx ON access_grants (expires_at);

CREATE TABLE aed_datasets (
    dataset_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_system text NOT NULL,
    source_url text NOT NULL,
    dataset_version text NOT NULL,
    retrieved_at timestamptz NOT NULL,
    imported_at timestamptz NOT NULL,
    synthetic boolean NOT NULL,
    license_note text NOT NULL,
    active boolean NOT NULL DEFAULT false,
    expires_at timestamptz,
    UNIQUE (source_system, dataset_version),
    CHECK (expires_at IS NULL OR expires_at > imported_at)
);

CREATE UNIQUE INDEX aed_datasets_one_active_source_idx
    ON aed_datasets (source_system) WHERE active;
CREATE INDEX aed_datasets_expiry_idx ON aed_datasets (expires_at) WHERE expires_at IS NOT NULL;

CREATE TABLE aed_locations (
    dataset_id bigint NOT NULL REFERENCES aed_datasets (dataset_id) ON DELETE CASCADE,
    stable_id text NOT NULL,
    source_id text NOT NULL,
    source_location_id text,
    source_system text NOT NULL,
    name text NOT NULL,
    latitude double precision NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude double precision NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    address text NOT NULL,
    opening_hours jsonb NOT NULL,
    access_notes text,
    access_notes_known boolean NOT NULL,
    source_url text NOT NULL,
    source_updated_at timestamptz,
    ingested_at timestamptz NOT NULL,
    dataset_version text NOT NULL,
    data_quality_notes jsonb NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY (dataset_id, stable_id),
    UNIQUE (dataset_id, source_id)
);

CREATE INDEX aed_locations_coordinate_idx
    ON aed_locations (dataset_id, latitude, longitude);

CREATE TABLE aed_assignments (
    incident_id text PRIMARY KEY REFERENCES incidents (incident_id) ON DELETE CASCADE,
    helper_id text NOT NULL,
    aed_id text,
    assignment_revision integer NOT NULL CHECK (assignment_revision > 0),
    assigned_at timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN ('assigned', 'no_candidate')),
    candidate jsonb,
    estimate jsonb,
    previous_aed_id text,
    expires_at timestamptz NOT NULL,
    CHECK ((status = 'assigned') = (aed_id IS NOT NULL))
);

CREATE INDEX aed_assignments_helper_idx ON aed_assignments (helper_id);
CREATE INDEX aed_assignments_expiry_idx ON aed_assignments (expires_at);

CREATE TABLE aed_assignment_exclusions (
    incident_id text NOT NULL REFERENCES incidents (incident_id) ON DELETE CASCADE,
    aed_id text NOT NULL,
    excluded_at timestamptz NOT NULL,
    PRIMARY KEY (incident_id, aed_id)
);

CREATE TABLE aed_unavailability_reports (
    incident_id text NOT NULL REFERENCES incidents (incident_id) ON DELETE CASCADE,
    report_id text NOT NULL,
    helper_id text,
    aed_id text,
    reason_code text,
    reported_at timestamptz,
    expected_assignment_revision integer CHECK (expected_assignment_revision >= 0),
    result jsonb NOT NULL,
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (incident_id, report_id)
);

CREATE INDEX aed_unavailability_reports_expiry_idx
    ON aed_unavailability_reports (expires_at);
