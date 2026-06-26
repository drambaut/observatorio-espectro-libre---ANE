from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Regulator(Base):
    __tablename__ = "regulators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    short_name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    country: Mapped[str | None] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(120))
    url_base: Mapped[str | None] = mapped_column(String(500))
    url_news: Mapped[str | None] = mapped_column(String(500))
    url_search: Mapped[str | None] = mapped_column(String(500))
    language: Mapped[str | None] = mapped_column(String(20))
    priority: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    documents = relationship("Document", back_populates="regulator")
