BEGIN;

ALTER TABLE annotator
    ADD COLUMN project_id INTEGER REFERENCES item(id) ON DELETE SET NULL;
CREATE INDEX ix_annotator_project_id ON annotator(project_id);

CREATE TABLE tournament (
    id SERIAL PRIMARY KEY,
    size INTEGER NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITHOUT TIME ZONE,
    champion_id INTEGER REFERENCES item(id) ON DELETE RESTRICT
);
CREATE INDEX ix_tournament_status ON tournament(status);

CREATE TABLE tournament_entry (
    id SERIAL PRIMARY KEY,
    tournament_id INTEGER NOT NULL REFERENCES tournament(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES item(id) ON DELETE RESTRICT,
    seed INTEGER NOT NULL,
    initial_mu DOUBLE PRECISION NOT NULL,
    initial_sigma_sq DOUBLE PRECISION NOT NULL,
    UNIQUE (tournament_id, item_id),
    UNIQUE (tournament_id, seed)
);
CREATE INDEX ix_tournament_entry_tournament_id ON tournament_entry(tournament_id);

CREATE TABLE bracket_match (
    id SERIAL PRIMARY KEY,
    tournament_id INTEGER NOT NULL REFERENCES tournament(id) ON DELETE CASCADE,
    round_number INTEGER NOT NULL,
    position INTEGER NOT NULL,
    item_a_id INTEGER REFERENCES item(id) ON DELETE RESTRICT,
    item_b_id INTEGER REFERENCES item(id) ON DELETE RESTRICT,
    winner_id INTEGER REFERENCES item(id) ON DELETE RESTRICT,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    opened_at TIMESTAMP WITHOUT TIME ZONE,
    closed_at TIMESTAMP WITHOUT TIME ZONE,
    UNIQUE (tournament_id, round_number, position),
    CHECK (item_a_id IS NULL OR item_b_id IS NULL OR item_a_id <> item_b_id)
);
CREATE INDEX ix_bracket_match_tournament_id ON bracket_match(tournament_id);
CREATE INDEX ix_bracket_match_status ON bracket_match(status);

CREATE TABLE bracket_vote (
    id SERIAL PRIMARY KEY,
    match_id INTEGER NOT NULL REFERENCES bracket_match(id) ON DELETE CASCADE,
    annotator_id INTEGER NOT NULL REFERENCES annotator(id) ON DELETE RESTRICT,
    item_id INTEGER NOT NULL REFERENCES item(id) ON DELETE RESTRICT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (match_id, annotator_id)
);
CREATE INDEX ix_bracket_vote_match_id ON bracket_vote(match_id);
CREATE INDEX ix_bracket_vote_annotator_id ON bracket_vote(annotator_id);

INSERT INTO setting (key, value)
VALUES (
    'phase',
    CASE
        WHEN EXISTS (SELECT 1 FROM setting WHERE key = 'closed' AND value = 'true')
        THEN 'closed'
        ELSE 'initial'
    END
)
ON CONFLICT (key) DO NOTHING;

COMMIT;
