# user-service/main.py
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from db import (
    SessionLocal, engine, User, Consultation, Meeting, MeetingReview,
    UserProfile, UserPhoto, MatchScore, MatchHistory, SuccessStory, Referral
)
from fastapi import UploadFile, File, Query
import random
import string
import uuid
from datetime import datetime, date
from typing import Optional
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


# ===== 관리자 전용 API =====

class UserSearchParams(BaseModel):
    status: str | None = None          # 매칭전, 매칭중, 성혼, 만료
    membership_type: str | None = None # 일반회원, 정회원, 결제회원
    gender: str | None = None          # 남, 여
    has_payment: bool | None = None    # 결제 여부
    is_matched: bool | None = None     # 매칭 여부
    is_banned: bool | None = None      # 추방 여부
    search: str | None = None          # 이름/전화번호 검색


@app.get("/admin/users/search")
def search_users(
    status: str = None,
    membership_type: str = None,
    gender: str = None,
    has_payment: bool = None,
    is_matched: bool = None,
    is_banned: bool = None,
    search: str = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    회원 필터링 검색 API
    - 상태, 멤버십, 성별, 결제여부, 매칭여부 등으로 필터링
    - 이름/전화번호 검색 지원
    """
    query = db.query(User)

    # 삭제된 회원 제외 (소프트 삭제)
    query = query.filter(User.deleted_at == None)

    # 필터 적용
    if status:
        query = query.filter(User.status == status)

    if membership_type:
        query = query.filter(User.membership_type == membership_type)

    if gender:
        query = query.filter(User.gender == gender)

    if has_payment is not None:
        if has_payment:
            query = query.filter(User.payment_date != None)
        else:
            query = query.filter(User.payment_date == None)

    if is_matched is not None:
        if is_matched:
            query = query.filter(User.matched_partner != None)
        else:
            query = query.filter(User.matched_partner == None)

    if is_banned is not None:
        query = query.filter(User.is_banned == is_banned)

    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            (User.name.like(search_pattern)) |
            (User.phone_number.like(search_pattern))
        )

    # 전체 개수
    total = query.count()

    # 페이징 적용
    users = query.offset(skip).limit(limit).all()

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "users": [
            {
                "user_id": u.user_id,
                "name": u.name,
                "email": u.email,
                "phone_number": u.phone_number,
                "age": u.age,
                "gender": u.gender,
                "birth_date": u.birth_date,
                "matching_count": u.matching_count,
                "status": u.status,
                "matched_partner": u.matched_partner,
                "membership_type": u.membership_type,
                "payment_date": str(u.payment_date) if u.payment_date else None,
                "is_banned": u.is_banned,
                "consultation_count": u.consultation_count
            }
            for u in users
        ]
    }


@app.get("/admin/users/{user_id}")
def get_user_detail(user_id: int, db: Session = Depends(get_db)):
    """회원 상세 조회 (관리자용)"""
    user = db.query(User).filter(User.user_id == user_id).first()
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
        "matched_partner": user.matched_partner,
        "first_consultation": str(user.first_consultation) if user.first_consultation else None,
        "last_consultation": str(user.last_consultation) if user.last_consultation else None,
        "consultation_count": user.consultation_count,
        "membership_type": user.membership_type,
        "payment_date": str(user.payment_date) if user.payment_date else None,
        "is_banned": user.is_banned,
        "banned_at": str(user.banned_at) if user.banned_at else None,
        "ban_reason": user.ban_reason,
        "deleted_at": str(user.deleted_at) if user.deleted_at else None,
        "created_at": str(user.created_at) if user.created_at else None
    }


@app.delete("/admin/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    """
    회원 탈퇴 처리 (소프트 삭제)
    - deleted_at에 현재 시간 저장
    - 실제 데이터는 삭제하지 않음
    """
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자 없음")

    if user.deleted_at:
        raise HTTPException(status_code=400, detail="이미 탈퇴한 회원입니다")

    user.deleted_at = datetime.now()
    user.status = "만료"

    db.commit()

    return {
        "status": "success",
        "message": f"회원 {user_id} 탈퇴 처리 완료",
        "deleted_at": str(user.deleted_at)
    }


class BanUserRequest(BaseModel):
    reason: str = "관리자에 의한 추방"


@app.post("/admin/users/{user_id}/ban")
def ban_user(user_id: int, req: BanUserRequest, db: Session = Depends(get_db)):
    """
    회원 추방 (블랙리스트)
    - is_banned = True, banned_at, ban_reason 저장
    """
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자 없음")

    if user.is_banned:
        raise HTTPException(status_code=400, detail="이미 추방된 회원입니다")

    user.is_banned = True
    user.banned_at = datetime.now()
    user.ban_reason = req.reason
    user.status = "만료"

    db.commit()

    return {
        "status": "success",
        "message": f"회원 {user_id} 추방 완료",
        "ban_reason": user.ban_reason,
        "banned_at": str(user.banned_at)
    }


@app.post("/admin/users/{user_id}/unban")
def unban_user(user_id: int, db: Session = Depends(get_db)):
    """회원 추방 해제"""
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자 없음")

    if not user.is_banned:
        raise HTTPException(status_code=400, detail="추방된 회원이 아닙니다")

    user.is_banned = False
    user.banned_at = None
    user.ban_reason = None
    user.status = "매칭전"

    db.commit()

    return {
        "status": "success",
        "message": f"회원 {user_id} 추방 해제 완료"
    }


@app.get("/admin/users/candidates/{user_id}")
def get_matching_candidates(user_id: int, db: Session = Depends(get_db)):
    """
    매칭 후보자 목록 조회
    - 해당 회원의 이성 중 매칭전 상태인 회원 목록
    - 추방되거나 탈퇴한 회원 제외
    """
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자 없음")

    # 이성 성별 결정
    opposite_gender = "여" if user.gender == "남" else "남"

    # 후보자 조회
    candidates = db.query(User).filter(
        User.gender == opposite_gender,
        User.status == "매칭전",
        User.is_banned == False,
        User.deleted_at == None,
        User.user_id != user_id
    ).all()

    return {
        "user_id": user_id,
        "user_gender": user.gender,
        "opposite_gender": opposite_gender,
        "total": len(candidates),
        "candidates": [
            {
                "user_id": c.user_id,
                "name": c.name,
                "age": c.age,
                "gender": c.gender,
                "birth_date": c.birth_date,
                "membership_type": c.membership_type,
                "matching_count": c.matching_count
            }
            for c in candidates
        ]
    }


@app.delete("/admin/users/match/{user_id}")
def unmatch_user(user_id: int, db: Session = Depends(get_db)):
    """
    매칭 해제
    - matched_partner를 None으로 설정
    - 상태를 매칭전으로 변경
    """
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자 없음")

    if not user.matched_partner:
        raise HTTPException(status_code=400, detail="매칭된 상대가 없습니다")

    old_partner_id = user.matched_partner
    user.matched_partner = None
    user.status = "매칭전"

    # 상대방도 매칭 해제
    partner = db.query(User).filter(User.user_id == old_partner_id).first()
    if partner and partner.matched_partner == user_id:
        partner.matched_partner = None
        partner.status = "매칭전"

    db.commit()

    return {
        "status": "success",
        "message": f"회원 {user_id}와 {old_partner_id} 매칭 해제 완료"
    }


@app.get("/admin/stats")
def get_admin_stats(db: Session = Depends(get_db)):
    """
    관리자 대시보드 통계
    - 전체 회원 수, 상태별 회원 수, 결제 회원 수 등
    """
    # 전체 회원 (탈퇴 제외)
    total_users = db.query(User).filter(User.deleted_at == None).count()

    # 상태별 회원 수
    status_counts = {}
    for status in ["매칭전", "매칭중", "성혼", "만료"]:
        count = db.query(User).filter(
            User.status == status,
            User.deleted_at == None
        ).count()
        status_counts[status] = count

    # 성별 회원 수
    gender_counts = {}
    for gender in ["남", "여"]:
        count = db.query(User).filter(
            User.gender == gender,
            User.deleted_at == None
        ).count()
        gender_counts[gender] = count

    # 결제 회원 수
    paid_users = db.query(User).filter(
        User.payment_date != None,
        User.deleted_at == None
    ).count()

    # 추방된 회원 수
    banned_users = db.query(User).filter(
        User.is_banned == True
    ).count()

    # 매칭된 회원 수
    matched_users = db.query(User).filter(
        User.matched_partner != None,
        User.deleted_at == None
    ).count()

    return {
        "total_users": total_users,
        "status_counts": status_counts,
        "gender_counts": gender_counts,
        "paid_users": paid_users,
        "banned_users": banned_users,
        "matched_users": matched_users
    }


# ===== 상담 요청 API =====

class ConsultationCreateRequest(BaseModel):
    user_id: int
    requested_date: str              # YYYY-MM-DD
    requested_time: str              # HH:MM
    consultation_type: str           # 초기상담/매칭상담/사후상담
    description: Optional[str] = None


class ConsultationConfirmRequest(BaseModel):
    confirmed_date: str              # YYYY-MM-DD
    confirmed_time: str              # HH:MM
    admin_note: Optional[str] = None


@app.post("/consultations")
def create_consultation(req: ConsultationCreateRequest, db: Session = Depends(get_db)):
    """상담 요청 생성"""
    # 사용자 확인
    user = db.query(User).filter(User.user_id == req.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자 없음")

    # 상담 유형 검증
    valid_types = ["초기상담", "매칭상담", "사후상담"]
    if req.consultation_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"유효하지 않은 상담 유형: {req.consultation_type}")

    consultation = Consultation(
        user_id=req.user_id,
        requested_date=datetime.strptime(req.requested_date, "%Y-%m-%d").date(),
        requested_time=req.requested_time,
        consultation_type=req.consultation_type,
        description=req.description,
        status="요청됨",
        created_at=datetime.now()
    )

    db.add(consultation)
    db.commit()
    db.refresh(consultation)

    return {
        "status": "success",
        "consultation": {
            "id": consultation.id,
            "user_id": consultation.user_id,
            "requested_date": str(consultation.requested_date),
            "requested_time": consultation.requested_time,
            "consultation_type": consultation.consultation_type,
            "status": consultation.status
        }
    }


@app.get("/consultations/my")
def get_my_consultations(user_id: int, db: Session = Depends(get_db)):
    """내 상담 요청 목록"""
    consultations = db.query(Consultation).filter(
        Consultation.user_id == user_id
    ).order_by(Consultation.created_at.desc()).all()

    return {
        "total": len(consultations),
        "consultations": [
            {
                "id": c.id,
                "requested_date": str(c.requested_date),
                "requested_time": c.requested_time,
                "consultation_type": c.consultation_type,
                "description": c.description,
                "status": c.status,
                "confirmed_date": str(c.confirmed_date) if c.confirmed_date else None,
                "confirmed_time": c.confirmed_time,
                "created_at": str(c.created_at) if c.created_at else None
            }
            for c in consultations
        ]
    }


@app.get("/consultations/{consultation_id}")
def get_consultation(consultation_id: int, db: Session = Depends(get_db)):
    """상담 상세 조회"""
    consultation = db.query(Consultation).filter(Consultation.id == consultation_id).first()
    if not consultation:
        raise HTTPException(status_code=404, detail="상담 요청을 찾을 수 없습니다")

    return {
        "id": consultation.id,
        "user_id": consultation.user_id,
        "requested_date": str(consultation.requested_date),
        "requested_time": consultation.requested_time,
        "consultation_type": consultation.consultation_type,
        "description": consultation.description,
        "status": consultation.status,
        "admin_note": consultation.admin_note,
        "confirmed_date": str(consultation.confirmed_date) if consultation.confirmed_date else None,
        "confirmed_time": consultation.confirmed_time,
        "completed_at": str(consultation.completed_at) if consultation.completed_at else None,
        "created_at": str(consultation.created_at) if consultation.created_at else None
    }


@app.put("/consultations/{consultation_id}/cancel")
def cancel_consultation(consultation_id: int, db: Session = Depends(get_db)):
    """상담 취소"""
    consultation = db.query(Consultation).filter(Consultation.id == consultation_id).first()
    if not consultation:
        raise HTTPException(status_code=404, detail="상담 요청을 찾을 수 없습니다")

    if consultation.status == "완료됨":
        raise HTTPException(status_code=400, detail="이미 완료된 상담은 취소할 수 없습니다")

    consultation.status = "취소됨"
    consultation.updated_at = datetime.now()
    db.commit()

    return {"status": "success", "message": "상담이 취소되었습니다"}


@app.get("/admin/consultations")
def get_all_consultations(
    status: str = None,
    consultation_type: str = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """관리자용 전체 상담 목록"""
    query = db.query(Consultation)

    if status:
        query = query.filter(Consultation.status == status)
    if consultation_type:
        query = query.filter(Consultation.consultation_type == consultation_type)

    total = query.count()
    consultations = query.order_by(Consultation.created_at.desc()).offset(skip).limit(limit).all()

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "consultations": [
            {
                "id": c.id,
                "user_id": c.user_id,
                "requested_date": str(c.requested_date),
                "requested_time": c.requested_time,
                "consultation_type": c.consultation_type,
                "description": c.description,
                "status": c.status,
                "admin_note": c.admin_note,
                "confirmed_date": str(c.confirmed_date) if c.confirmed_date else None,
                "confirmed_time": c.confirmed_time,
                "created_at": str(c.created_at) if c.created_at else None
            }
            for c in consultations
        ]
    }


@app.put("/admin/consultations/{consultation_id}/confirm")
def confirm_consultation(consultation_id: int, req: ConsultationConfirmRequest, db: Session = Depends(get_db)):
    """상담 확정 (관리자)"""
    consultation = db.query(Consultation).filter(Consultation.id == consultation_id).first()
    if not consultation:
        raise HTTPException(status_code=404, detail="상담 요청을 찾을 수 없습니다")

    consultation.status = "확인됨"
    consultation.confirmed_date = datetime.strptime(req.confirmed_date, "%Y-%m-%d").date()
    consultation.confirmed_time = req.confirmed_time
    consultation.admin_note = req.admin_note
    consultation.updated_at = datetime.now()
    db.commit()

    return {"status": "success", "message": "상담이 확정되었습니다"}


@app.put("/admin/consultations/{consultation_id}/complete")
def complete_consultation(consultation_id: int, db: Session = Depends(get_db)):
    """상담 완료 처리 (관리자)"""
    consultation = db.query(Consultation).filter(Consultation.id == consultation_id).first()
    if not consultation:
        raise HTTPException(status_code=404, detail="상담 요청을 찾을 수 없습니다")

    consultation.status = "완료됨"
    consultation.completed_at = datetime.now()
    consultation.updated_at = datetime.now()

    # 사용자의 상담 횟수 증가
    user = db.query(User).filter(User.user_id == consultation.user_id).first()
    if user:
        user.consultation_count = (user.consultation_count or 0) + 1
        user.last_consultation = datetime.now()
        if not user.first_consultation:
            user.first_consultation = datetime.now()

    db.commit()

    return {"status": "success", "message": "상담이 완료 처리되었습니다"}


# ===== 만남 관리 API =====

class MeetingCreateRequest(BaseModel):
    user_id: int
    partner_id: int
    meeting_date: str                # YYYY-MM-DD
    meeting_time: Optional[str] = None
    location: Optional[str] = None


class MeetingReviewCreateRequest(BaseModel):
    reviewer_id: int
    reviewed_id: int
    rating: int                      # 1-5
    content: Optional[str] = None
    next_meeting_intent: Optional[str] = None  # 원함/미정/원하지않음


@app.post("/meetings")
def create_meeting(req: MeetingCreateRequest, db: Session = Depends(get_db)):
    """만남 일정 생성"""
    # 사용자 확인
    user = db.query(User).filter(User.user_id == req.user_id).first()
    partner = db.query(User).filter(User.user_id == req.partner_id).first()

    if not user or not partner:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    meeting = Meeting(
        user_id=req.user_id,
        partner_id=req.partner_id,
        meeting_date=datetime.strptime(req.meeting_date, "%Y-%m-%d").date(),
        meeting_time=req.meeting_time,
        location=req.location,
        status="예약됨",
        created_at=datetime.now()
    )

    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    return {
        "status": "success",
        "meeting": {
            "id": meeting.id,
            "user_id": meeting.user_id,
            "partner_id": meeting.partner_id,
            "meeting_date": str(meeting.meeting_date),
            "meeting_time": meeting.meeting_time,
            "location": meeting.location,
            "status": meeting.status
        }
    }


@app.get("/meetings/my")
def get_my_meetings(user_id: int, db: Session = Depends(get_db)):
    """내 만남 목록"""
    meetings = db.query(Meeting).filter(
        (Meeting.user_id == user_id) | (Meeting.partner_id == user_id)
    ).order_by(Meeting.meeting_date.desc()).all()

    return {
        "total": len(meetings),
        "meetings": [
            {
                "id": m.id,
                "user_id": m.user_id,
                "partner_id": m.partner_id,
                "meeting_date": str(m.meeting_date),
                "meeting_time": m.meeting_time,
                "location": m.location,
                "status": m.status,
                "created_at": str(m.created_at) if m.created_at else None
            }
            for m in meetings
        ]
    }


@app.get("/meetings/{meeting_id}")
def get_meeting(meeting_id: int, db: Session = Depends(get_db)):
    """만남 상세 조회"""
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="만남을 찾을 수 없습니다")

    # 후기 조회
    reviews = db.query(MeetingReview).filter(MeetingReview.meeting_id == meeting_id).all()

    return {
        "id": meeting.id,
        "user_id": meeting.user_id,
        "partner_id": meeting.partner_id,
        "meeting_date": str(meeting.meeting_date),
        "meeting_time": meeting.meeting_time,
        "location": meeting.location,
        "status": meeting.status,
        "created_at": str(meeting.created_at) if meeting.created_at else None,
        "reviews": [
            {
                "id": r.id,
                "reviewer_id": r.reviewer_id,
                "rating": r.rating,
                "next_meeting_intent": r.next_meeting_intent
            }
            for r in reviews
        ]
    }


@app.put("/meetings/{meeting_id}/complete")
def complete_meeting(meeting_id: int, db: Session = Depends(get_db)):
    """만남 완료 처리"""
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="만남을 찾을 수 없습니다")

    meeting.status = "완료됨"
    meeting.updated_at = datetime.now()
    db.commit()

    return {"status": "success", "message": "만남이 완료 처리되었습니다"}


@app.put("/meetings/{meeting_id}/cancel")
def cancel_meeting(meeting_id: int, db: Session = Depends(get_db)):
    """만남 취소"""
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="만남을 찾을 수 없습니다")

    meeting.status = "취소됨"
    meeting.updated_at = datetime.now()
    db.commit()

    return {"status": "success", "message": "만남이 취소되었습니다"}


@app.post("/meetings/{meeting_id}/reviews")
def create_meeting_review(meeting_id: int, req: MeetingReviewCreateRequest, db: Session = Depends(get_db)):
    """만남 후기 작성"""
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="만남을 찾을 수 없습니다")

    # 평점 검증
    if req.rating < 1 or req.rating > 5:
        raise HTTPException(status_code=400, detail="평점은 1-5 사이여야 합니다")

    # 중복 후기 방지
    existing_review = db.query(MeetingReview).filter(
        MeetingReview.meeting_id == meeting_id,
        MeetingReview.reviewer_id == req.reviewer_id
    ).first()
    if existing_review:
        raise HTTPException(status_code=400, detail="이미 후기를 작성했습니다")

    review = MeetingReview(
        meeting_id=meeting_id,
        reviewer_id=req.reviewer_id,
        reviewed_id=req.reviewed_id,
        rating=req.rating,
        content=req.content,
        next_meeting_intent=req.next_meeting_intent,
        is_private=True,
        created_at=datetime.now()
    )

    db.add(review)
    db.commit()
    db.refresh(review)

    return {
        "status": "success",
        "review": {
            "id": review.id,
            "meeting_id": review.meeting_id,
            "rating": review.rating,
            "next_meeting_intent": review.next_meeting_intent
        }
    }


@app.get("/admin/meetings")
def get_all_meetings(
    status: str = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """관리자용 전체 만남 목록"""
    query = db.query(Meeting)

    if status:
        query = query.filter(Meeting.status == status)

    total = query.count()
    meetings = query.order_by(Meeting.meeting_date.desc()).offset(skip).limit(limit).all()

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "meetings": [
            {
                "id": m.id,
                "user_id": m.user_id,
                "partner_id": m.partner_id,
                "meeting_date": str(m.meeting_date),
                "meeting_time": m.meeting_time,
                "location": m.location,
                "status": m.status,
                "created_at": str(m.created_at) if m.created_at else None
            }
            for m in meetings
        ]
    }


@app.get("/admin/reviews")
def get_all_reviews(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    """관리자용 전체 후기 열람"""
    total = db.query(MeetingReview).count()
    reviews = db.query(MeetingReview).order_by(MeetingReview.created_at.desc()).offset(skip).limit(limit).all()

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "reviews": [
            {
                "id": r.id,
                "meeting_id": r.meeting_id,
                "reviewer_id": r.reviewer_id,
                "reviewed_id": r.reviewed_id,
                "rating": r.rating,
                "content": r.content,
                "next_meeting_intent": r.next_meeting_intent,
                "created_at": str(r.created_at) if r.created_at else None
            }
            for r in reviews
        ]
    }


@app.get("/admin/meetings/stats")
def get_meeting_stats(db: Session = Depends(get_db)):
    """만남 통계"""
    total_meetings = db.query(Meeting).count()
    completed_meetings = db.query(Meeting).filter(Meeting.status == "완료됨").count()
    cancelled_meetings = db.query(Meeting).filter(Meeting.status == "취소됨").count()

    total_reviews = db.query(MeetingReview).count()
    avg_rating = db.query(MeetingReview).with_entities(
        db.query(MeetingReview.rating).scalar_subquery()
    ).scalar() or 0

    # 다음 만남 의향 통계
    intent_counts = {}
    for intent in ["원함", "미정", "원하지않음"]:
        count = db.query(MeetingReview).filter(
            MeetingReview.next_meeting_intent == intent
        ).count()
        intent_counts[intent] = count

    return {
        "total_meetings": total_meetings,
        "completed_meetings": completed_meetings,
        "cancelled_meetings": cancelled_meetings,
        "total_reviews": total_reviews,
        "intent_counts": intent_counts
    }


# ===== 프로필 API (Phase 6-2) =====

class ProfileUpdateRequest(BaseModel):
    height: Optional[int] = None
    job: Optional[str] = None
    company: Optional[str] = None
    education: Optional[str] = None
    religion: Optional[str] = None
    smoking: Optional[str] = None
    drinking: Optional[str] = None
    location: Optional[str] = None
    mbti: Optional[str] = None
    hobbies: Optional[str] = None
    introduction: Optional[str] = None
    ideal_age_min: Optional[int] = None
    ideal_age_max: Optional[int] = None
    ideal_height_min: Optional[int] = None
    ideal_height_max: Optional[int] = None
    ideal_location: Optional[str] = None
    ideal_religion: Optional[str] = None
    ideal_smoking: Optional[str] = None


@app.get("/profile/my")
def get_my_profile(user_id: int = Query(...), db: Session = Depends(get_db)):
    """내 프로필 조회"""
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()

    if not profile:
        return {"user_id": user_id, "profile": None, "message": "프로필이 없습니다"}

    photos = db.query(UserPhoto).filter(
        UserPhoto.user_id == user_id,
        UserPhoto.is_approved == True
    ).order_by(UserPhoto.order_index).all()

    return {
        "user_id": user_id,
        "profile": {
            "height": profile.height,
            "job": profile.job,
            "company": profile.company,
            "education": profile.education,
            "religion": profile.religion,
            "smoking": profile.smoking,
            "drinking": profile.drinking,
            "location": profile.location,
            "mbti": profile.mbti,
            "hobbies": profile.hobbies,
            "introduction": profile.introduction,
            "ideal_age_min": profile.ideal_age_min,
            "ideal_age_max": profile.ideal_age_max,
            "ideal_height_min": profile.ideal_height_min,
            "ideal_height_max": profile.ideal_height_max,
            "ideal_location": profile.ideal_location,
            "ideal_religion": profile.ideal_religion,
            "ideal_smoking": profile.ideal_smoking
        },
        "photos": [
            {
                "id": p.id,
                "photo_url": p.photo_url,
                "photo_type": p.photo_type,
                "order_index": p.order_index
            }
            for p in photos
        ]
    }


@app.put("/profile/my")
def update_my_profile(user_id: int = Query(...), req: ProfileUpdateRequest = None, db: Session = Depends(get_db)):
    """프로필 수정"""
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()

    if not profile:
        profile = UserProfile(user_id=user_id, created_at=datetime.now())
        db.add(profile)

    # 프로필 업데이트
    for field, value in req.dict(exclude_unset=True).items():
        if value is not None:
            setattr(profile, field, value)

    profile.updated_at = datetime.now()
    db.commit()
    db.refresh(profile)

    return {"status": "success", "message": "프로필이 업데이트되었습니다"}


@app.post("/profile/photos")
async def upload_profile_photo(
    user_id: int = Query(...),
    photo_type: str = Query("profile"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """프로필 사진 업로드"""
    # 파일 확장자 확인
    allowed_extensions = [".jpg", ".jpeg", ".png", ".gif"]
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail="허용되지 않는 파일 형식입니다")

    # 파일 이름 생성
    photo_id = str(uuid.uuid4())
    file_key = f"user_photos/{user_id}/{photo_id}{file_ext}"

    try:
        # S3 업로드
        contents = await file.read()
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=file_key,
            Body=contents,
            ContentType=file.content_type
        )

        # S3 URL 생성
        photo_url = f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{file_key}"

        # 현재 사진 순서
        max_order = db.query(UserPhoto).filter(
            UserPhoto.user_id == user_id
        ).count()

        # DB 저장
        photo = UserPhoto(
            user_id=user_id,
            photo_url=photo_url,
            photo_type=photo_type,
            order_index=max_order,
            is_approved=False,
            created_at=datetime.now()
        )
        db.add(photo)
        db.commit()
        db.refresh(photo)

        return {
            "status": "success",
            "photo": {
                "id": photo.id,
                "photo_url": photo.photo_url,
                "is_approved": photo.is_approved
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"업로드 실패: {str(e)}")


@app.delete("/profile/photos/{photo_id}")
def delete_profile_photo(photo_id: int, db: Session = Depends(get_db)):
    """프로필 사진 삭제"""
    photo = db.query(UserPhoto).filter(UserPhoto.id == photo_id).first()
    if not photo:
        raise HTTPException(status_code=404, detail="사진을 찾을 수 없습니다")

    # S3에서 삭제
    try:
        file_key = photo.photo_url.split(f"{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/")[1]
        s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=file_key)
    except Exception:
        pass

    db.delete(photo)
    db.commit()

    return {"status": "success", "message": "사진이 삭제되었습니다"}


@app.put("/profile/photos/{photo_id}/order")
def update_photo_order(photo_id: int, order_index: int = Query(...), db: Session = Depends(get_db)):
    """사진 순서 변경"""
    photo = db.query(UserPhoto).filter(UserPhoto.id == photo_id).first()
    if not photo:
        raise HTTPException(status_code=404, detail="사진을 찾을 수 없습니다")

    photo.order_index = order_index
    db.commit()

    return {"status": "success", "message": "순서가 변경되었습니다"}


@app.get("/admin/photos/pending")
def get_pending_photos(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    """승인 대기 사진 목록"""
    query = db.query(UserPhoto).filter(UserPhoto.is_approved == False)
    total = query.count()
    photos = query.offset(skip).limit(limit).all()

    return {
        "total": total,
        "photos": [
            {
                "id": p.id,
                "user_id": p.user_id,
                "photo_url": p.photo_url,
                "photo_type": p.photo_type,
                "created_at": str(p.created_at) if p.created_at else None
            }
            for p in photos
        ]
    }


@app.put("/admin/photos/{photo_id}/approve")
def approve_photo(photo_id: int, db: Session = Depends(get_db)):
    """사진 승인"""
    photo = db.query(UserPhoto).filter(UserPhoto.id == photo_id).first()
    if not photo:
        raise HTTPException(status_code=404, detail="사진을 찾을 수 없습니다")

    photo.is_approved = True
    db.commit()

    return {"status": "success", "message": "사진이 승인되었습니다"}


@app.put("/admin/photos/{photo_id}/reject")
def reject_photo(photo_id: int, reason: str = Query("부적절한 사진"), db: Session = Depends(get_db)):
    """사진 거부"""
    photo = db.query(UserPhoto).filter(UserPhoto.id == photo_id).first()
    if not photo:
        raise HTTPException(status_code=404, detail="사진을 찾을 수 없습니다")

    photo.rejected_reason = reason
    db.delete(photo)
    db.commit()

    return {"status": "success", "message": "사진이 거부되었습니다"}


# ===== 매칭 추천 API (Phase 6-4) =====

def calculate_match_score(user_profile, candidate_profile, candidate_user):
    """매칭 점수 계산"""
    score = 0
    breakdown = {}

    if not user_profile or not candidate_profile:
        return 50, {"base": 50}

    # 1. 이상형 나이 조건 (15점)
    try:
        candidate_age = int(candidate_user.age) if candidate_user.age else 0
        if user_profile.ideal_age_min and user_profile.ideal_age_max:
            if user_profile.ideal_age_min <= candidate_age <= user_profile.ideal_age_max:
                score += 15
                breakdown["age"] = 15
    except:
        pass

    # 2. 이상형 키 조건 (15점)
    if candidate_profile.height and user_profile.ideal_height_min and user_profile.ideal_height_max:
        if user_profile.ideal_height_min <= candidate_profile.height <= user_profile.ideal_height_max:
            score += 15
            breakdown["height"] = 15

    # 3. 지역 조건 (10점)
    if user_profile.ideal_location and candidate_profile.location:
        if user_profile.ideal_location in candidate_profile.location:
            score += 10
            breakdown["location"] = 10

    # 4. 종교 조건 (10점)
    if user_profile.ideal_religion and candidate_profile.religion:
        if user_profile.ideal_religion == candidate_profile.religion or user_profile.ideal_religion == "상관없음":
            score += 10
            breakdown["religion"] = 10

    # 5. 흡연 조건 (10점)
    if user_profile.ideal_smoking and candidate_profile.smoking:
        if user_profile.ideal_smoking == candidate_profile.smoking or user_profile.ideal_smoking == "상관없음":
            score += 10
            breakdown["smoking"] = 10

    # 6. 프로필 완성도 (20점)
    profile_fields = [candidate_profile.job, candidate_profile.education, candidate_profile.introduction]
    filled = sum(1 for f in profile_fields if f)
    completeness = (filled / len(profile_fields)) * 20
    score += completeness
    breakdown["completeness"] = completeness

    # 7. 기본 점수 (20점)
    score += 20
    breakdown["base"] = 20

    return min(score, 100), breakdown


@app.get("/recommendations")
def get_recommendations(user_id: int = Query(...), limit: int = 10, db: Session = Depends(get_db)):
    """내 추천 목록"""
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자 없음")

    user_profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()

    # 이성, 매칭전, 활성 사용자 조회
    opposite_gender = "여" if user.gender == "남" else "남"
    candidates = db.query(User).filter(
        User.gender == opposite_gender,
        User.status == "매칭전",
        User.is_banned == False,
        User.deleted_at == None,
        User.user_id != user_id
    ).all()

    # 점수 계산
    scored_candidates = []
    for candidate in candidates:
        candidate_profile = db.query(UserProfile).filter(UserProfile.user_id == candidate.user_id).first()
        score, breakdown = calculate_match_score(user_profile, candidate_profile, candidate)
        scored_candidates.append({
            "user": candidate,
            "profile": candidate_profile,
            "score": score,
            "breakdown": breakdown
        })

    # 점수순 정렬
    scored_candidates.sort(key=lambda x: x["score"], reverse=True)

    return {
        "total": len(scored_candidates[:limit]),
        "recommendations": [
            {
                "user_id": c["user"].user_id,
                "name": c["user"].name,
                "age": c["user"].age,
                "score": round(c["score"], 1),
                "profile": {
                    "job": c["profile"].job if c["profile"] else None,
                    "location": c["profile"].location if c["profile"] else None,
                    "introduction": c["profile"].introduction[:100] if c["profile"] and c["profile"].introduction else None
                } if c["profile"] else None
            }
            for c in scored_candidates[:limit]
        ]
    }


@app.get("/admin/recommendations/{user_id}")
def get_user_recommendations(user_id: int, limit: int = 20, db: Session = Depends(get_db)):
    """특정 회원 추천 목록 (관리자)"""
    return get_recommendations(user_id=user_id, limit=limit, db=db)


# ===== 성혼 후기 API (Phase 6-5) =====

class SuccessStoryCreateRequest(BaseModel):
    user1_id: int
    user2_id: int
    title: str
    content: Optional[str] = None
    display_names: Optional[str] = None


@app.post("/success-stories")
def create_success_story(req: SuccessStoryCreateRequest, db: Session = Depends(get_db)):
    """성혼 후기 작성"""
    story = SuccessStory(
        user1_id=req.user1_id,
        user2_id=req.user2_id,
        title=req.title,
        content=req.content,
        display_names=req.display_names,
        status="pending",
        is_public=False,
        created_at=datetime.now()
    )

    db.add(story)
    db.commit()
    db.refresh(story)

    return {
        "status": "success",
        "story_id": story.id,
        "message": "후기가 등록되었습니다. 관리자 승인 후 공개됩니다."
    }


@app.get("/success-stories/public")
def get_public_success_stories(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """공개 후기 목록 (랜딩페이지용)"""
    stories = db.query(SuccessStory).filter(
        SuccessStory.status == "approved",
        SuccessStory.is_public == True
    ).order_by(SuccessStory.approved_at.desc()).offset(skip).limit(limit).all()

    return {
        "total": len(stories),
        "stories": [
            {
                "id": s.id,
                "title": s.title,
                "content": s.content,
                "display_names": s.display_names,
                "photo_url": s.photo_url,
                "approved_at": str(s.approved_at) if s.approved_at else None
            }
            for s in stories
        ]
    }


@app.get("/admin/success-stories")
def get_all_success_stories(status: str = None, skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    """전체 후기 목록 (관리자)"""
    query = db.query(SuccessStory)
    if status:
        query = query.filter(SuccessStory.status == status)

    total = query.count()
    stories = query.order_by(SuccessStory.created_at.desc()).offset(skip).limit(limit).all()

    return {
        "total": total,
        "stories": [
            {
                "id": s.id,
                "user1_id": s.user1_id,
                "user2_id": s.user2_id,
                "title": s.title,
                "content": s.content,
                "status": s.status,
                "is_public": s.is_public,
                "created_at": str(s.created_at) if s.created_at else None
            }
            for s in stories
        ]
    }


@app.put("/admin/success-stories/{story_id}/approve")
def approve_success_story(story_id: int, is_public: bool = True, db: Session = Depends(get_db)):
    """후기 승인"""
    story = db.query(SuccessStory).filter(SuccessStory.id == story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="후기를 찾을 수 없습니다")

    story.status = "approved"
    story.is_public = is_public
    story.approved_at = datetime.now()
    db.commit()

    return {"status": "success", "message": "후기가 승인되었습니다"}


@app.put("/admin/success-stories/{story_id}/reject")
def reject_success_story(story_id: int, note: str = None, db: Session = Depends(get_db)):
    """후기 거부"""
    story = db.query(SuccessStory).filter(SuccessStory.id == story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="후기를 찾을 수 없습니다")

    story.status = "rejected"
    story.admin_note = note
    db.commit()

    return {"status": "success", "message": "후기가 거부되었습니다"}


# ===== 추천인 API (Phase 6-6) =====

def generate_referral_code():
    """추천 코드 생성"""
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=6))


@app.get("/referral/my-code")
def get_my_referral_code(user_id: int = Query(...), db: Session = Depends(get_db)):
    """내 추천 코드 조회 (없으면 생성)"""
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자 없음")

    if not user.referral_code:
        # 코드 생성
        while True:
            code = generate_referral_code()
            existing = db.query(User).filter(User.referral_code == code).first()
            if not existing:
                user.referral_code = code
                db.commit()
                break

    return {
        "user_id": user_id,
        "referral_code": user.referral_code
    }


@app.post("/referral/apply")
def apply_referral_code(user_id: int = Query(...), code: str = Query(...), db: Session = Depends(get_db)):
    """추천 코드 적용"""
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자 없음")

    if user.referred_by:
        raise HTTPException(status_code=400, detail="이미 추천 코드를 적용했습니다")

    # 추천인 찾기
    referrer = db.query(User).filter(User.referral_code == code).first()
    if not referrer:
        raise HTTPException(status_code=404, detail="유효하지 않은 추천 코드입니다")

    if referrer.user_id == user_id:
        raise HTTPException(status_code=400, detail="본인의 추천 코드는 사용할 수 없습니다")

    # 추천 관계 저장
    user.referred_by = referrer.user_id

    referral = Referral(
        referrer_id=referrer.user_id,
        referee_id=user_id,
        referral_code=code,
        reward_status="pending",
        created_at=datetime.now()
    )
    db.add(referral)
    db.commit()

    return {
        "status": "success",
        "message": "추천 코드가 적용되었습니다",
        "referrer_id": referrer.user_id
    }


@app.get("/referral/my-referrals")
def get_my_referrals(user_id: int = Query(...), db: Session = Depends(get_db)):
    """내가 추천한 사람 목록"""
    referrals = db.query(Referral).filter(Referral.referrer_id == user_id).all()

    return {
        "total": len(referrals),
        "referrals": [
            {
                "id": r.id,
                "referee_id": r.referee_id,
                "reward_status": r.reward_status,
                "created_at": str(r.created_at) if r.created_at else None
            }
            for r in referrals
        ]
    }


@app.get("/admin/referrals")
def get_all_referrals(status: str = None, skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    """전체 추천 현황 (관리자)"""
    query = db.query(Referral)
    if status:
        query = query.filter(Referral.reward_status == status)

    total = query.count()
    referrals = query.order_by(Referral.created_at.desc()).offset(skip).limit(limit).all()

    return {
        "total": total,
        "referrals": [
            {
                "id": r.id,
                "referrer_id": r.referrer_id,
                "referee_id": r.referee_id,
                "referral_code": r.referral_code,
                "reward_status": r.reward_status,
                "reward_type": r.reward_type,
                "created_at": str(r.created_at) if r.created_at else None
            }
            for r in referrals
        ]
    }


@app.put("/admin/referrals/{referral_id}/reward")
def reward_referral(referral_id: int, reward_type: str = Query("discount"), db: Session = Depends(get_db)):
    """보상 지급 처리"""
    referral = db.query(Referral).filter(Referral.id == referral_id).first()
    if not referral:
        raise HTTPException(status_code=404, detail="추천 기록을 찾을 수 없습니다")

    referral.reward_status = "rewarded"
    referral.reward_type = reward_type
    referral.rewarded_at = datetime.now()
    db.commit()

    return {"status": "success", "message": "보상이 지급되었습니다"}


# ===== 관리자 대시보드 고도화 API (Phase 6-7) =====

@app.get("/admin/dashboard")
def get_admin_dashboard(db: Session = Depends(get_db)):
    """종합 대시보드"""
    # 기본 통계
    total_users = db.query(User).filter(User.deleted_at == None).count()
    active_users = db.query(User).filter(
        User.deleted_at == None,
        User.is_banned == False
    ).count()

    # 이번 달 신규 가입
    today = datetime.now()
    first_of_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    new_users_this_month = db.query(User).filter(
        User.created_at >= first_of_month
    ).count()

    # 매칭 통계
    total_matches = db.query(User).filter(User.matched_partner != None).count() // 2
    success_matches = db.query(User).filter(User.status == "성혼").count() // 2

    # 대기 항목
    pending_photos = db.query(UserPhoto).filter(UserPhoto.is_approved == False).count()
    pending_consultations = db.query(Consultation).filter(Consultation.status == "요청됨").count()
    pending_stories = db.query(SuccessStory).filter(SuccessStory.status == "pending").count()

    return {
        "overview": {
            "total_users": total_users,
            "active_users": active_users,
            "new_users_this_month": new_users_this_month,
            "total_matches": total_matches,
            "success_matches": success_matches
        },
        "alerts": {
            "pending_photos": pending_photos,
            "pending_consultations": pending_consultations,
            "pending_stories": pending_stories
        }
    }


@app.get("/admin/analytics/users")
def get_user_analytics(db: Session = Depends(get_db)):
    """사용자 분석"""
    # 성별 분포
    gender_counts = {}
    for gender in ["남", "여"]:
        count = db.query(User).filter(User.gender == gender, User.deleted_at == None).count()
        gender_counts[gender] = count

    # 멤버십 분포
    membership_counts = {}
    for membership in ["일반회원", "정회원", "결제회원"]:
        count = db.query(User).filter(User.membership_type == membership, User.deleted_at == None).count()
        membership_counts[membership] = count

    # 상태 분포
    status_counts = {}
    for status in ["매칭전", "매칭중", "성혼", "만료"]:
        count = db.query(User).filter(User.status == status, User.deleted_at == None).count()
        status_counts[status] = count

    return {
        "gender_distribution": gender_counts,
        "membership_distribution": membership_counts,
        "status_distribution": status_counts
    }


@app.get("/admin/analytics/matches")
def get_match_analytics(db: Session = Depends(get_db)):
    """매칭 분석"""
    total_users = db.query(User).filter(User.deleted_at == None).count()
    matched_users = db.query(User).filter(User.matched_partner != None, User.deleted_at == None).count()
    success_users = db.query(User).filter(User.status == "성혼").count()

    match_rate = (matched_users / total_users * 100) if total_users > 0 else 0
    success_rate = (success_users / matched_users * 100) if matched_users > 0 else 0

    return {
        "total_users": total_users,
        "matched_users": matched_users,
        "success_users": success_users,
        "match_rate": round(match_rate, 1),
        "success_rate": round(success_rate, 1)
    }


@app.get("/admin/analytics/consultations")
def get_consultation_analytics(db: Session = Depends(get_db)):
    """상담 분석"""
    total = db.query(Consultation).count()
    by_status = {}
    for status in ["요청됨", "확인됨", "완료됨", "취소됨"]:
        count = db.query(Consultation).filter(Consultation.status == status).count()
        by_status[status] = count

    by_type = {}
    for ctype in ["초기상담", "매칭상담", "사후상담"]:
        count = db.query(Consultation).filter(Consultation.consultation_type == ctype).count()
        by_type[ctype] = count

    return {
        "total": total,
        "by_status": by_status,
        "by_type": by_type
    }


@app.get("/admin/reports/summary")
def get_summary_report(db: Session = Depends(get_db)):
    """요약 리포트"""
    # 전체 통계
    total_users = db.query(User).filter(User.deleted_at == None).count()
    paid_users = db.query(User).filter(User.payment_date != None, User.deleted_at == None).count()
    total_consultations = db.query(Consultation).count()
    total_meetings = db.query(Meeting).count()
    total_referrals = db.query(Referral).count()

    return {
        "summary": {
            "total_users": total_users,
            "paid_users": paid_users,
            "payment_rate": round((paid_users / total_users * 100) if total_users > 0 else 0, 1),
            "total_consultations": total_consultations,
            "total_meetings": total_meetings,
            "total_referrals": total_referrals
        }
    }
