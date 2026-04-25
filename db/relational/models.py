from sqlalchemy import Column, String, Text, DateTime, Integer, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from backend.dependencies import Base

class Memory(Base):
    __tablename__ = "memories"
    
    id = Column(String(32), primary_key=True, index=True)
    content = Column(Text, nullable=False)
    type = Column(String(20), nullable=False, index=True)  # cli_command / project_decision / user_preference
    source = Column(String(20), nullable=False, index=True)  # cli / feishu_group / feishu_doc
    user_id = Column(String(64), index=True)
    team_id = Column(String(64), index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expire_at = Column(DateTime, index=True)
    hit_count = Column(Integer, default=0)
    
    decision = relationship("DecisionMemory", back_populates="memory", uselist=False)

class DecisionMemory(Base):
    __tablename__ = "decision_memories"
    
    id = Column(String(32), ForeignKey("memories.id"), primary_key=True)
    topic = Column(Text, nullable=False, index=True)
    conclusion = Column(Text, nullable=False)
    reason = Column(Text)
    related_persons = Column(Text)
    deadline = Column(DateTime, index=True)
    
    memory = relationship("Memory", back_populates="decision")
