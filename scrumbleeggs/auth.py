"""User authentication, session management, and role-based authorization.

Provides password hashing (bcrypt), server-side session storage, rate limiting
via failed-attempt tracking, and admin bootstrap on first run.
"""
import logging
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (from environment)
# ---------------------------------------------------------------------------

SESSION_TTL_HOURS = int(os.getenv("SBE_SESSION_TTL_HOURS", "24"))
MAX_FAILED_ATTEMPTS = int(os.getenv("SBE_MAX_FAILED_ATTEMPTS", "5"))
LOCKOUT_MINUTES = int(os.getenv("SBE_LOCKOUT_MINUTES", "15"))
BCRYPT_COST = int(os.getenv("SBE_BCRYPT_COST", "12"))

VALID_ROLES = frozenset({"admin", "developer", "tester"})

_UTC = timezone.utc


# ---------------------------------------------------------------------------
# Domain objects
# ---------------------------------------------------------------------------


@dataclass
class User:
    """Authenticated user identity returned from session lookup.

    Attributes:
        id: UUID string.
        username: Unique login handle.
        email: Optional email address.
        role: One of 'admin', 'developer', 'tester'.
        is_active: False means the account is disabled.
        created_at: UTC datetime of account creation.
        last_login: UTC datetime of most recent successful login, or None.
    """

    id: str
    username: str
    email: Optional[str]
    role: str
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime] = None

    @property
    def is_admin(self) -> bool:
        """Return True if this user has the admin role."""
        return self.role == "admin"

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dictionary (no password hash)."""
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "last_login": self.last_login.isoformat() if self.last_login else None,
        }


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AuthError(Exception):
    """Raised when an authentication or authorization operation fails."""


class RateLimitError(AuthError):
    """Raised when a username/IP has exceeded the failed-login threshold."""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class AuthService:
    """Handles users, sessions, and rate limiting against a SQLAlchemy DB.

    Args:
        db: The ``Database`` facade from ``scrumbleeggs.db``.
    """

    def __init__(self, db) -> None:
        self._db = db

    # ── Password ──────────────────────────────────────────────────────

    def hash_password(self, password: str) -> str:
        """Hash a plaintext password with bcrypt.

        Args:
            password: Plaintext password (minimum 8 characters).

        Returns:
            bcrypt hash string safe to store in the database.

        Raises:
            ValueError: If the password is too short.
        """
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters.")
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=BCRYPT_COST))
        return hashed.decode()

    def verify_password(self, password: str, password_hash: str) -> bool:
        """Check a plaintext password against a stored bcrypt hash.

        Args:
            password: Plaintext candidate password.
            password_hash: Stored bcrypt hash.

        Returns:
            True if the password matches, False otherwise.
        """
        try:
            return bcrypt.checkpw(password.encode(), password_hash.encode())
        except Exception:
            return False

    # ── Users ─────────────────────────────────────────────────────────

    def create_user(
        self,
        username: str,
        password: str,
        role: str = "developer",
        email: Optional[str] = None,
    ) -> User:
        """Create a new user account.

        Args:
            username: Unique handle (3–32 chars, letters/digits/underscore/dash).
            password: Plaintext password (min 8 chars).
            role: One of 'admin', 'developer', 'tester'.
            email: Optional email address.

        Returns:
            The newly created User.

        Raises:
            ValueError: If username format or role is invalid.
            AuthError: If username or email is already taken.
        """
        # Import here to avoid circular imports at module load time
        from scrumbleeggs.db import UserModel

        username = username.strip()
        if len(username) < 3 or len(username) > 32:
            raise ValueError("Username must be 3–32 characters.")
        if not all(c.isalnum() or c in "_-" for c in username):
            raise ValueError("Username may only contain letters, digits, _ and -.")
        if role not in VALID_ROLES:
            raise ValueError(f"Invalid role '{role}'. Must be one of: {sorted(VALID_ROLES)}.")

        password_hash = self.hash_password(password)
        user_id = str(uuid.uuid4())
        now = datetime.now(_UTC)

        with self._db.session() as db:
            if db.query(UserModel).filter_by(username=username).first():
                raise AuthError(f"Username '{username}' is already taken.")
            if email and db.query(UserModel).filter_by(email=email).first():
                raise AuthError(f"Email '{email}' is already registered.")

            db.add(UserModel(
                id=user_id,
                username=username,
                email=email,
                password_hash=password_hash,
                role=role,
                is_active=1,
                created_at=now,
            ))
            db.commit()

        logger.info("Created user '%s' with role '%s'", username, role)
        return User(
            id=user_id, username=username, email=email,
            role=role, is_active=True, created_at=now,
        )

    def get_user_by_username(self, username: str) -> Optional[User]:
        """Fetch a user by username.

        Args:
            username: The username to look up.

        Returns:
            User if found, else None.
        """
        from scrumbleeggs.db import UserModel

        with self._db.session() as db:
            row = db.query(UserModel).filter_by(username=username).first()
            return self._row_to_user(row) if row else None

    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Fetch a user by UUID.

        Args:
            user_id: UUID string.

        Returns:
            User if found, else None.
        """
        from scrumbleeggs.db import UserModel

        with self._db.session() as db:
            row = db.query(UserModel).filter_by(id=user_id).first()
            return self._row_to_user(row) if row else None

    def list_users(self) -> list[User]:
        """Return all users ordered by username.

        Returns:
            List of User objects.
        """
        from scrumbleeggs.db import UserModel

        with self._db.session() as db:
            rows = db.query(UserModel).order_by(UserModel.username).all()
            return [self._row_to_user(r) for r in rows]

    def update_user(
        self,
        user_id: str,
        *,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
        email: Optional[str] = None,
        password: Optional[str] = None,
    ) -> User:
        """Update one or more fields on an existing user.

        Args:
            user_id: UUID of the user to update.
            role: New role if changing.
            is_active: New active flag if changing.
            email: New email if changing.
            password: New plaintext password if changing.

        Returns:
            Updated User.

        Raises:
            AuthError: If the user is not found.
            ValueError: If the new role is invalid.
        """
        from scrumbleeggs.db import UserModel

        if role is not None and role not in VALID_ROLES:
            raise ValueError(f"Invalid role '{role}'.")

        with self._db.session() as db:
            row = db.query(UserModel).filter_by(id=user_id).first()
            if not row:
                raise AuthError(f"User {user_id} not found.")
            if role is not None:
                row.role = role
            if is_active is not None:
                row.is_active = 1 if is_active else 0
            if email is not None:
                row.email = email
            if password is not None:
                row.password_hash = self.hash_password(password)
            db.commit()
            return self._row_to_user(row)

    def count_users(self) -> int:
        """Return the total number of user accounts in the database."""
        from scrumbleeggs.db import UserModel

        with self._db.session() as db:
            return db.query(UserModel).count()

    # ── Sessions ──────────────────────────────────────────────────────

    def create_session(self, user_id: str, ip_address: str) -> str:
        """Create a server-side session and return an opaque token.

        Args:
            user_id: UUID of the authenticated user.
            ip_address: Remote IP address for the audit trail.

        Returns:
            URL-safe random token (store in an httponly cookie).
        """
        from scrumbleeggs.db import SessionModel, UserModel

        token = secrets.token_urlsafe(32)
        now = datetime.now(_UTC)
        expires = now + timedelta(hours=SESSION_TTL_HOURS)

        with self._db.session() as db:
            db.add(SessionModel(
                token=token,
                user_id=user_id,
                created_at=now,
                expires_at=expires,
                ip_address=ip_address,
            ))
            user_row = db.query(UserModel).filter_by(id=user_id).first()
            if user_row:
                user_row.last_login = now
            db.commit()

        logger.info("Session created for user_id=%s from %s", user_id, ip_address)
        return token

    def get_session_user(self, token: str) -> Optional[User]:
        """Resolve a session token to the owning User.

        Expired sessions are deleted on access (lazy TTL enforcement).

        Args:
            token: Session token from the request cookie.

        Returns:
            Active User if the session is valid, else None.
        """
        from scrumbleeggs.db import SessionModel, UserModel

        if not token:
            return None

        now = datetime.now(_UTC)
        with self._db.session() as db:
            session = db.query(SessionModel).filter_by(token=token).first()
            if not session:
                return None
            exp = session.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=_UTC)
            if exp < now:
                db.delete(session)
                db.commit()
                return None
            user_row = db.query(UserModel).filter_by(id=session.user_id).first()
            if not user_row or not user_row.is_active:
                return None
            return self._row_to_user(user_row)

    def delete_session(self, token: str) -> None:
        """Invalidate a session (logout).

        Args:
            token: The session token to delete.
        """
        from scrumbleeggs.db import SessionModel

        with self._db.session() as db:
            session = db.query(SessionModel).filter_by(token=token).first()
            if session:
                db.delete(session)
                db.commit()
        logger.info("Session deleted (logout)")

    def purge_expired_sessions(self) -> int:
        """Remove all expired sessions from the database.

        Returns:
            Number of rows deleted.
        """
        from scrumbleeggs.db import SessionModel

        now = datetime.now(_UTC)
        with self._db.session() as db:
            deleted = (
                db.query(SessionModel)
                .filter(SessionModel.expires_at < now)
                .delete()
            )
            db.commit()
        if deleted:
            logger.info("Purged %d expired sessions", deleted)
        return deleted

    # ── Rate limiting ─────────────────────────────────────────────────

    def check_rate_limit(self, username: str, ip_address: str) -> None:
        """Raise RateLimitError if the username is currently locked out.

        Counts failed attempts in the last ``LOCKOUT_MINUTES`` minutes.

        Args:
            username: Attempted username.
            ip_address: Source IP (logged but not used for lockout keying).

        Raises:
            RateLimitError: If the failure threshold has been exceeded.
        """
        from scrumbleeggs.db import LoginAttemptModel

        cutoff = datetime.now(_UTC) - timedelta(minutes=LOCKOUT_MINUTES)
        with self._db.session() as db:
            failures = (
                db.query(LoginAttemptModel)
                .filter(
                    LoginAttemptModel.username == username,
                    LoginAttemptModel.success == 0,
                    LoginAttemptModel.attempted_at >= cutoff,
                )
                .count()
            )
        if failures >= MAX_FAILED_ATTEMPTS:
            logger.warning(
                "Rate limit triggered: username='%s' ip=%s failures=%d",
                username, ip_address, failures,
            )
            raise RateLimitError(
                f"Too many failed attempts. Try again in {LOCKOUT_MINUTES} minutes."
            )

    def record_login_attempt(
        self, username: str, ip_address: str, success: bool
    ) -> None:
        """Persist a login attempt for rate limiting and audit.

        Args:
            username: The username that was attempted.
            ip_address: Source IP address.
            success: Whether the attempt succeeded.
        """
        from scrumbleeggs.db import LoginAttemptModel

        with self._db.session() as db:
            db.add(LoginAttemptModel(
                id=str(uuid.uuid4()),
                username=username,
                ip_address=ip_address,
                attempted_at=datetime.now(_UTC),
                success=1 if success else 0,
            ))
            db.commit()

    # ── Bootstrap ─────────────────────────────────────────────────────

    def bootstrap_admin(self) -> Optional[str]:
        """Create a default admin account if the users table is empty.

        Reads SBE_ADMIN_USER and SBE_ADMIN_PASS from environment.
        If SBE_ADMIN_PASS is not set, generates a secure random password
        and prints it to the log (WARNING level so it's always visible).

        Returns:
            The plaintext password if a new admin was created, else None.
        """
        if self.count_users() > 0:
            return None

        admin_user = os.getenv("SBE_ADMIN_USER", "admin")
        admin_pass = os.getenv("SBE_ADMIN_PASS") or secrets.token_urlsafe(16)
        admin_email = os.getenv("SBE_ADMIN_EMAIL")

        self.create_user(admin_user, admin_pass, role="admin", email=admin_email)

        logger.warning(
            "\n"
            "╔══════════════════════════════════════════╗\n"
            "║     FIRST RUN — Admin account created    ║\n"
            "║                                          ║\n"
            "║  Username : %-28s║\n"
            "║  Password : %-28s║\n"
            "║                                          ║\n"
            "║  Set SBE_ADMIN_USER / SBE_ADMIN_PASS     ║\n"
            "║  in your .env to control these values.   ║\n"
            "╚══════════════════════════════════════════╝",
            admin_user,
            admin_pass,
        )
        return admin_pass

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _row_to_user(row) -> User:
        """Convert a UserModel ORM row to a User dataclass."""
        created = row.created_at
        if created and created.tzinfo is None:
            created = created.replace(tzinfo=_UTC)
        last = row.last_login
        if last and last.tzinfo is None:
            last = last.replace(tzinfo=_UTC)
        return User(
            id=row.id,
            username=row.username,
            email=row.email,
            role=row.role,
            is_active=bool(row.is_active),
            created_at=created or datetime.now(_UTC),
            last_login=last,
        )
