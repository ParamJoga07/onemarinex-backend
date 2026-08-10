from sqlalchemy import Column, Integer, String, Boolean, DateTime, event, func
from app.db.base import Base
from app.services.port_identity import canonical_port_code, canonical_port_key

class Port(Base):
    __tablename__ = "ports"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    code = Column(String(100), unique=True, index=True, nullable=False) # e.g. port_vishakapatnam
    canonical_key = Column(String(255), unique=True, index=True, nullable=False)
    is_active = Column(Boolean, default=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<Port id={self.id} name={self.name} code={self.code}>"


@event.listens_for(Port, "before_insert")
@event.listens_for(Port, "before_update")
def _set_port_canonical_key(_mapper, _connection, target: Port) -> None:
    target.canonical_key = canonical_port_key(target.name or target.code)
    target.code = canonical_port_code(target.name or target.code)
