from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy metadata root. Business tables register by importing app.models."""
