from pydantic import BaseModel, Field
class LoginIn(BaseModel): email:str; password:str
class RegisterIn(BaseModel): name:str=""; email:str; password:str=Field(min_length=6)
class PaymentIn(BaseModel): plan:str; txid:str=Field(min_length=3)
