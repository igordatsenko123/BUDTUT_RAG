from sqlalchemy import select
from models import User
from db import SessionLocal

async def insert_or_update_user(tg_id, first_name, last_name, phone, speciality, experience=None, company=None):
    async with SessionLocal() as session:
        async with session.begin():
            result = await session.execute(select(User).where(User.tg_id == tg_id))
            user = result.scalar_one_or_none()

            if user is None:
                user = User(
                    tg_id=tg_id,
                    first_name=first_name,
                    last_name=last_name,
                    phone=phone,
                    speciality=speciality,
                    experience=experience,
                    company=company
                )
                session.add(user)
            else:
                user.first_name = first_name
                user.last_name = last_name
                user.phone = phone
                user.speciality = speciality
                user.experience = experience
                user.company = company
