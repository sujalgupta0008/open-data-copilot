from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import hash_password, verify_password, create_access_token
from app.models.models import User
from app.schemas.schemas import UserCreate, UserLogin, TokenOut, UserOut
from app.core.deps import get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"], redirect_slashes=False)

@router.post("/register", response_model=TokenOut)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(email=payload.email, password_hash=hash_password(payload.password), name=payload.name)
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token({"sub": user.id})
    # BYOS: auto-create Google Drive workspace folder upon first user login/registration
    try:
        from app.services.google_drive import GoogleDriveService
        svc = GoogleDriveService(user_id=user.id)
        svc.ensure_workspace_folder()
    except Exception:
        pass
    return {"access_token": token, "token_type": "bearer", "user": user}

@router.post("/login", response_model=TokenOut)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": user.id})
    # BYOS: auto-create workspace on login
    try:
        from app.services.google_drive import GoogleDriveService
        svc = GoogleDriveService(user_id=user.id)
        svc.ensure_workspace_folder()
    except Exception:
        pass
    return {"access_token": token, "token_type": "bearer", "user": user}

@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user

@router.post("/logout")
def logout(current_user: User = Depends(get_current_user)):
    return {"message": "Logged out"}
