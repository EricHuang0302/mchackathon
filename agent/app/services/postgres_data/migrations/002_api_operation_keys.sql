CREATE TABLE api_operation_keys (
    incident_id text NOT NULL REFERENCES incidents (incident_id) ON DELETE CASCADE,
    operation text NOT NULL,
    idempotency_key text NOT NULL,
    fingerprint text NOT NULL,
    response jsonb NOT NULL,
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (incident_id, operation, idempotency_key)
);

CREATE INDEX api_operation_keys_expiry_idx ON api_operation_keys (expires_at);
