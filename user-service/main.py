# user-service/main.py
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from db import SessionLocal, engine, User  # ✅ 수정됨
from datetime import datetime
import os
import httpx
from fastapi.middleware.cors import CORSMiddleware
from typing import List
from fastapi import FastAPI, HTTPException, Path
from pydantic import BaseModel
import boto3
import json
from botocore.exceptions import BotoCoreError, ClientError

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://www.abysscm.com","http://www.abysscm.com:5173","http://www.abysscm.com:5174","http://admin.abysscm.com","http://admin.abysscm.com:5173","http://admin.abysscm.com:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class UserRequest(BaseModel):
    kakao_id: str  # 이메일 없이 카카오 ID만 사용
    nickname: str = None  # 조회용

class UserResponse(BaseModel):
    kakao_id: str
    nickname: str = None
    member_status: str  # '회원' 또는 '비회원'

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class AddUserRequest(BaseModel):
    username: str
    birthDate: str
    birthTime: str
    calendar: str
    ampm: str
    kakao_id: int
    userphonenumber: str | None = None  # 프론트에서 보내는 이름
    email: str = "noemail@example.com"  # 필수 컬럼이므로 기본값 지정
    gender: str | None = None
    matching_count: str = "0"
    status: str = "매칭전"

class UserOut(BaseModel):
    user_id: int
    name: str
    email: str | None
    phone_number: str | None
    age: str | None
    gender: str | None
    birth_date: str | None
    matching_count: int
    status: str
    first_consultation: str | None
    last_consultation: str | None
    consultation_count: int
    matched_partner: int | None

    class Config:
        orm_mode = True


# AWS S3 설정
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")


s3_client = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION
)

class UpdateUserRequest(BaseModel):
    job: str
    memo: str

class MatchRequest(BaseModel):
    partner_id: int

@app.post("/users/login-or-register", response_model=UserResponse)
def login_or_register(user_req: UserRequest, db: Session = Depends(get_db)):
    # 카카오 ID로 조회
    user = db.query(User).filter(User.user_id == int(user_req.kakao_id)).first()

    if user:
        return UserResponse(
            kakao_id=user_req.kakao_id,
            nickname=user_req.nickname,
            member_status="회원"
        )
    else:
        return UserResponse(
            kakao_id=user_req.kakao_id,
            nickname=user_req.nickname,
            member_status="비회원"
        )


@app.post("/users/add")
def add_user(data: AddUserRequest, db: Session = Depends(get_db)):
    # user_id = kakao_id 기준으로 중복 체크
    existing_user = db.query(User).filter(User.user_id == int(data.kakao_id)).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="이미 존재하는 사용자입니다.")

    # 나이 계산
    try:
        birth_date_obj = datetime.strptime(data.birthDate, "%Y-%m-%d")
        today = datetime.today()
        age = today.year - birth_date_obj.year
        if (today.month, today.day) < (birth_date_obj.month, birth_date_obj.day):
            age -= 1
        age_str = str(age)
    except Exception as e:
        age_str = ""
        print(f"Age 계산 오류: {e}")

    # 생년월일 + 시간 + 양력/음력 + 오전/오후
    birth_time = f"{data.birthTime[:2]}:{data.birthTime[2:]}"
    calendar_str = "양력" if data.calendar == "solar" else "음력"
    ampm_str = "오전" if data.ampm == "AM" else "오후"
    final_birth_str = f"{data.birthDate} {birth_time} {ampm_str} ({calendar_str})"

    # ✅ User 생성 (결제 필드 추가, 문법 수정)
    user = User(
        user_id=int(data.kakao_id),
        name=data.username,
        email=data.email or "noemail@example.com",
        phone_number=data.userphonenumber,
        age=age_str,
        gender=data.gender if data.gender in ("남", "여") else None,
        birth_date=final_birth_str,
        matching_count=int(data.matching_count) if data.matching_count else 0,
        status=data.status if data.status in ("매칭전", "매칭중", "성혼", "만료") else "매칭전",
        membership_type="일반회원",   # ✅ 기본값 추가
        payment_date=None            # ✅ 결제일은 없음
    )

    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        print(f"DB 삽입 오류: {e}")
        raise HTTPException(status_code=500, detail=f"User service DB 삽입 실패: {e}")

    return {
        "status": "success",
        "user": {
            "user_id": user.user_id,
            "name": user.name,
            "email": user.email,
            "phone_number": user.phone_number,
            "age": user.age,
            "gender": user.gender,
            "birth_date": user.birth_date,
            "matching_count": user.matching_count,
            "status": user.status,
            "membership_type": user.membership_type,   # ✅ 응답에도 추가
            "payment_date": user.payment_date          # ✅ 응답에도 추가
        }
    }

