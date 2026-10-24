-- Runs once, when the PostgreSQL data volume is first initialised.
-- Creates a separate database for automated tests so that test runs (which
-- drop and recreate tables) never touch the development database.
CREATE DATABASE auracinema_test;
