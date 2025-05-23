from sqlalchemy import select
from models import User
from db import SessionLocal

async def insert_or_update_user(tg_id, first_name, last_name, phone, speciality, experience, company, username, updated_at):
    async with SessionLocal() as session:
        user = await session.get(User, tg_id)
        if not user:
            user = User(
                tg_id=tg_id,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                speciality=speciality,
                experience=experience,
                company=company,
                username=username,
                updated_at=updated_at
            )
            session.add(user)
        else:
            user.first_name = first_name
            user.last_name = last_name
            user.phone = phone
            user.speciality = speciality
            user.experience = experience
            user.company = company
            user.username = username
            user.updated_at = updated_at
        await session.commit()

async def is_registered(tg_id: int) -> bool:
    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.tg_id == tg_id))
        user = result.scalar_one_or_none()
        return user is not None