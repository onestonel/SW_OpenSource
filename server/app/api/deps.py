"""API 함수가 공통으로 받는 값."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from ..db import get_db

DB = Annotated[Session, Depends(get_db)]
