from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    import uuid


@runtime_checkable
class AuthPrincipal(Protocol):
    """Structural shape shared by `Customer` and `Staff` (S0 §7.2)."""

    @property
    def id(self) -> uuid.UUID: ...

    @property
    def email(self) -> str: ...

    @property
    def password_hash(self) -> str: ...

    @property
    def role(self) -> Any: ...

    @property
    def is_authenticated(self) -> bool: ...

    @property
    def is_active(self) -> bool: ...

    @property
    def is_anonymous(self) -> bool: ...

    def get_id(self) -> str: ...
