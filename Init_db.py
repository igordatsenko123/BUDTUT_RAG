import asyncio
from db import engine, Base
from models import User  # Обязательно импортировать модель, чтобы она зарегистрировалась

async def init_models():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        print("✅ Таблицы успешно созданы")

if __name__ == "__main__":
    asyncio.run(init_models())

