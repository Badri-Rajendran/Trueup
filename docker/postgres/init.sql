-- Trueup database roles. Runs once, as the postgres superuser, on first container start.
--
-- Three roles, not one, because docs/specs/0-backend-foundation-design.md §7.3 requires that
-- bypassing Row-Level Security be a *credential boundary* rather than application discipline:
-- "The web API's credential is never granted BYPASSRLS — it is structurally incapable of
-- bypassing RLS regardless of a future bug in request-handling code."
--
-- The equivalent roles must exist in Azure Postgres Flexible Server; see docs/project-helpers/
-- service-accounts.md. Passwords here are local-development only and are never used elsewhere.

-- Owns the schema. Runs migrations. Never used to serve a request.
CREATE ROLE trueup_owner LOGIN PASSWORD 'trueup_owner';

-- The web API. NOBYPASSRLS is the whole point of this role existing separately.
CREATE ROLE trueup_app LOGIN PASSWORD 'trueup_app' NOBYPASSRLS;

-- Scheduled jobs and the outbox worker, which legitimately operate across every customer.
CREATE ROLE trueup_worker LOGIN PASSWORD 'trueup_worker' BYPASSRLS;

-- S11's chat assistant tool call (ADR 19). NOBYPASSRLS, and deliberately excluded from the
-- `ALTER DEFAULT PRIVILEGES` grants below: this role gets no access to any table by default, only
-- the explicit `GRANT SELECT` on the curated chat views its own migration adds. A missing grant
-- here is not a bug to fix — it is the whole point of a least-privilege credential.
CREATE ROLE trueup_chat_readonly LOGIN PASSWORD 'trueup_chat_readonly' NOBYPASSRLS;

-- A separate database for the test suite, so a test run can never touch dev data.
CREATE DATABASE trueup_test OWNER trueup_owner;

ALTER DATABASE trueup OWNER TO trueup_owner;

\connect trueup

ALTER SCHEMA public OWNER TO trueup_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO trueup_app, trueup_worker, trueup_chat_readonly;

-- Tables created later by migrations (as trueup_owner) are reachable by both runtime roles.
-- Append-only tables then REVOKE UPDATE/DELETE from trueup_app in their own migration, per
-- S1 §6 — this default is the baseline those revocations carve away from, not a contradiction.
ALTER DEFAULT PRIVILEGES FOR ROLE trueup_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO trueup_app, trueup_worker;
ALTER DEFAULT PRIVILEGES FOR ROLE trueup_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO trueup_app, trueup_worker;

\connect trueup_test

ALTER SCHEMA public OWNER TO trueup_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO trueup_app, trueup_worker, trueup_chat_readonly;

ALTER DEFAULT PRIVILEGES FOR ROLE trueup_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO trueup_app, trueup_worker;
ALTER DEFAULT PRIVILEGES FOR ROLE trueup_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO trueup_app, trueup_worker;
