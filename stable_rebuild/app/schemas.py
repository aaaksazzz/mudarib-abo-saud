from pydantic import BaseModel, Field, field_validator
import re

class LoginIn(BaseModel):
    email:str=Field(min_length=3,max_length=254)
    password:str=Field(min_length=6)

class RegisterIn(BaseModel):
    name:str=Field(default="",max_length=100)
    email:str=Field(min_length=3,max_length=254)
    password:str=Field(min_length=6,max_length=128)

    @field_validator("email")
    @classmethod
    def valid_email(cls,v):
        v=v.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",v):
            raise ValueError("البريد الإلكتروني غير صحيح")
        return v

    @field_validator("name")
    @classmethod
    def clean_name(cls,v):
        return v.strip()

class PaymentIn(BaseModel):
    plan:str
    txid:str=Field(min_length=3,max_length=200)

    @field_validator("plan")
    @classmethod
    def valid_plan(cls,v):
        if v not in ("7d","30d","90d"):
            raise ValueError("الباقة غير صحيحة")
        return v

    @field_validator("txid")
    @classmethod
    def clean_txid(cls,v):
        return v.strip()
