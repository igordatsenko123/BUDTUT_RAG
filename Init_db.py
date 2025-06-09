from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import Column, BigInteger, String, DateTime
from datetime import datetime
import asyncio
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL").replace("postgresql://", "postgresql+asyncpg://")

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    tg_id = Column(BigInteger, primary_key=True, index=True)
    first_name = Column(String(255))
    last_name = Column(String(255))
    phone = Column(String(255))
    speciality = Column(String(255))
    experience = Column(String(255))
    username = Column(String(255))
    ref_source = Column(String(255))  # ← Нове поле для джерела переходу
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def init_db():
    async with engine.begin() as conn:
        print("❌ Видаляємо стару таблицю...")
        await conn.run_sync(Base.metadata.drop_all)
        print("✅ Створюємо нову таблицю...")
        await conn.run_sync(Base.metadata.create_all)
    print("🎉 Таблиця users успішно пересоздана")

if __name__ == "__main__":
    asyncio.run(init_db())
