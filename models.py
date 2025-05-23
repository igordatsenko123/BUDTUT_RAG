from sqlalchemy import Column, Integer, BigInteger, String
from db import Base  # Base берётся из db.py

class User(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True, index=True)
    tg_id = Column(BigInteger, unique=True, nullable=False)
    first_name = Column(String(255))
    last_name = Column(String(255))
    phone = Column(String(50))
    speciality = Column(String(255))
    experience = Column(String(255))
    company = Column(String(255))
