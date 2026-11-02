-- QueryGuard Phase 4 application-database migration.

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

    ADD COLUMN IF NOT EXISTS verification_status text NOT NULL DEFAULT 'not_started',

    ADD COLUMN IF NOT EXISTS verification_repair_attempts integer NOT NULL DEFAULT 0;


 

ALTER TABLE queryguard.query_executions

    ADD COLUMN IF NOT EXISTS query_role text NOT NULL DEFAULT 'manual',

    ADD COLUMN IF NOT EXISTS parent_query_id uuid,

    ADD COLUMN IF NOT EXISTS candidate_key text;


 

DO $constraints$

BEGIN

    IF NOT EXISTS (

        SELECT 1 FROM pg_constraint

        WHERE conname = 'analysis_runs_verification_status_check'

          AND conrelid = 'queryguard.analysis_runs'::regclass

    ) THEN

        ALTER TABLE queryguard.analysis_runs

            ADD CONSTRAINT analysis_runs_verification_status_check

            CHECK (verification_status IN (

                'not_started', 'reviewing', 'querying', 'reconciling',

                'repairing', 'passed', 'rejected', 'failed'

            ));

    END IF;


 

    IF NOT EXISTS (

        SELECT 1 FROM pg_constraint

        WHERE conname = 'analysis_runs_verification_repair_attempts_check'

          AND conrelid = 'queryguard.analysis_runs'::regclass

    ) THEN

        ALTER TABLE queryguard.analysis_runs

            ADD CONSTRAINT analysis_runs_verification_repair_attempts_check

            CHECK (verification_repair_attempts >= 0);

    END IF;


 

    IF NOT EXISTS (

        SELECT 1 FROM pg_constraint

        WHERE conname = 'query_executions_query_role_check'

          AND conrelid = 'queryguard.query_executions'::regclass

    ) THEN

        ALTER TABLE queryguard.query_executions

            ADD CONSTRAINT query_executions_query_role_check

            CHECK (query_role IN ('manual', 'analyst', 'verifier'));

    END IF;


 

    IF NOT EXISTS (

        SELECT 1 FROM pg_constraint

        WHERE conname = 'query_executions_parent_query_fk'

          AND conrelid = 'queryguard.query_executions'::regclass

    ) THEN

        ALTER TABLE queryguard.query_executions

            ADD CONSTRAINT query_executions_parent_query_fk

            FOREIGN KEY (parent_query_id)

            REFERENCES queryguard.query_executions(query_id)

            ON DELETE SET NULL;

    END IF;

END

$constraints$;


 

ALTER TABLE queryguard.claims

    ADD COLUMN IF NOT EXISTS claim_key text,

    ADD COLUMN IF NOT EXISTS statement_text text,

    ADD COLUMN IF NOT EXISTS value_type text,

    ADD COLUMN IF NOT EXISTS source_check_id text,

    ADD COLUMN IF NOT EXISTS importance text NOT NULL DEFAULT 'supporting';


 

DO $claim_constraints$

BEGIN

    IF NOT EXISTS (

        SELECT 1 FROM pg_constraint

        WHERE conname = 'claims_value_type_check'

          AND conrelid = 'queryguard.claims'::regclass

    ) THEN

        ALTER TABLE queryguard.claims

            ADD CONSTRAINT claims_value_type_check

            CHECK (value_type IS NULL OR value_type IN ('number', 'text'));

    END IF;


 

    IF NOT EXISTS (

        SELECT 1 FROM pg_constraint

        WHERE conname = 'claims_importance_check'

          AND conrelid = 'queryguard.claims'::regclass

    ) THEN

        ALTER TABLE queryguard.claims

            ADD CONSTRAINT claims_importance_check

            CHECK (importance IN ('primary', 'supporting'));

    END IF;

END

$claim_constraints$;


 

CREATE UNIQUE INDEX IF NOT EXISTS claims_run_claim_key_uidx

    ON queryguard.claims(run_id, claim_key)

    WHERE claim_key IS NOT NULL;


 

CREATE TABLE IF NOT EXISTS queryguard.verifier_reviews (

    review_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    run_id uuid NOT NULL

        REFERENCES queryguard.analysis_runs(run_id) ON DELETE CASCADE,

    review_version integer NOT NULL CHECK (review_version >= 1),

    analyst_query_id uuid NOT NULL

        REFERENCES queryguard.query_executions(query_id) ON DELETE CASCADE,

    decision text NOT NULL CHECK (decision IN ('verify', 'reject')),

    summary text NOT NULL,

    independence_strategy text NOT NULL,

    issues jsonb NOT NULL DEFAULT '[]'::jsonb,

    checks jsonb NOT NULL DEFAULT '[]'::jsonb,

    created_at timestamptz NOT NULL DEFAULT now(),

    UNIQUE (run_id, review_version)

);


 

CREATE TABLE IF NOT EXISTS queryguard.reconciliation_results (

    reconciliation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    run_id uuid NOT NULL

        REFERENCES queryguard.analysis_runs(run_id) ON DELETE CASCADE,

    reconciliation_version integer NOT NULL CHECK (reconciliation_version >= 1),

    analyst_query_id uuid NOT NULL

        REFERENCES queryguard.query_executions(query_id) ON DELETE CASCADE,

    verifier_query_id uuid NOT NULL

        REFERENCES queryguard.query_executions(query_id) ON DELETE CASCADE,

    status text NOT NULL CHECK (status IN ('pass', 'mismatch', 'rejected')),

    comparisons jsonb NOT NULL DEFAULT '[]'::jsonb,

    issues jsonb NOT NULL DEFAULT '[]'::jsonb,

    created_at timestamptz NOT NULL DEFAULT now(),

    UNIQUE (run_id, reconciliation_version)

);


 

CREATE INDEX IF NOT EXISTS query_executions_role_idx

    ON queryguard.query_executions(run_id, query_role, created_at);


 

CREATE INDEX IF NOT EXISTS verifier_reviews_run_idx

    ON queryguard.verifier_reviews(run_id, review_version);


 

CREATE INDEX IF NOT EXISTS reconciliation_results_run_idx

    ON queryguard.reconciliation_results(run_id, reconciliation_version);


 

COMMIT;


 

SELECT table_name

FROM information_schema.tables

WHERE table_schema = 'queryguard'

  AND table_name IN ('verifier_reviews', 'reconciliation_results')

ORDER BY table_name;


 

SELECT column_name, data_type

FROM information_schema.columns

WHERE table_schema = 'queryguard'

  AND table_name IN ('analysis_runs', 'query_executions', 'claims')

  AND column_name IN (

      'verification_status', 'verification_repair_attempts',

      'query_role', 'parent_query_id', 'candidate_key',

      'claim_key', 'statement_text', 'value_type', 'source_check_id', 'importance'

  )

ORDER BY table_name, ordinal_position;


 