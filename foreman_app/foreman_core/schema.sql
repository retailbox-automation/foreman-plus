-- Foreman+ core: agent registry, bi-temporal shared memory, write-gate journal.

CREATE TABLE IF NOT EXISTS agents (
    name          text PRIMARY KEY,
    version       text NOT NULL,
    description   text,
    registered_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gate_journal (
    id             bigserial PRIMARY KEY,
    proposed_by    text NOT NULL,
    session_id     text,
    proposal       jsonb NOT NULL,
    verdict        text NOT NULL DEFAULT 'pending',
    verifier_model text,
    reason         text,
    decided_at     timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memory_facts (
    id            bigserial PRIMARY KEY,
    subject       text NOT NULL,
    predicate     text NOT NULL,
    object        jsonb NOT NULL,
    source_agent  text NOT NULL REFERENCES agents(name),
    valid_from    timestamptz NOT NULL DEFAULT now(),
    valid_to      timestamptz,
    ingested_at   timestamptz NOT NULL DEFAULT now(),
    superseded_by bigint REFERENCES memory_facts(id),
    gate_entry_id bigint REFERENCES gate_journal(id)
);

CREATE INDEX IF NOT EXISTS memory_facts_subject_idx
    ON memory_facts (subject, predicate) WHERE valid_to IS NULL;
CREATE INDEX IF NOT EXISTS gate_journal_subject_idx
    ON gate_journal ((proposal ->> 'subject'));
