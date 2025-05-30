from sqlalchemy import Column, BigInteger, String, DateTime
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    tg_id = Column(BigInteger, primary_key=True, index=True)  # <- заменяем user_id
    first_name = Column(String)
    last_name = Column(String)
    phone = Column(String)
    speciality = Column(String)
    experience = Column(String)
    username = Column(String)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)