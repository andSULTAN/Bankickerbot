"""Declarative base shared by all models (and by Alembic autogenerate)."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
