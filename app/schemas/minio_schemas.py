from pydantic import BaseModel, Field

class CreateFolderBody(BaseModel):
    full_path: str = Field(..., min_length=1)

class RenameFolderBody(BaseModel):
    old_path: str = Field(..., min_length=1)
    new_path: str = Field(..., min_length=1)

class RenameObjectBody(BaseModel):
    object_key: str = Field(..., min_length=1)
    new_name: str = Field(..., min_length=1)
