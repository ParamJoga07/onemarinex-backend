from sqlalchemy import Column, Integer, String, ForeignKey
from app.db.base import Base   # ✅ FIXED

class FileAsset(Base):
    __tablename__ = "file_assets"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    path = Column(String, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"))
