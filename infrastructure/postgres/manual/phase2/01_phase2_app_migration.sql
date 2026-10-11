-- QueryGuard Phase 2 application-database migration.

-- Run this in database queryguard_app as queryguard_app (or postgres).


 

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


 

ALTER TABLE queryguard.query_executions

    ADD COLUMN IF NOT EXISTS normalized_sql text,

    ADD COLUMN IF NOT EXISTS executable_sql text,

    ADD COLUMN IF NOT EXISTS tables_used jsonb NOT NULL DEFAULT '[]'::jsonb,

    ADD COLUMN IF NOT EXISTS functions_used jsonb NOT NULL DEFAULT '[]'::jsonb,

    ADD COLUMN IF NOT EXISTS plan_summary jsonb,

    ADD COLUMN IF NOT EXISTS truncated boolean,

    ADD COLUMN IF NOT EXISTS error_code text,

    ADD COLUMN IF NOT EXISTS error_message text;


 

CREATE TABLE IF NOT EXISTS queryguard.query_result_previews (

    query_id uuid PRIMARY KEY

        REFERENCES queryguard.query_executions(query_id) ON DELETE CASCADE,

    columns jsonb NOT NULL,

    rows jsonb NOT NULL,

    returned_row_count integer NOT NULL CHECK (returned_row_count >= 0),

    truncated boolean NOT NULL,

    created_at timestamptz NOT NULL DEFAULT now()

);


 

CREATE INDEX IF NOT EXISTS query_executions_status_idx

    ON queryguard.query_executions(execution_status, created_at DESC);


 

COMMIT;


 

SELECT

    column_name,

    data_type

FROM information_schema.columns

WHERE table_schema = 'queryguard'

  AND table_name = 'query_executions'

ORDER BY ordinal_position;


 

SELECT

    table_schema,

    table_name

FROM information_schema.tables

WHERE table_schema = 'queryguard'

  AND table_name = 'query_result_previews';


 