from pydantic import BaseModel, Field, ValidationError

class UserInfo(BaseModel):
    name: str
    uuid: str