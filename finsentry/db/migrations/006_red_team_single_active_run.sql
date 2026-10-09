-- At most one Red Team run may be in the running state. The runner's asyncio.Lock only
-- serializes callers inside one process, and the gateway runs as several replicas. The
-- unique index makes the database the arbiter: a second concurrent insert of a running
-- run fails, whichever process it comes from. Finished runs are not constrained, so every
-- historical run is kept.

-- An index cannot be built while two rows qualify. Keep the newest running run and close
-- the others, with their unfinished executions, so they stay visible as failed.
WITH extra AS (
    UPDATE red_team_runs
       SET status = 'failed', finished_at = now(),
           failure_reason = 'Closed by migration 006: more than one run was marked running.'
     WHERE status = 'running'
       AND run_id <> (
           SELECT run_id FROM red_team_runs WHERE status = 'running'
            ORDER BY created_at DESC LIMIT 1
       )
 RETURNING run_id
)
UPDATE red_team_executions
   SET state = 'finished', outcome = 'execution_failed', expectation = 'not_assessable',
       finished_at = now(), reason = 'The run ended before this execution completed.'
 WHERE run_id IN (SELECT run_id FROM extra) AND state <> 'finished';

CREATE UNIQUE INDEX IF NOT EXISTS red_team_one_running_run
    ON red_team_runs ((true)) WHERE status = 'running';
