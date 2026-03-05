from typing import Optional

from pydantic import BaseModel


class ResolveExceptionRequest(BaseModel):
    note: Optional[str] = None
