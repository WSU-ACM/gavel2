BEGIN;

ALTER TABLE item
    ADD COLUMN external_id VARCHAR(255),
    ADD COLUMN managed_source VARCHAR(64),
    ADD COLUMN roster_active BOOLEAN;

ALTER TABLE annotator
    ADD COLUMN external_id VARCHAR(255),
    ADD COLUMN managed_source VARCHAR(64),
    ADD COLUMN roster_active BOOLEAN;

ALTER TABLE item
    ADD CONSTRAINT ck_item_integration_identity
    CHECK ((external_id IS NULL) = (managed_source IS NULL));

ALTER TABLE annotator
    ADD CONSTRAINT ck_annotator_integration_identity
    CHECK ((external_id IS NULL) = (managed_source IS NULL));

CREATE UNIQUE INDEX uq_item_external_id_nonnull
    ON item(external_id) WHERE external_id IS NOT NULL;
CREATE UNIQUE INDEX uq_annotator_external_id_nonnull
    ON annotator(external_id) WHERE external_id IS NOT NULL;
CREATE INDEX ix_item_managed_source_external_id
    ON item(managed_source, external_id);
CREATE INDEX ix_item_managed_source_roster_active
    ON item(managed_source, roster_active);
CREATE INDEX ix_annotator_managed_source_external_id
    ON annotator(managed_source, external_id);
CREATE INDEX ix_annotator_managed_source_roster_active
    ON annotator(managed_source, roster_active);

CREATE TABLE membership_roster_import (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    administrator VARCHAR(64) NOT NULL DEFAULT 'admin',
    projects_sha256 VARCHAR(64) NOT NULL,
    participants_sha256 VARCHAR(64) NOT NULL,
    projects_created INTEGER NOT NULL DEFAULT 0,
    projects_updated INTEGER NOT NULL DEFAULT 0,
    projects_unchanged INTEGER NOT NULL DEFAULT 0,
    projects_deactivated INTEGER NOT NULL DEFAULT 0,
    participants_created INTEGER NOT NULL DEFAULT 0,
    participants_updated INTEGER NOT NULL DEFAULT 0,
    participants_unchanged INTEGER NOT NULL DEFAULT 0,
    participants_deactivated INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE invitation_delivery (
    id SERIAL PRIMARY KEY,
    annotator_id INTEGER NOT NULL UNIQUE
        REFERENCES annotator(id) ON DELETE CASCADE,
    import_id INTEGER
        REFERENCES membership_roster_import(id) ON DELETE SET NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    failure_code VARCHAR(64),
    claim_token VARCHAR(32),
    claimed_at TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP WITHOUT TIME ZONE
);
CREATE INDEX ix_invitation_delivery_import_id
    ON invitation_delivery(import_id);
CREATE INDEX ix_invitation_delivery_status
    ON invitation_delivery(status);

INSERT INTO setting (key, value)
VALUES (
    'voting_started',
    CASE
        WHEN EXISTS (SELECT 1 FROM decision)
          OR EXISTS (SELECT 1 FROM bracket_vote)
        THEN 'true'
        ELSE 'false'
    END
)
ON CONFLICT (key) DO UPDATE SET value = CASE
    WHEN setting.value = 'true' OR EXCLUDED.value = 'true' THEN 'true'
    ELSE 'false'
END;

COMMIT;
