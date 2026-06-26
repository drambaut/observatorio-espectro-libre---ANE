from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ScrapingRun(Base):
    __tablename__ = "scraping_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    keywords_used: Mapped[str | None] = mapped_column(Text)
    total_sites: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_saved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    documents = relationship("Document", back_populates="scraping_run")
