# 05 — Data Model and Persistence Layer

> **Purpose of this document:** A complete, interview-ready reference for every
> form of persistence in SyncCut Studio — relational database, in-memory
> dictionaries, and the filesystem session store. After reading this you should
> be able to answer any question about where data lives, how it gets there, and
> what happens when it doesn't.

---

## Table of Contents

1. [Two Kinds of Persistence](#1-two-kinds-of-persistence)
2. [The User Model](#2-the-user-model)
3. [The PasswordResetToken Model](#3-the-passwordresettoken-model)
4. [The Subscription Model](#4-the-subscription-model)
5. [The Project Model](#5-the-project-model)
6. [Database Engine Selection (`_database_url`)](#6-database-engine-selection-_database_url)
7. [Migration Strategy (`_ensure_legacy_columns`)](#7-migration-strategy-_ensure_legacy_columns)
8. [In-Memory State: `SESSIONS` and `LOCAL_JOBS`](#8-in-memory-state-sessions-and-local_jobs)
9. [Filesystem Session Structure](#9-filesystem-session-structure)
10. [Where Other App Data Lives](#10-where-other-app-data-lives)
11. [Stateless vs. Stateful Analysis](#11-stateless-vs-stateful-analysis)
12. [Key Interview Q&A](#12-key-interview-qa)

---

## 1 — Two Kinds of Persistence

SyncCut Studio uses **two completely independent persistence systems** that serve
different purposes and have different operational characteristics.

### 1.1 Relational persistence: SQLite / PostgreSQL via SQLAlchemy

User accounts, subscription status, and project metadata are stored in a
relational database managed by SQLAlchemy ORM. In desktop/MSIX mode this is a
local SQLite file; in cloud/Render mode it is a PostgreSQL database pointed to
by `DATABASE_URL`.

**Why relational storage for metadata?**

- Fast indexed lookups: find a user by token or email with a single
  `SELECT … WHERE` with an index; no full-table scan.
- ACID semantics: a failed registration does not leave a half-created user row;
  rollback on exception is automatic via `_session_scope()`.
- Lightweight for the data shape: user and project rows are small (< 1 KB each);
  storing them in a relational table costs almost nothing.
- Queryable: `get_user_projects()` can `ORDER BY created_at DESC` trivially;
  doing that over raw JSON files would require reading every file.

### 1.2 Filesystem persistence: session directories

Uploaded video and audio files, WAV decode artifacts, sync reports, proxy
videos, and export outputs are written to per-session directories under
`%LOCALAPPDATA%\SyncCutStudio\sessions\`.

**Why the filesystem for media artifacts?**

- Size: a single 4K video clip can be several gigabytes. Storing binary blobs
  in SQLite would bloat the database file and make backup/restore painful.
- Streaming: `send_file()` can stream directly from disk with zero copy via
  `Range` headers; a database column cannot do this.
- FFmpeg interop: every pipeline stage (decode, proxy transcode, mixdown) writes
  and reads from paths. Using the filesystem is the natural interface.
- Atomicity is not critical: if an upload is interrupted the partial directory
  can simply be deleted; there is no transaction to roll back.

### 1.3 How the two systems are connected

The `session_id` column in the `projects` table is the bridge. It is a string
key that names both a row in the `projects` table and a directory under
`sessions/`. The application resolves a project's filesystem artifacts by
calling `session_dir(project.session_id)`.

```
SQLite: projects row  ──── session_id = "a3f9b2c1d4e5" ────► sessions/a3f9b2c1d4e5/
                                                                ├── .owner.json
                                                                ├── 01_camera_A.mp4
                                                                ├── sync_report.json
                                                                └── proxy/
```

---

## 2 — The User Model

**Source:** `synccut/api/db.py`, lines 44–59

```python
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    hashed_password: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Kept to allow existing SQLite accounts to continue authenticating.
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    salt: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    google_sub: Mapped[str | None] = mapped_column(String(255), nullable=True)
    plan: Mapped[str] = mapped_column(String(40), nullable=False, default="Free Plan")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
```

### 2.1 Column-by-column breakdown

| Column | Type | Nullable | Purpose |
|--------|------|----------|---------|
| `id` | `VARCHAR(64)` | No | Primary key, format `usr_<16 hex chars>` |
| `email` | `VARCHAR(320)` | No | Unique, indexed, normalized to lowercase |
| `name` | `VARCHAR(120)` | No (default `""`) | Display name, falls back to email prefix |
| `hashed_password` | `VARCHAR(512)` | Yes | Werkzeug `pbkdf2:sha256` hash (current) |
| `password_hash` | `VARCHAR(256)` | Yes | PBKDF2-SHA256 hex digest (legacy) |
| `salt` | `VARCHAR(64)` | Yes | Salt used with legacy `password_hash` |
| `token` | `VARCHAR(256)` | Yes | Bearer auth token (indexed) |
| `google_sub` | `VARCHAR(255)` | Yes | Google OAuth subject identifier |
| `plan` | `VARCHAR(40)` | No (default `"Free Plan"`) | Human-readable plan label |
| `created_at` | `DATETIME` (UTC) | No | Account creation timestamp |

### 2.2 How `id` is generated

```python
# db.py – create_user(), line 267
user = User(
    id=f"usr_{secrets.token_hex(8)}",
    ...
)
```

`secrets.token_hex(8)` produces 8 random bytes encoded as 16 lowercase
hexadecimal characters. The prefix `usr_` makes the type of the entity obvious
in logs and foreign key traces. Total length: 20 characters, well within the
`VARCHAR(64)` column limit.

### 2.3 Why two password columns exist

When SyncCut first shipped, passwords were hashed with a custom PBKDF2-SHA256
implementation (`hash_password()` in `db.py`) that stored the hex digest in
`password_hash` and the random hex salt in `salt`. This is the *legacy* scheme.

Later, the codebase adopted Werkzeug's `generate_password_hash()` / 
`check_password_hash()`, which produces a self-contained `pbkdf2:sha256:…`
string stored in `hashed_password`. Werkzeug's format encodes the algorithm,
iteration count, salt, and hash in one opaque string; no separate `salt` column
is needed.

Both columns are kept so that existing local SQLite accounts — whose rows only
have `password_hash` / `salt` populated — continue to authenticate without a
forced migration. The `authenticate_user()` function checks `hashed_password`
first; if that column is `NULL` it falls back to the legacy verifier:

```python
# db.py – authenticate_user(), lines 386–392
valid = False
if user.hashed_password:
    valid = check_password_hash(user.hashed_password, password)
elif user.salt and user.password_hash:
    valid = verify_password(password, user.salt, user.password_hash)
if not valid:
    return None
```

New users created after the migration have both columns populated:
`create_user()` calls `generate_password_hash(password)` for `hashed_password`
*and* `hash_password(password)` for the legacy pair, so the account can be
authenticated by either code path regardless of which schema migration has run.

### 2.4 How `token` is generated and used

```python
# db.py – create_user(), line 273
token=secrets.token_urlsafe(32),

# db.py – authenticate_user(), line 394
user.token = secrets.token_urlsafe(32)
```

`secrets.token_urlsafe(32)` produces 32 random bytes base64url-encoded ≈
43 URL-safe characters. It is regenerated on every successful login so that
sessions from other devices are automatically invalidated.

**End-to-end token flow:**

```
1. POST /api/login  → authenticate_user() → new token written to users.token
2. Response body: { "token": "abc123…" }
3. Frontend stores token in localStorage (not a cookie)
4. Every subsequent API request: Authorization: Bearer abc123…
5. require_auth decorator → _get_current_user() → strips "Bearer " prefix
6. get_user_by_token(token) → SELECT * FROM users WHERE token = ?
7. If found → g.current_user = user dict; route proceeds
8. POST /api/logout → revoke_user_token() → users.token = NULL
```

```python
# routes.py – _get_current_user(), lines 52–59
def _get_current_user():
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
    token = token or request.args.get("token", "") or session.get("auth_token", "")
    if not token:
        return None
    from synccut.api.db import get_user_by_token
    return get_user_by_token(token)
```

The `token` column has a database index, making the per-request lookup
effectively O(1) for typical table sizes.

### 2.5 Google OAuth path

When a user authenticates via Google, `authenticate_google_user()` receives the
`google_sub` (Google's permanent user identifier), looks up the user by
`google_sub OR email`, and either creates a new account or updates the existing
one. A fresh `token_urlsafe(32)` is always issued, invalidating any prior session:

```python
# db.py – authenticate_google_user(), lines 315–317
user.google_sub = google_sub
user.token = secrets.token_urlsafe(32)
subscription = session.get(Subscription, user.id)
```

Google-authenticated users have `hashed_password` populated with a random
generated password (they cannot log in with email/password unless they set one
via the forgot-password flow).

---

## 3 — The PasswordResetToken Model

**Source:** `synccut/api/db.py`, lines 62–69

```python
class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

### 3.1 Why store the hash, not the raw token

The URL-safe token sent in the reset email is a secret equivalent to a password.
Storing it in plaintext means a database dump immediately leaks all pending reset
links. Storing `SHA-256(raw_token)` means an attacker with database read access
still cannot construct valid reset URLs — they would need to reverse SHA-256.

The route layer hashes the token from the URL before looking it up:

```python
# routes.py (conceptual)
raw_token = request.json["token"]
token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
success = db.consume_password_reset(token_hash, new_password)
```

### 3.2 Full reset flow

```
POST /api/forgot-password  { "email": "user@example.com" }
  │
  ├─ db.create_password_reset(email, token_hash, expires_at)
  │    - generates raw_token = secrets.token_urlsafe(32)
  │    - token_hash = sha256(raw_token)
  │    - deletes any prior reset row for this user (one outstanding reset at a time)
  │    - inserts PasswordResetToken(token_hash, user_id, expires_at = now + 1 hour)
  │
  └─ SMTP: sends email with link containing raw_token

User clicks link → browser POSTs raw_token to /api/reset-password

POST /api/reset-password  { "token": "<raw_token>", "password": "<new_pw>" }
  │
  └─ db.consume_password_reset(sha256(raw_token), new_password)
       - SELECT … WITH FOR UPDATE (advisory lock, prevents replay)
       - checks expires_at > now
       - updates user.hashed_password, user.salt, user.password_hash
       - sets user.token = NULL (forces re-login on all devices)
       - DELETE FROM password_reset_tokens WHERE user_id = ?
       - returns True
```

```python
# db.py – consume_password_reset(), lines 344–372
def consume_password_reset(token_hash: str, password: str) -> bool:
    with _session_scope() as session:
        reset = session.scalar(
            select(PasswordResetToken)
            .where(PasswordResetToken.token_hash == token_hash)
            .with_for_update()
        )
        if reset is None:
            return False
        expires_at = reset.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            session.delete(reset)
            return False
        user = session.get(User, reset.user_id)
        if user is None:
            session.delete(reset)
            return False
        salt, legacy_hash = hash_password(password)
        user.hashed_password = generate_password_hash(password)
        user.salt = salt
        user.password_hash = legacy_hash
        user.token = None
        session.execute(
            delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
        )
        return True
```

**Key properties:**
- `WITH FOR UPDATE` prevents two simultaneous requests for the same token from
  both succeeding (TOCTOU race).
- `ON DELETE CASCADE` on `user_id` means deleting a user automatically removes
  their pending reset tokens.
- `user.token = None` after reset: any active sessions are logged out
  immediately, preventing session fixation after a credential change.

---

## 4 — The Subscription Model

**Source:** `synccut/api/db.py`, lines 72–85

```python
class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("stripe_subscription_id", name="uq_subscriptions_stripe_subscription_id"),
        CheckConstraint("tier IN ('free', 'pro', 'studio')", name="ck_subscriptions_tier"),
    )

    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tier: Mapped[str] = mapped_column(String(16), nullable=False, default="free")
    stripe_customer_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

### 4.1 Schema design notes

- **`user_id` is the primary key**, not a separate surrogate key. This enforces
  the 1:1 cardinality between user and subscription at the database level; there
  is no way to accidentally create two subscription rows for the same user.
- **`ON DELETE CASCADE`** means dropping a user account automatically removes
  the subscription row — no orphan cleanup needed.
- **`CHECK` constraint** on `tier` restricts valid values to `free`, `pro`, and
  `studio` at the database engine level, not just the application layer. If a
  bug somehow sends `"enterprise"` to the DB, the constraint fires.
- **`UniqueConstraint` on `stripe_subscription_id`** prevents duplicate Stripe
  webhook events from creating two active subscriptions.

### 4.2 `_tier_for()` — expiry-aware tier resolution

```python
# db.py – _tier_for(), lines 238–248
def _tier_for(subscription: Subscription | None) -> str:
    if subscription is None or subscription.tier not in {"free", "pro", "studio"}:
        return "free"
    expires_at = subscription.expires_at
    if expires_at is not None:
        now = datetime.now(timezone.utc)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            return "free"
    return subscription.tier
```

**Decision tree:**

```
subscription is None?           → "free"
tier not in {free,pro,studio}?  → "free"   (defensive; CHECK constraint should prevent this)
expires_at is None?             → subscription.tier  (no expiry = permanent)
expires_at <= now?              → "free"   (subscription lapsed)
else                            → subscription.tier
```

`expires_at` being `None` for `free` tier users is the normal case — there is
no expiry date to track when nothing is paid. Pro/Studio subscriptions populated
by Stripe set `expires_at` to the subscription's `current_period_end`.

### 4.3 Stripe webhook flow

```
Stripe sends POST /api/billing/webhook
  │
  ├─ billing_bp verifies STRIPE_WEBHOOK_SECRET signature
  ├─ customer.subscription.updated  → activate_pro_subscription()
  │    - upserts Subscription row: tier="pro", stripe_customer_id, stripe_subscription_id, expires_at
  │    - sets user.plan = "Pro Plan"
  │
  └─ customer.subscription.deleted → downgrade_subscription()
       - looks up by stripe_subscription_id OR stripe_customer_id
       - tier="free", stripe_subscription_id=None, expires_at=None
       - sets user.plan = "Free Plan"
```

```python
# db.py – activate_pro_subscription(), lines 444–463
def activate_pro_subscription(
    user_id: str,
    customer_id: str | None,
    subscription_id: str,
    expires_at: datetime | None,
) -> bool:
    with _session_scope() as session:
        user = session.get(User, user_id)
        if user is None:
            return False
        subscription = session.get(Subscription, user_id)
        if subscription is None:
            subscription = Subscription(user_id=user_id, tier="pro")
            session.add(subscription)
        subscription.tier = "pro"
        subscription.stripe_customer_id = customer_id
        subscription.stripe_subscription_id = subscription_id
        subscription.expires_at = expires_at
        user.plan = "Pro Plan"
        return True
```

---

## 5 — The Project Model

**Source:** `synccut/api/db.py`, lines 88–105

```python
class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, default="", index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="Draft")
    camera_count: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    duration: Mapped[str | None] = mapped_column(String(32), nullable=True, default="00:00:00")
    thumbnail_url: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True, default=1.0)
    # These are strings for compatibility with the date labels in existing SQLite projects.
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(64), nullable=False)
```

### 5.1 Column breakdown

| Column | Type | Notes |
|--------|------|-------|
| `id` | `VARCHAR(64)` | `proj-<12 hex chars>` via `f"proj-{secrets.token_hex(6)}"` |
| `user_id` | `VARCHAR(64) FK` | References `users.id`, `ON DELETE CASCADE`, indexed |
| `session_id` | `VARCHAR(128)` | Key to filesystem session dir; indexed |
| `name` | `VARCHAR(255)` | User-supplied project name |
| `description` | `TEXT` | Nullable, default "Multicam editing session" |
| `status` | `VARCHAR(64)` | `"Draft"` or `"Complete"` |
| `camera_count` | `INTEGER` | Number of video angles uploaded |
| `duration` | `VARCHAR(32)` | String `"HH:MM:SS"` from FFprobe |
| `thumbnail_url` | `TEXT` | Nullable; Unsplash fallback if not set |
| `confidence_score` | `FLOAT` | 0.0–1.0 sync confidence from GCC-PHAT |
| `created_at` | `VARCHAR(64)` | String `"Nov 19, 2026"` for UI display |
| `updated_at` | `VARCHAR(64)` | Same format; updated on every mutation |

**Why are `created_at` / `updated_at` strings?** When the app first shipped,
the UI received these values and displayed them directly as human-readable date
labels. Converting to `DATETIME` columns would require all existing SQLite
projects to be migrated. The comment in the model says: *"These are strings for
compatibility with the date labels in existing SQLite projects."*

### 5.2 Why `session_id` is not always equal to `project_id`

The session (filesystem working directory) is created **before** the project
row. The sequence is:

```
1. POST /api/session          → new_session() → uuid4().hex[:12] → returns session_id
2. User uploads files         → POST /api/upload?session_id=<session_id>
3. User runs sync             → POST /api/sync?session_id=<session_id>
4. POST /api/session/<id>/project → create_user_project(session_id=<session_id>)
```

By step 4, the project gets a *new* `proj-…` ID, but `session_id` is set to the
pre-existing filesystem key. If the client does not supply a `session_id` in the
payload, the fallback is `session_id = project_id`:

```python
# db.py – create_user_project(), line 522
session_id=project_data.get("session_id") or project_id,
```

This covers the rare case where a project is created without a prior `/api/session`
call (e.g., programmatic import scripts).

### 5.3 CRUD operations

**Create / upsert — `session.merge()`:**

```python
# db.py – create_user_project(), line 536–537
with _session_scope() as session:
    session.merge(project)
```

`session.merge()` performs an `INSERT OR REPLACE` (upsert) semantics: if a row
with the same primary key already exists it is updated; otherwise it is inserted.
This means calling `create_user_project()` with an existing `id` is safe and
idempotent — it updates the metadata rather than raising an integrity error.

**Partial update — `update_user_project()`:**

```python
# db.py – update_user_project(), lines 563–574
def update_user_project(user_id: str, project_id: str, updates: dict) -> bool:
    with _session_scope() as session:
        project = session.scalar(
            select(Project).where(Project.id == project_id, Project.user_id == user_id)
        )
        if project is None:
            return False
        if "status" in updates:
            project.status = updates["status"]
        if "name" in updates:
            project.name = updates["name"]
        project.updated_at = datetime.now(timezone.utc).strftime("%b %d, %Y")
        return True
```

Only `status` and `name` are patchable via `update_user_project()`. All other
columns (`camera_count`, `confidence_score`, etc.) are set only at creation time.
This is intentional: the sync pipeline writes those values once; the UI can only
rename or mark a project complete.

---

## 6 — Database Engine Selection (`_database_url`)

**Source:** `synccut/api/db.py`, lines 115–155

```python
def _database_url() -> str | URL:
    from synccut.paths import is_frozen

    desktop_mode = os.environ.get("SYNCCUT_DESKTOP", "").strip() in {"1", "true", "yes"}
    if is_frozen() or desktop_mode:
        return URL.create("sqlite", database=str(_get_db_path()))

    configured = os.environ.get("DATABASE_URL")
    if configured:
        if configured.startswith("postgres://"):
            configured = "postgresql://" + configured[len("postgres://"):]
        return configured
    return URL.create("sqlite", database=str(_get_db_path()))
```

### 6.1 Decision tree

```
is_frozen() == True?        → SQLite at %LOCALAPPDATA%\SyncCutStudio\synccut.db
  ↓ no
SYNCCUT_DESKTOP == "1"?     → SQLite at %LOCALAPPDATA%\SyncCutStudio\synccut.db
  ↓ no
DATABASE_URL env set?       → PostgreSQL (after postgres:// → postgresql:// fix)
  ↓ no
                            → SQLite fallback (same path as desktop)
```

`is_frozen()` detects that the code is running inside a PyInstaller bundle
(`sys.frozen == True`). `SYNCCUT_DESKTOP` is set to `"1"` by `factory.py`
when `is_frozen()` is true, and also when the user launches the desktop app
without freezing (development mode with the MSIX environment):

```python
# factory.py – create_app(), line 87
os.environ.setdefault(
    "SYNCCUT_DESKTOP",
    "1" if is_frozen() else os.environ.get("SYNCCUT_DESKTOP", "0")
)
```

### 6.2 `postgres://` → `postgresql://` fix

SQLAlchemy 1.4+ dropped support for the `postgres://` scheme (Heroku/Render
historically used this). The one-liner substitution ensures `DATABASE_URL`
provided by hosting platforms still works without manual correction.

### 6.3 `check_same_thread=False` for SQLite

```python
# db.py – _engine_and_sessions(), line 135
connect_args = {"check_same_thread": False} if str(database_url).startswith("sqlite") else {}
```

By default, Python's `sqlite3` module raises a `ProgrammingError` if a
connection created on one thread is used on another. Flask serves requests on
multiple threads; without this flag every request other than the first would
fail. `check_same_thread=False` disables this guard while SQLAlchemy's own
connection pool handles thread safety correctly.

### 6.4 `pool_pre_ping=True`

```python
engine = create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)
```

`pool_pre_ping` causes SQLAlchemy to issue a lightweight `SELECT 1` before
handing a pooled connection to the application. If the connection has gone stale
(e.g., the PostgreSQL server on Render restarted, or the cloud database timed out
an idle connection), the ping fails, the connection is discarded, and a fresh one
is opened — all transparently. Without this, the first request after a database
restart would fail with an `OperationalError`.

### 6.5 PostgreSQL unreachable fallback

```python
# db.py – _engine_and_sessions(), lines 141–150
except Exception as e:
    if not str(database_url).startswith("sqlite"):
        import logging
        logging.getLogger(__name__).warning(
            "Could not connect to external DATABASE_URL (%s): %s. Falling back to local SQLite.",
            database_url, e
        )
        sqlite_url = URL.create("sqlite", database=str(_get_db_path()))
        key = str(sqlite_url)
        engine = create_engine(sqlite_url, pool_pre_ping=True, connect_args={"check_same_thread": False})
    else:
        raise
```

If the PostgreSQL connection probe fails (network issue, bad credentials), the
engine silently falls back to local SQLite and logs a warning. This prevents the
application from completely failing to start in an environment where the database
host is temporarily unreachable.

---

## 7 — Migration Strategy (`_ensure_legacy_columns`)

**Source:** `synccut/api/db.py`, lines 172–206

SyncCut does **not** use Alembic or any migration framework. Schema changes
after the initial launch are applied by `_ensure_legacy_columns()`, which is
called from `init_db()` on every application startup.

```python
def _ensure_legacy_columns(engine: Engine) -> None:
    """Add fields introduced after the original SQLite schema was created."""
    inspector = inspect(engine)
    migrations = {
        "users": {
            "hashed_password": "VARCHAR(512)",
            "name":            "VARCHAR(120) NOT NULL DEFAULT ''",
            "password_hash":   "VARCHAR(256)",
            "salt":            "VARCHAR(64)",
            "token":           "VARCHAR(256)",
            "google_sub":      "VARCHAR(255)",
            "plan":            "VARCHAR(40) NOT NULL DEFAULT 'Free Plan'",
        },
        "projects": {
            "session_id": "VARCHAR(128) NOT NULL DEFAULT ''",
        },
    }
    with engine.begin() as connection:
        for table_name, columns in migrations.items():
            if table_name not in inspector.get_table_names():
                continue
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, column_type in columns.items():
                if column_name not in existing:
                    connection.execute(
                        text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
                    )
        if "users" in inspector.get_table_names():
            connection.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_google_sub ON users (google_sub)")
            )
        if "projects" in inspector.get_table_names():
            connection.execute(
                text("UPDATE projects SET session_id = id WHERE session_id IS NULL OR session_id = ''")
            )
```

### 7.1 How it works

1. `inspect(engine)` — uses SQLAlchemy's reflection to query the actual
   database schema (not the ORM models).
2. `inspector.get_table_names()` — if a table does not exist yet (first run),
   it is skipped; `Base.metadata.create_all()` already created it correctly.
3. `inspector.get_columns(table_name)` — returns the live schema; the set
   comprehension captures existing column names.
4. For each missing column, raw SQL `ALTER TABLE … ADD COLUMN` is executed. This
   is SQLite-compatible (SQLite supports `ADD COLUMN` since 3.1.3).
5. The function is **idempotent**: checking `if column_name not in existing`
   before executing means running it 100 times is the same as running it once.

### 7.2 Columns added post-launch

**`users` table:**

| Column | Added for |
|--------|-----------|
| `hashed_password` | Werkzeug password hashing migration |
| `name` | User display name feature |
| `password_hash` | Legacy compat (kept alongside `hashed_password`) |
| `salt` | Legacy compat salt column |
| `token` | Bearer auth token feature |
| `google_sub` | Google OAuth login feature |
| `plan` | Plan display label (redundant with Subscription.tier) |

**`projects` table:**

| Column | Added for |
|--------|-----------|
| `session_id` | Filesystem session linking feature |

### 7.3 Extra post-migration steps

After column additions, two more operations run:

- **`CREATE UNIQUE INDEX IF NOT EXISTS uq_users_google_sub`** — SQLAlchemy's
  `UniqueConstraint` in the ORM model only applies at table creation time
  (`create_all`). For existing tables this index must be created manually. The
  `IF NOT EXISTS` clause makes it idempotent.
- **`UPDATE projects SET session_id = id WHERE session_id IS NULL OR session_id = ''`**
  — backfills the new `session_id` column for all projects created before the
  column existed, using the project's own `id` as the session key (the original
  behavior before sessions were separate from projects).

---

## 8 — In-Memory State: `SESSIONS` and `LOCAL_JOBS`

**Source:** `synccut/api/routes.py`, lines 43–45

```python
SESSIONS: dict = {}
LOCAL_JOBS: dict = {}
LOCAL_CANCEL_EVENTS: dict = {}
```

These three module-level dictionaries are defined at the top of `routes.py`.
They are **plain Python dicts** — no Redis, no Memcached, no database backing.

### 8.1 `SESSIONS` — the media pipeline cache

`SESSIONS` is a `dict[session_id: str, dict]`. Each entry caches the in-memory
state for one upload session so it does not have to be re-read from disk on
every request:

```python
# routes.py – get_session(), lines 142–152
SESSIONS[session_id] = {
    "reference_path": None,       # Path to the designated master audio file
    "input_paths": [],            # All uploaded file paths in sorted order
    "all_signals": [],            # Pre-loaded numpy float32 audio arrays
    "fs": 16000,                  # Sample rate (always 16 kHz after decode)
    "report_results": report_results,  # Deserialized sync_report.json results
    "report_json_path": report_path if os.path.exists(report_path) else None,
    "media_dir": sdir,            # Absolute filesystem path to session directory
    "last_switches": None,        # Cached AI cut-list from generate_active_speaker_roughcut
    "last_switches_media_dir": sdir,
}
```

`get_session()` checks if the session is already in `SESSIONS`; if not, it
reads `sync_report.json` from disk and populates the cache. Subsequent requests
for the same `session_id` skip the disk read.

**`all_signals`** is the most important field: it holds the decoded 16 kHz mono
WAV data as numpy arrays in RAM. Loading all camera angles' audio (possibly
several hundred MB) into memory before sync means the GCC-PHAT cross-correlation
runs entirely in-process without repeated disk I/O.

### 8.2 `LOCAL_JOBS` — the in-process job queue

`LOCAL_JOBS` is a `dict[job_id: str, dict]`. Each job entry has the shape:

```python
{
    "status":   "PENDING" | "RUNNING" | "SUCCESS" | "FAILED" | "CANCELLED",
    "metadata": {
        "current":    <int>,          # Steps completed
        "total":      <int>,          # Total steps
        "changed_at": <float>,        # time.time() of last status change
    },
    "result":   { ... } | None,      # Final payload on SUCCESS
    "error":    "message" | None,    # On FAILED
}
```

The sync pipeline runs in a background thread (`threading.Thread`). Progress
updates are written to `LOCAL_JOBS[job_id]` by the `_store_local_progress()`
callback:

```python
# routes.py – _store_local_progress(), lines 189–200
def _store_local_progress(job_id: str, current, total, status: str):
    metadata = {"status": status}
    if current is not None and total is not None:
        metadata.update({"current": current, "total": total})
    ...
```

The frontend polls `GET /api/job/<job_id>/status`, which reads from `LOCAL_JOBS`
and returns the current progress. No database query is made for job status.

### 8.3 Why no Redis in desktop mode

| Factor | Desktop (in-memory) | Cloud (Celery + Redis) |
|--------|---------------------|------------------------|
| Complexity | Zero external dependencies | Redis + Celery worker processes |
| Latency | Nanoseconds (dict lookup) | Milliseconds (network + serialization) |
| Persistence | Lost on restart | Survives restart |
| Scale | Single process | Multiple workers |
| User count | 1 (local app) | N (SaaS) |

For the desktop app, there is exactly one user and one process. Using Redis
would require the user to install and run a Redis server — an unacceptable
prerequisite for a desktop application. In cloud mode on Render, Celery workers
in separate processes cannot share module-level dicts; Redis is the correct
shared broker for that topology.

### 8.4 What happens on restart

```
Process restart
  ↓
SESSIONS = {}   ← all cached audio signals, report caches cleared
LOCAL_JOBS = {} ← all job progress, results cleared
  ↓
users, projects, subscriptions → untouched in SQLite/PostgreSQL
session directories → untouched on disk
  ↓
User refreshes UI → sees projects (from DB) → status is "Draft" (last DB write)
User clicks "Check Status" on a running job → 404 (job_id not in LOCAL_JOBS)
```

The user experience impact: a restart during an active sync job loses the
progress report. The uploaded files remain on disk so the user can re-trigger
sync without re-uploading.

---

## 9 — Filesystem Session Structure

**Source:** `synccut/paths.py`, lines 68–71; `synccut/api/routes.py`, lines 89–153

### 9.1 Root directory resolution

```python
# paths.py – get_sessions_dir(), lines 68–71
def get_sessions_dir() -> Path:
    path = get_user_data_dir() / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path
```

`get_user_data_dir()` resolves to `%LOCALAPPDATA%\SyncCutStudio` on Windows.
The full session root is therefore:

```
C:\Users\<username>\AppData\Local\SyncCutStudio\sessions\
```

### 9.2 Per-session directory anatomy

```
sessions/
└── a3f9b2c1d4e5/              ← session_id (uuid4().hex[:12] = 12 hex chars)
    ├── .owner.json            ← {"user_id": "usr_abcdef1234567890"}
    ├── 01_camera_A.mp4        ← prefixed original upload #1
    ├── 02_camera_B.mp4        ← prefixed original upload #2
    ├── 03_lav_mic.wav         ← prefixed original upload #3
    ├── camera_A_16k.wav       ← mono 16 kHz decoded audio for clip #1
    ├── camera_B_16k.wav       ← mono 16 kHz decoded audio for clip #2
    ├── lav_mic_16k.wav        ← mono 16 kHz decoded audio for clip #3
    ├── sync_report.json       ← {"offsets": [...], "results": [...], "master": "..."}
    ├── master_mix.wav         ← aligned mixdown of all clips
    ├── switches.json          ← AI active-speaker cut list (frame numbers)
    └── proxy/
        ├── camera_A_proxy.mp4 ← 720p H.264 proxy for browser playback
        └── camera_B_proxy.mp4
```

**File naming conventions:**

- `01_`, `02_`, … prefixes preserve upload order. FFmpeg pipeline stages use
  the prefix to determine which clip is "camera 1" vs "camera 2" in the
  timeline.
- `<name>_16k.wav` — stereo-to-mono converted, resampled to 16 kHz. This is
  the common format expected by the GCC-PHAT cross-correlation engine.
- `sync_report.json` — written by the sync pipeline at the end. Its `offsets`
  array drives timeline building; `master` names the reference clip.
- `master_mix.wav` — the aligned mixdown; can be downloaded by the user for
  external NLE work.
- `switches.json` — written by `generate_active_speaker_roughcut()`; consumed
  by `export_roughcut_fcpxml()`.
- `proxy/<name>_proxy.mp4` — transcoded to 720p H.264 by FFmpeg; served via
  `/api/session/<id>/file/<name>` for browser `<video>` playback.

### 9.3 `session_dir()` — path resolution with traversal protection

```python
# routes.py – session_dir(), lines 89–95
def session_dir(session_id: str) -> str:
    root = os.path.realpath(_upload_root())
    d = os.path.realpath(os.path.join(root, session_id))
    if os.path.commonpath([root, d]) != root:
        raise ValueError("Invalid session identifier.")
    os.makedirs(d, exist_ok=True)
    return d
```

`os.path.realpath()` resolves symlinks and `..` components before the
`commonpath` check. A `session_id` of `"../../etc"` would resolve to a path
outside `root`, fail the `commonpath` check, and raise `ValueError` before any
filesystem operation occurs.

### 9.4 `_claim_session()` — ownership enforcement

```python
# routes.py – _claim_session(), lines 98–124
def _claim_session(session_id: str, user_id: str):
    if not isinstance(session_id, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", session_id
    ):
        return None, (jsonify({"error": "Missing session_id."}), 400)
    try:
        sdir = session_dir(session_id)
    except ValueError:
        return None, (jsonify({"error": "Invalid session identifier."}), 400)

    owner_path = os.path.join(sdir, ".owner.json")
    if os.path.isfile(owner_path):
        try:
            with open(owner_path, "r", encoding="utf-8") as owner_file:
                owner_id = json.load(owner_file).get("user_id")
        except (OSError, json.JSONDecodeError, AttributeError):
            return None, (jsonify({"error": "Session ownership could not be verified."}), 403)
        if owner_id != user_id:
            return None, (jsonify({"error": "This session belongs to another account."}), 403)
        return sdir, None

    with os.scandir(sdir) as entries:
        if next(entries, None) is not None:
            return None, (jsonify({"error": "This session cannot be claimed."}), 403)
    with open(owner_path, "w", encoding="utf-8") as owner_file:
        json.dump({"user_id": user_id}, owner_file)
    return sdir, None
```

**Three-layer security:**

1. **Regex validation** — `r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}"` allows only
   alphanumerics, hyphens, and underscores; rejects dots, slashes, null bytes.
2. **`commonpath` check** — in `session_dir()`, prevents any resolved path that
   escapes the sessions root directory.
3. **Ownership check** — `.owner.json` is written on first claim (when the
   directory is empty). A second user attempting to claim the same non-empty
   unclaimed directory is rejected with 403. If `.owner.json` exists, the
   stored `user_id` must match the authenticated user.

The `scandir` check prevents one user from "squatting" a session directory
created by another user: if the directory already has files in it but no
`.owner.json`, it is treated as already in use and cannot be claimed.

---

## 10 — Where Other App Data Lives

All runtime data for the desktop app lives under `%LOCALAPPDATA%\SyncCutStudio`.
This location is writable under MSIX's filesystem virtualisation and survives
across app updates.

```
%LOCALAPPDATA%\SyncCutStudio\
├── synccut.db              ← SQLite database (users, projects, subscriptions)
├── .flask_secret_key       ← 32-byte hex string, auto-generated once by factory.py
├── startup.log             ← desktop launcher log (RotatingFileHandler 3 MB × 3)
├── backend_error.log       ← Flask/synccut package logger (5 MB × 3 as configured)
├── sessions\               ← per-session media directories (see Section 9)
├── audio_cache\            ← cached decoded WAV files for reuse
├── results\                ← export outputs (FCPXML, EDL, OTIO files)
└── tmp\                    ← Werkzeug multipart upload buffer + tempfile.tempdir
```

**Source:** `synccut/paths.py`

```python
# paths.py – module-level, lines 177–181
_SCRATCH_DIR = str(get_temp_dir())
tempfile.tempdir = _SCRATCH_DIR
os.environ["TMPDIR"] = _SCRATCH_DIR
os.environ["TEMP"]   = _SCRATCH_DIR
os.environ["TMP"]    = _SCRATCH_DIR
```

Setting all four of these is necessary because Werkzeug reads `TMPDIR`/`TEMP`/`TMP`
(platform-dependent) to decide where to buffer incoming multipart file data.
Under MSIX, the default `TEMP` pointed to the sandboxed app-specific temp
directory which had a small quota; large video uploads would fail with
`OSError: [Errno 28] No space left on device`. Redirecting all temp pointers to
`%LOCALAPPDATA%\SyncCutStudio\tmp` bypasses the sandbox limitation.

**`.flask_secret_key` generation** (from `factory.py`):

```python
def _get_secret_key() -> str:
    configured = os.environ.get("SYNCCUT_SECRET_KEY")
    if configured:
        return configured
    secret_path = get_user_data_dir() / ".flask_secret_key"
    try:
        with secret_path.open("x", encoding="utf-8") as secret_file:  # "x" = exclusive create
            secret = secrets.token_hex(32)
            secret_file.write(secret)
            return secret
    except FileExistsError:
        return secret_path.read_text(encoding="utf-8").strip()
```

`open("x")` raises `FileExistsError` if the file already exists, making the
"generate once" behavior atomic without a separate existence check. Flask uses
this secret for HMAC-signing session cookies (used only for OAuth PKCE state).

---

## 11 — Stateless vs. Stateful Analysis

Understanding which layer is stateless and which is stateful is essential for
reasoning about horizontal scaling, restarts, and debugging.

### 11.1 HTTP layer — stateless

```
Client                             Server (Flask)
  │                                      │
  ├─ Authorization: Bearer <token> ─────►│
  │                                      ├─ SELECT * FROM users WHERE token = ?
  │                                      ├─ g.current_user = { id, email, tier }
  │◄──────────────────── response ───────┤
```

No session cookie is set for authenticated API requests. The token is in
`localStorage`, not in a cookie. The server holds no per-client session state;
every request is self-contained. This means:

- Any number of server instances behind a load balancer will handle any request
  correctly without sticky sessions.
- Revocation is instant: `users.token = NULL` in the DB immediately invalidates
  all in-flight tokens for that user.

### 11.2 In-memory layer — stateful per process

`SESSIONS` and `LOCAL_JOBS` are module-level singletons. They are:

- **Not shared** across multiple Flask worker processes (Gunicorn `--workers > 1`
  would have independent dicts per worker).
- **Lost** on process restart.
- **Fast**: nanosecond dict lookups vs. millisecond DB round-trips.

The desktop app runs as a single Flask process (`threaded=True`), so the
in-memory approach is correct. The cloud deployment uses a single Gunicorn
worker for the Flask app + a separate Celery worker for heavy sync jobs; in this
topology `LOCAL_JOBS` is not used for Celery tasks (they use Redis).

### 11.3 Database layer — durable stateful

Users, subscriptions, and projects persist across all restarts and deployments.
SQLite in desktop mode is a single file; PostgreSQL in cloud mode has its own
backup and HA story managed by Render.

### 11.4 Flask `session` cookie — OAuth dance only

```python
# routes.py (OAuth callback handler, conceptual)
session["oauth_state"] = state   # Written before redirect to Google
session["nonce"] = nonce         # Written before redirect to Google
# ... Google redirects back ...
assert session.pop("oauth_state") == request.args["state"]  # PKCE validation
```

Flask's `session` (a signed cookie) is **only** used during the Google OAuth
redirect dance to store `oauth_state` and `nonce` between the initial redirect
and the callback. It is cleared after the callback. Using a cookie here is
correct because the state must survive an HTTP redirect round-trip where the
server cannot look up the state by user (the user is not yet authenticated).

---

## 12 — Key Interview Q&A

### Q: If the server restarts, do uploads survive?

**A:** Partially. Uploaded files on disk under `sessions/<session_id>/` survive
because they are written to `%LOCALAPPDATA%`, which is not affected by a process
restart. The sync job's progress (in `LOCAL_JOBS`) is lost entirely. The user
will see the project in the "Draft" status (the last value written to SQLite),
but `GET /api/job/<job_id>/status` will return 404 because the job ID is gone
from the in-memory dict. The user must re-trigger sync (not re-upload).

### Q: How does the app know which files belong to which user?

**A:** `.owner.json` is written to the session directory by `_claim_session()`
the first time a user uploads to that session. It contains `{"user_id": "usr_…"}`.
Every route that accesses session files reads `.owner.json` and compares the
stored `user_id` to `g.current_user["id"]`. If they differ, the route returns
403. See `_claim_session()` and `_owned_session_dir()` in `routes.py`.

### Q: Can a user have multiple projects?

**A:** Yes. `Project.user_id` is a foreign key (not unique), so the table can
hold many rows with the same `user_id`. `get_user_projects(user_id)` returns all
of them ordered by `created_at DESC`:

```python
# db.py – get_user_projects(), lines 492–512
projects = session.scalars(
    select(Project).where(Project.user_id == user_id).order_by(Project.created_at.desc())
).all()
```

### Q: Is there row-level security?

**A:** Not at the database level. SQLite and PostgreSQL do not enforce
row-level security in this schema. Ownership is enforced in Python: every route
that touches a project calls `select(Project).where(Project.id == project_id, Project.user_id == user_id)`. If `user_id` does not match, the query returns `None`
and the route returns 404 (not 403, to avoid leaking existence).

```python
# db.py – update_user_project(), lines 565–568
project = session.scalar(
    select(Project).where(Project.id == project_id, Project.user_id == user_id)
)
if project is None:
    return False
```

### Q: What prevents directory traversal in session file serving?

**A:** `session_dir()` uses `os.path.realpath()` to resolve the constructed path
(collapsing `..`, symlinks) and then `os.path.commonpath([root, d]) != root` to
verify the result is still inside the sessions root:

```python
# routes.py – session_dir(), lines 89–95
root = os.path.realpath(_upload_root())
d = os.path.realpath(os.path.join(root, session_id))
if os.path.commonpath([root, d]) != root:
    raise ValueError("Invalid session identifier.")
```

A `session_id` of `"../../../etc/passwd"` would resolve to a path whose
`commonpath` with `root` is an ancestor of `root` (not `root` itself), failing
the check and raising `ValueError` before `makedirs` is called.

### Q: Why does `create_user_project` use `session.merge()` instead of `session.add()`?

**A:** `session.merge()` performs an upsert by primary key: if a `projects` row
with the given `id` already exists, it is updated; if not, it is inserted.
`session.add()` would raise an `IntegrityError` on a duplicate primary key.
Using `merge()` makes the endpoint idempotent — the same project can be
"created" multiple times from the frontend (e.g., after a network retry) without
errors.

### Q: What is the difference between a "session" and a "project"?

**A:** They are related but distinct concepts:
- A **session** (`session_id`) is a filesystem working directory. It is created
  by `POST /api/session` before any files are uploaded, and exists as a
  directory under `sessions/`. It is identified by a 12-character hex UUID.
- A **project** is a SQLite row in the `projects` table. It stores metadata
  (name, status, confidence score, timestamps). It is created later by
  `POST /api/session/<id>/project` and has a `proj-<12hex>` ID.

The project's `session_id` column links the metadata row to the filesystem
directory. In the happy path the values are different. In the fallback path
(project created without a prior session), `session_id` is set to `project_id`.

### Q: How does two-password-column authentication work in practice?

**A:** `authenticate_user()` checks `hashed_password` first (Werkzeug format).
If that column is `NULL` (old account pre-migration), it falls back to the
legacy `verify_password(password, salt, password_hash)` using PBKDF2-SHA256.
On a successful login, a new `token` is always generated regardless of which
path was taken. The two-column approach means no forced migration run; accounts
self-upgrade the next time the user changes their password via forgot-password
(which writes both columns).

### Q: What happens to `LOCAL_JOBS` in a multi-worker Gunicorn setup?

**A:** Each Gunicorn worker has its own independent `LOCAL_JOBS` dict. A request
that starts a job on worker A will only find that job's status if it hits worker
A again. This is a known limitation. In practice, the cloud deployment uses
Celery with Redis for job state, so `LOCAL_JOBS` is only the in-process fallback
for the desktop/single-worker mode.

### Q: How is `pool_pre_ping` different from connection timeout settings?

**A:** `pool_pre_ping=True` validates connections *at checkout time* (before
handing them to the application). It does not set a network timeout during the
query itself. The effect is: if a pooled connection has been idle long enough
for the database server to close it (common with PaaS databases that close
connections after ~5 minutes of idle), the stale connection is detected and
replaced before the application sees it. Without `pool_pre_ping`, the first
request after a long idle period would receive a broken connection and fail.

---

*Last updated: Nov 19, 2026 — covers db.py (575 lines), paths.py (181 lines),
factory.py (179 lines), routes.py (session management, lines 43–174).*
