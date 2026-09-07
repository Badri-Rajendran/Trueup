"""Response schema for `app/controllers/api/profile.py` (ADR 27, OWASP API3).

Explicit allow-list only -- never a raw `Customer` entity (it carries `password_hash`) --
`app/views/` may not import `app/models/`, enforced by `lint-imports`'s `views-are-not-entities`
contract. Deliberately narrow: only the fields `/profile` itself owns. The frontend gets
`id`/`email`/`role` from `/auth/session` and KYC/approval status from
`/identity/status/<id>` separately -- this view does not duplicate either.
"""

from __future__ import annotations

from pydantic import BaseModel


class ProfileResponse(BaseModel):
    """`GET|PATCH /api/v1/profile` -- `None` means the field was never set (ADR 27), not that it
    was cleared to empty; every pre-existing customer reads back with all three `None`."""

    display_name: str | None
    phone: str | None
    mailing_address: str | None
