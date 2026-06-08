"""phant/repositories/base.py — shared repository behaviour."""

from __future__ import annotations

from typing import Generic, Optional, Type, TypeVar

from sqlalchemy.orm import Session

from database import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    model: Type[T]

    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, obj_id: str) -> Optional[T]:
        return self.db.get(self.model, obj_id)

    def add(self, obj: T, *, commit: bool = True) -> T:
        self.db.add(obj)
        if commit:
            self.db.commit()
            self.db.refresh(obj)
        else:
            self.db.flush()
        return obj

    def save(self, obj: T) -> T:
        self.db.commit()
        self.db.refresh(obj)
        return obj
