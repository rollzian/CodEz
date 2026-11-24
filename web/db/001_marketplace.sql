BEGIN;
CREATE TABLE IF NOT EXISTS publishers (
    id text PRIMARY KEY CHECK (id ~ '^[a-f0-9]{24}$'),
    name text NOT NULL, verified boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS extensions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    publisher text NOT NULL REFERENCES publishers(id),
    slug text UNIQUE NOT NULL CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'),
    kind text NOT NULL CHECK (kind IN ('skills','plugins','mcp')),
    title text NOT NULL, description text NOT NULL, category text NOT NULL,
    tags text NOT NULL, license text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
    search tsvector GENERATED ALWAYS AS (to_tsvector('simple', title || ' ' || description || ' ' || category || ' ' || tags)) STORED
);
CREATE INDEX IF NOT EXISTS extensions_search ON extensions USING gin(search);
CREATE TABLE IF NOT EXISTS versions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    extension bigint NOT NULL REFERENCES extensions(id),
    version text NOT NULL, compatibility text NOT NULL, dependencies text NOT NULL,
    changelog text NOT NULL, filename text NOT NULL, package bytea NOT NULL CHECK(octet_length(package) BETWEEN 1 AND 2097152),
    sha256 text NOT NULL CHECK(sha256 ~ '^[a-f0-9]{64}$'),
    state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','approved','rejected')),
    created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(extension,version)
);
CREATE INDEX IF NOT EXISTS versions_catalog ON versions(extension,state,id DESC);
CREATE TABLE IF NOT EXISTS reviews (
    extension bigint REFERENCES extensions(id), author text REFERENCES publishers(id),
    rating smallint NOT NULL CHECK(rating BETWEEN 1 AND 5), body text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(extension,author)
);
CREATE TABLE IF NOT EXISTS favorites (
    extension bigint REFERENCES extensions(id), author text REFERENCES publishers(id), PRIMARY KEY(extension,author)
);
CREATE TABLE IF NOT EXISTS subscriptions (
    extension bigint REFERENCES extensions(id), author text REFERENCES publishers(id), PRIMARY KEY(extension,author)
);
CREATE TABLE IF NOT EXISTS downloads (
    version bigint REFERENCES versions(id), author text REFERENCES publishers(id), downloaded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(version,author)
);
CREATE TABLE IF NOT EXISTS reports (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, version bigint REFERENCES versions(id), author text REFERENCES publishers(id),
    reason text NOT NULL, state text NOT NULL DEFAULT 'open' CHECK(state IN ('open','closed')),
    created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(version,author)
);
COMMIT;