@app.get("/users/{kakao_id}")
def get_user(kakao_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.user_id == kakao_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자 없음")
    
    return {
        "user_id": user.user_id,
        "name": user.name,
        "email": user.email,
        "phone_number": user.phone_number,
        "age": user.age,
        "gender": user.gender,
        "birth_date": user.birth_date,
        "matching_count": user.matching_count,
        "status": user.status,
        "member_status": "회원",  # 단순 표시용
        "consultation_count":user.consultation_count
    }


@app.get("/admin/users", response_model=List[UserOut])
def get_all_users(db: Session = Depends(get_db)):
    users = db.query(User).all()
    return users

@app.put("/admin/users/memo/{user_id}")
async def update_user(user_id: int = Path(...), req: UpdateUserRequest = ...):
    try:
        # JSON 데이터를 S3에 저장할 파일 이름
        file_key = f"user_updates/{user_id}.json"

        # JSON 문자열 변환
        data_str = json.dumps(req.dict(), ensure_ascii=False)

        # S3 업로드
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=file_key,
            Body=data_str.encode("utf-8"),
            ContentType="application/json"
        )

        return {"status": "success", "message": f"{file_key} 저장 완료"}
    except (BotoCoreError, ClientError) as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/admin/users/memo/{user_id}")
async def get_user(user_id: int = Path(...)):
    file_key = f"user_updates/{user_id}.json"
    try:
        response = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=file_key)
        data = response["Body"].read().decode("utf-8")
        return json.loads(data)
    except s3_client.exceptions.NoSuchKey:
        # 파일이 없으면 기본값 반환
        return {"job": "", "memo": ""}
    except (BotoCoreError, ClientError) as e:
        raise HTTPException(status_code=500, detail=str(e))

# 회원 매칭 처리: Partner 선택 시 호출
@app.post("/admin/users/match/{user_id}/{partner_id}")
def match_partner(
    user_id: int = Path(..., description="현재 회원 ID"),
    partner_id: int = Path(..., description="선택한 이성 회원 ID"),
    db: Session = Depends(get_db)
):
    # 현재 회원 조회
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # 선택한 이성 회원 조회
    partner = db.query(User).filter(User.user_id == partner_id).first()
    if not partner:
        raise HTTPException(status_code=404, detail="Partner not found")
    
    # 매칭 적용
    user.matching_count = (user.matching_count or 0) + 1
    user.matched_partner = partner.user_id
    user.status = "매칭중"
    
    db.commit()
    db.refresh(user)
    
    
    return {
        "user_id": user.user_id,
        "matched_partner": user.matched_partner,
        "matching_count": user.matching_count
    }


# ===== 멤버십 업데이트 API (pay-service에서 호출) =====

class MembershipUpdateRequest(BaseModel):
    membership_type: str
    payment_date: str


@app.patch("/users/{user_id}/membership")
def update_membership(user_id: int, req: MembershipUpdateRequest, db: Session = Depends(get_db)):
    """결제 완료 후 회원 등급 업데이트"""
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자 없음")

    # 멤버십 타입 검증
    valid_types = ["일반회원", "정회원", "결제회원"]
    if req.membership_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"유효하지 않은 멤버십 타입: {req.membership_type}")

    user.membership_type = req.membership_type

    # 결제일 파싱
    try:
        if req.payment_date:
            # ISO 형식 파싱 (토스페이먼츠에서 오는 형식)
            payment_date = req.payment_date.replace("Z", "+00:00")
            user.payment_date = datetime.fromisoformat(payment_date)
    except ValueError:
        user.payment_date = datetime.now()

    db.commit()
    db.refresh(user)

    return {
        "status": "success",
        "user_id": user_id,
        "membership_type": user.membership_type,
        "payment_date": str(user.payment_date) if user.payment_date else None
    }


@app.get("/health")
def health_check():
    """헬스체크"""
    return {"status": "ok", "service": "user-service"}
