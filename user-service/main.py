# user-service/main.py
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from db import SessionLocal, engine, User, Consultation, Meeting, MeetingReview
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
