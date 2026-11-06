"""SQLAlchemy persistence for users, subscriptions, and projects."""
from __future__ import annotations

import hashlib
import os
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    URL,
    create_engine,
    func,
    inspect,
    or_,
    select,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from werkzeug.security import check_password_hash, generate_password_hash

from synccut.paths import get_user_data_dir

_DB_PATH: Path | None = None
_ENGINES: dict[str, Engine] = {}
_SESSION_FACTORIES: dict[str, sessionmaker[Session]] = {}


class Base(DeclarativeBase):
    pass


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
    plan: Mapped[str] = mapped_column(String(40), nullable=False, default="Free Plan")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


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


def _get_db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        _DB_PATH = get_user_data_dir() / "synccut.db"
    return _DB_PATH


def _database_url() -> str | URL:
    configured = os.environ.get("DATABASE_URL")
    if configured:
        if configured.startswith("postgres://"):
            configured = "postgresql://" + configured[len("postgres://") :]
        return configured
    return URL.create("sqlite", database=str(_get_db_path()))


def _engine_and_sessions() -> tuple[Engine, sessionmaker[Session]]:
    database_url = _database_url()
    key = str(database_url)
    engine = _ENGINES.get(key)
    if engine is None:
        connect_args = {"check_same_thread": False} if str(database_url).startswith("sqlite") else {}
        engine = create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)
        _ENGINES[key] = engine
        _SESSION_FACTORIES[key] = sessionmaker(bind=engine, expire_on_commit=False)
    return engine, _SESSION_FACTORIES[key]


