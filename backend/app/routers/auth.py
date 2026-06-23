from fastapi import APIRouter, Depends, HTTPException, status

from ..schemas import LoginIn, TokenOut
from ..security import create_access_token, get_current_admin, verify_admin


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn) -> TokenOut:
    if not verify_admin(payload.username, payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    return TokenOut(access_token=create_access_token(payload.username), username=payload.username)


@router.get("/me")
def me(username: str = Depends(get_current_admin)) -> dict:
    return {"username": username}
