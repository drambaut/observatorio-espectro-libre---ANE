from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Keyword(Base):
    __tablename__ = "keywords"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    keyword_original: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    keyword_en: Mapped[str | None] = mapped_column(String(255))
    keyword_es: Mapped[str | None] = mapped_column(String(255))
    keyword_pt: Mapped[str | None] = mapped_column(String(255))
    keyword_ko: Mapped[str | None] = mapped_column(String(255))
    keyword_ar: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
