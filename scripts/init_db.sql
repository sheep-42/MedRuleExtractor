-- Empty few-shot example store. No private examples are distributed.
CREATE TABLE IF NOT EXISTS review_prompt_examples (
    id SERIAL PRIMARY KEY,
    stage INTEGER NOT NULL,
    type VARCHAR(20) NOT NULL,
    label VARCHAR(100) NOT NULL,
    text TEXT NOT NULL,
    output JSON NOT NULL,
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    review BOOLEAN NOT NULL DEFAULT FALSE,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_review_prompt_lookup
ON review_prompt_examples (stage, type, label, is_deleted);