@contextmanager
def _session_scope() -> Generator[Session, None, None]:
    _, factory = _engine_and_sessions()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _ensure_legacy_columns(engine: Engine) -> None:
    """Add fields introduced after the original SQLite schema was created."""
    inspector = inspect(engine)
    migrations = {
        "users": {
            "hashed_password": "VARCHAR(512)",
            "name": "VARCHAR(120) NOT NULL DEFAULT ''",
            "password_hash": "VARCHAR(256)",
            "salt": "VARCHAR(64)",
            "token": "VARCHAR(256)",
            "plan": "VARCHAR(40) NOT NULL DEFAULT 'Free Plan'",
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
        if "projects" in inspector.get_table_names():
            connection.execute(
                text("UPDATE projects SET session_id = id WHERE session_id IS NULL OR session_id = ''")
            )


def init_db() -> None:
    """Create SQLAlchemy tables and upgrade the original local SQLite schema."""
    engine, _ = _engine_and_sessions()
    if engine.dialect.name == "sqlite":
        _get_db_path().parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    _ensure_legacy_columns(engine)
    with _session_scope() as session:
        user_ids = session.scalars(select(User.id)).all()
        existing_ids = set(session.scalars(select(Subscription.user_id)).all())
        for user_id in user_ids:
            if user_id not in existing_ids:
                session.add(Subscription(user_id=user_id, tier="free"))


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Return a legacy PBKDF2 hash and salt for backwards-compatible storage."""
    salt = salt or secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000
    ).hex()
    return salt, hashed


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    _, calculated = hash_password(password, salt)
    return secrets.compare_digest(calculated, expected_hash)


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


def _user_payload(user: User, subscription: Subscription | None) -> dict:
    tier = _tier_for(subscription)
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "tier": tier,
        "plan": {"free": "Free Plan", "pro": "Pro Plan", "studio": "Studio Plan"}[tier],
    }


def create_user(email: str, name: str, password: str) -> dict:
    email_clean = email.strip().lower()
    name_clean = name.strip() if name and name.strip() else email_clean.split("@")[0]
    salt, legacy_hash = hash_password(password)
    user = User(
        id=f"usr_{secrets.token_hex(8)}",
        email=email_clean,
        name=name_clean,
        hashed_password=generate_password_hash(password),
        password_hash=legacy_hash,
        salt=salt,
        token=secrets.token_urlsafe(32),
        plan="Free Plan",
    )
    with _session_scope() as session:
        session.add(user)
        session.flush()
        session.add(Subscription(user_id=user.id, tier="free"))
        result = _user_payload(user, None)
        result["token"] = user.token
        return result


def authenticate_user(email_or_username: str, password: str) -> dict | None:
    identifier = email_or_username.strip().lower()
    with _session_scope() as session:
        user = session.scalar(
            select(User).where(
                or_(func.lower(User.email) == identifier, func.lower(User.name) == identifier)
            )
        )
        if user is None:
            return None

        valid = False
        if user.hashed_password:
            valid = check_password_hash(user.hashed_password, password)
        elif user.salt and user.password_hash:
            valid = verify_password(password, user.salt, user.password_hash)
        if not valid:
            return None

        user.token = secrets.token_urlsafe(32)
        subscription = session.get(Subscription, user.id)
        result = _user_payload(user, subscription)
        result["token"] = user.token
        return result


def get_user_by_token(token: str) -> dict | None:
    if not token:
        return None
    with _session_scope() as session:
        user = session.scalar(select(User).where(User.token == token))
        if user is None:
            return None
        return _user_payload(user, session.get(Subscription, user.id))


def revoke_user_token(token: str) -> None:
    if not token:
        return
    with _session_scope() as session:
        user = session.scalar(select(User).where(User.token == token))
        if user is not None:
            user.token = None


def get_user_tier(user_id: str) -> str:
    with _session_scope() as session:
        return _tier_for(session.get(Subscription, user_id))


def get_subscription_info(user_id: str) -> dict:
    with _session_scope() as session:
        subscription = session.get(Subscription, user_id)
        tier = _tier_for(subscription)
        expires_at = subscription.expires_at if subscription else None
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return {
            "tier": tier,
            "expires_at": expires_at.isoformat() if expires_at else None,
        }


def get_stripe_customer_id(user_id: str) -> str | None:
    with _session_scope() as session:
        subscription = session.get(Subscription, user_id)
        return subscription.stripe_customer_id if subscription else None


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


def downgrade_subscription(
    subscription_id: str | None, customer_id: str | None
) -> bool:
    with _session_scope() as session:
        subscription = None
        if subscription_id:
            subscription = session.scalar(
                select(Subscription).where(Subscription.stripe_subscription_id == subscription_id)
            )
        if subscription is None and customer_id:
            subscription = session.scalar(
                select(Subscription).where(Subscription.stripe_customer_id == customer_id)
            )
        if subscription is None:
            return False
        if subscription_id and subscription.stripe_subscription_id != subscription_id:
            return False
        subscription.tier = "free"
        subscription.stripe_subscription_id = None
        subscription.expires_at = None
        user = session.get(User, subscription.user_id)
        if user is not None:
            user.plan = "Free Plan"
        return True


def get_user_projects(user_id: str) -> list[dict]:
    with _session_scope() as session:
        projects = session.scalars(
            select(Project).where(Project.user_id == user_id).order_by(Project.created_at.desc())
        ).all()
        return [
            {
                "id": project.id,
                "name": project.name,
                "description": project.description or "",
                "status": project.status,
                "cameraCount": project.camera_count,
                "duration": project.duration or "00:00:00",
                "updatedAt": project.updated_at,
                "thumbnailUrl": project.thumbnail_url
                or "https://images.unsplash.com/photo-1574717024653-61fd2cf4d44d?auto=format&fit=crop&w=640&q=80",
                "confidenceScore": float(project.confidence_score or 1.0),
                "session_id": project.session_id,
            }
            for project in projects
        ]


def create_user_project(user_id: str, project_data: dict) -> dict:
    project_id = project_data.get("id") or f"proj-{secrets.token_hex(6)}"
    name = project_data.get("name") or "New Project"
    now = datetime.now(timezone.utc).strftime("%b %d, %Y")
    project = Project(
        id=project_id,
        user_id=user_id,
        session_id=project_data.get("session_id") or project_id,
        name=name,
        description=project_data.get("description", "Multicam editing session"),
        status=project_data.get("status", "Draft"),
        camera_count=int(project_data.get("cameraCount", 2)),
        duration=project_data.get("duration", "00:00:00"),
        thumbnail_url=project_data.get(
            "thumbnailUrl",
            "https://images.unsplash.com/photo-1574717024653-61fd2cf4d44d?auto=format&fit=crop&w=640&q=80",
        ),
        confidence_score=float(project_data.get("confidenceScore", 1.0)),
        created_at=now,
        updated_at=now,
    )
    with _session_scope() as session:
        session.merge(project)
        return {
            "id": project.id,
            "name": project.name,
            "description": project.description or "",
            "status": project.status,
            "cameraCount": project.camera_count,
            "duration": project.duration or "00:00:00",
            "thumbnailUrl": project.thumbnail_url,
            "confidenceScore": project.confidence_score,
            "updatedAt": project.updated_at,
            "session_id": project.session_id,
        }


def delete_user_project(user_id: str, project_id: str) -> bool:
    with _session_scope() as session:
        project = session.scalar(
            select(Project).where(Project.id == project_id, Project.user_id == user_id)
        )
        if project is None:
            return False
        session.delete(project)
        return True


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
