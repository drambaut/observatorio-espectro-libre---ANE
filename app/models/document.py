from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    regulator_id: Mapped[int] = mapped_column(ForeignKey("regulators.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True, index=True)
    content_excerpt: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(20))
    doc_type: Mapped[str | None] = mapped_column(String(80))
    publish_date: Mapped[date | None] = mapped_column(Date)
    extraction_date: Mapped[datetime | None] = mapped_column(DateTime)
    keyword_matched: Mapped[str | None] = mapped_column(String(255))
    scraping_run_id: Mapped[int | None] = mapped_column(ForeignKey("scraping_runs.id"), index=True)
    has_attachment: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    attachment_url: Mapped[str | None] = mapped_column(String(1000))
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="new", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    regulator = relationship("Regulator", back_populates="documents")
    scraping_run = relationship("ScrapingRun", back_populates="documents")
    topics = relationship("DocumentTopic", back_populates="document", cascade="all, delete-orphan")


class DocumentTopic(Base):
    __tablename__ = "document_topics"

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id"),
        primary_key=True,
    )
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("topics.id"),
        primary_key=True,
    )
    score: Mapped[float | None] = mapped_column(Float)

    document = relationship("Document", back_populates="topics")
    topic = relationship("Topic", back_populates="documents")
