-- QueryGuard Phase 3 application-database migration.

-- Run this in queryguard_app as queryguard_app (or postgres).


 

DO $queryguard$

BEGIN

    IF current_database() <> 'queryguard_app' THEN

        RAISE EXCEPTION

            'Wrong database. Connect to queryguard_app before running this script. Current database: %',

            current_database();

    END IF;

END

$queryguard$;


 

BEGIN;


 

ALTER TABLE queryguard.analysis_runs

    ADD COLUMN IF NOT EXISTS thread_id text,

    ADD COLUMN IF NOT EXISTS normalized_question text,

    ADD COLUMN IF NOT EXISTS selected_dimension_ids jsonb NOT NULL DEFAULT '[]'::jsonb,

    ADD COLUMN IF NOT EXISTS current_node text,

    ADD COLUMN IF NOT EXISTS error_code text,

    ADD COLUMN IF NOT EXISTS error_message text;


 

CREATE UNIQUE INDEX IF NOT EXISTS analysis_runs_thread_id_uidx

    ON queryguard.analysis_runs(thread_id)

    WHERE thread_id IS NOT NULL;


 

CREATE TABLE IF NOT EXISTS queryguard.clarifications (

    clarification_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    run_id uuid NOT NULL UNIQUE

        REFERENCES queryguard.analysis_runs(run_id) ON DELETE CASCADE,

    question text NOT NULL,

    options jsonb NOT NULL DEFAULT '[]'::jsonb,

    selected_choice_id text,

    status text NOT NULL CHECK (status IN ('pending', 'answered')),

    created_at timestamptz NOT NULL DEFAULT now(),

    answered_at timestamptz

);


 

CREATE TABLE IF NOT EXISTS queryguard.analysis_artifacts (

    artifact_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    run_id uuid NOT NULL

        REFERENCES queryguard.analysis_runs(run_id) ON DELETE CASCADE,

    artifact_type text NOT NULL,

    artifact_version integer NOT NULL DEFAULT 1 CHECK (artifact_version >= 1),

    payload jsonb NOT NULL,

    created_at timestamptz NOT NULL DEFAULT now(),

    UNIQUE (run_id, artifact_type, artifact_version)

);


 

CREATE TABLE IF NOT EXISTS queryguard.model_calls (

    model_call_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    run_id uuid NOT NULL

        REFERENCES queryguard.analysis_runs(run_id) ON DELETE CASCADE,

    graph_node text NOT NULL,

    model_name text NOT NULL,

    prompt_version text NOT NULL,

    input_hash text NOT NULL,

    output_payload jsonb,

    input_tokens integer CHECK (input_tokens IS NULL OR input_tokens >= 0),

    output_tokens integer CHECK (output_tokens IS NULL OR output_tokens >= 0),

    total_tokens integer CHECK (total_tokens IS NULL OR total_tokens >= 0),

    duration_ms integer CHECK (duration_ms IS NULL OR duration_ms >= 0),

    status text NOT NULL CHECK (status IN ('success', 'failed')),

    error_message text,

    created_at timestamptz NOT NULL DEFAULT now()

);


 

CREATE INDEX IF NOT EXISTS analysis_artifacts_run_idx

    ON queryguard.analysis_artifacts(run_id, created_at);


 

CREATE INDEX IF NOT EXISTS model_calls_run_idx

    ON queryguard.model_calls(run_id, created_at);


 

COMMIT;


 

SELECT table_name

FROM information_schema.tables

WHERE table_schema = 'queryguard'

  AND table_name IN ('clarifications', 'analysis_artifacts', 'model_calls')

ORDER BY table_name;


 