import pytest
from sqlalchemy import select
from db import Base, User, SessionLocal, engine, hash_password, verify_password, valid_email

@pytest.mark.asyncio
async def test_database_and_password():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as s:
        email="test@example.com"
        existing=(await s.execute(select(User).where(User.email==email))).scalar_one_or_none()
        if existing: await s.delete(existing); await s.commit()
        u=User(name="Test",email=email,password_hash=hash_password("StrongPass123"))
        s.add(u); await s.commit()
        assert verify_password("StrongPass123",u.password_hash)
        assert not verify_password("WrongPass123",u.password_hash)
        assert valid_email(email)
        assert not valid_email("bad-email")
        await s.delete(u); await s.commit()
