-- Run as the superuser on a fresh Postgres:  psql -U postgres -f deploy/postgres/init.sql
-- (Linux: sudo -u postgres psql -f deploy/postgres/init.sql). Safe to run again.
-- Creates the provisioning role and closes the default databases to everyone else.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'orgplus_admin') THEN
    CREATE ROLE orgplus_admin LOGIN NOSUPERUSER CREATEDB CREATEROLE NOINHERIT;
  END IF;
END
$$;
-- Postgres 16+: lets it hand each new database to the role it just created
-- (CREATE DATABASE ... OWNER needs SET on that role). pg_hba.conf still only lets it
-- into the "postgres" database.
ALTER ROLE orgplus_admin SET createrole_self_grant = 'set';

REVOKE CONNECT, TEMPORARY ON DATABASE postgres FROM PUBLIC;
REVOKE CONNECT, TEMPORARY ON DATABASE template1 FROM PUBLIC;
GRANT CONNECT ON DATABASE postgres TO orgplus_admin;

-- New databases are created from template1: nothing in it is usable by PUBLIC.
\connect template1
REVOKE ALL ON SCHEMA public FROM PUBLIC;
\connect postgres
REVOKE ALL ON SCHEMA public FROM PUBLIC;
