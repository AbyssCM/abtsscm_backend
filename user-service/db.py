# db.py
# PostgreSQL 버전 (MySQL에서 마이그레이션)
import os
from sqlalchemy import create_engine, Column, Integer, String, DateTime, BigInteger, Boolean, Text, Date, ForeignKey, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# 환경변수에서 DB 정보 가져오기
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")  # PostgreSQL 기본 포트
DB_NAME = os.getenv("DB_NAME")

# PostgreSQL 연결 URL
SQLALCHEMY_DATABASE_URL = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# 엔진 생성
engine = create_engine(SQLALCHEMY_DATABASE_URL, echo=True, future=True)

# 세션 로컬 생성
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base 클래스 선언 (모델 상속용)
Base = declarative_base()


class User(Base):
    """회원 모델"""
    __tablename__ = "users"

    # 기본 정보
    user_id = Column(BigInteger, primary_key=True, index=True)  # 카카오 ID
    name = Column(String(50), nullable=False)                    # 이름
    email = Column(String(100), unique=True, nullable=True)      # 이메일
    phone_number = Column(String(20), nullable=True)             # 전화번호
    age = Column(String(3), nullable=True)                       # 나이
    gender = Column(String(2), nullable=True)                    # 성별 (남/여)
    birth_date = Column(String(30), nullable=True)               # 생년월일

    # 매칭 관련
    matching_count = Column(Integer, default=0)                  # 매칭횟수
    status = Column(String(10), default="매칭전")                # 상태 (매칭전/매칭중/성혼/만료)
    matched_partner = Column(BigInteger, nullable=True)          # 매칭된 상대 회원 ID

    # 상담 관련
    first_consultation = Column(DateTime, nullable=True)         # 최초 상담일
    last_consultation = Column(DateTime, nullable=True)          # 마지막 상담일
    consultation_count = Column(Integer, default=0)              # 상담횟수

    # 결제 관련
    membership_type = Column(String(10), default="일반회원")     # 회원 등급 (일반회원/정회원/결제회원)
    payment_date = Column(DateTime, nullable=True)               # 결제일

    # 관리 관련 (신규)
    is_banned = Column(Boolean, default=False)                   # 추방 여부
    banned_at = Column(DateTime, nullable=True)                  # 추방일
    ban_reason = Column(Text, nullable=True)                     # 추방 사유
    deleted_at = Column(DateTime, nullable=True)                 # 탈퇴일 (소프트 삭제)
    created_at = Column(DateTime, nullable=True)                 # 가입일


class Admin(Base):
    """관리자 모델"""
    __tablename__ = "admins"

    admin_id = Column(Integer, primary_key=True, autoincrement=True)
    kakao_id = Column(BigInteger, unique=True, nullable=False)   # 허용된 카카오 ID
    name = Column(String(50), nullable=False)                    # 관리자 이름
    role = Column(String(20), default="admin")                   # 역할 (super_admin/admin)
    created_at = Column(DateTime, nullable=True)                 # 생성일
    last_login = Column(DateTime, nullable=True)                 # 마지막 로그인


class Consultation(Base):
    """상담 요청 모델"""
    __tablename__ = "consultations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)

    # 상담 일정
    requested_date = Column(Date, nullable=False)                # 희망 상담일
    requested_time = Column(String(10), nullable=False)          # 희망 시간 (HH:MM)

    # 상담 내용
    consultation_type = Column(String(20), nullable=False)       # 초기상담/매칭상담/사후상담
    description = Column(Text, nullable=True)                    # 상담 내용/요청사항

    # 상태 관리
    status = Column(String(20), default="요청됨")                # 요청됨/확인됨/완료됨/취소됨
    admin_note = Column(Text, nullable=True)                     # 관리자 메모

    # 확정 일정
    confirmed_date = Column(Date, nullable=True)                 # 확정된 상담일
    confirmed_time = Column(String(10), nullable=True)           # 확정된 시간
    completed_at = Column(DateTime, nullable=True)               # 완료 시간

    # 타임스탬프
    created_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)


class Meeting(Base):
    """만남 기록 모델"""
    __tablename__ = "meetings"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 참여자 (양쪽 사용자)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    partner_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)

    # 만남 일정
    meeting_date = Column(Date, nullable=False)                  # 만남 날짜
    meeting_time = Column(String(10), nullable=True)             # 만남 시간
    location = Column(String(200), nullable=True)                # 만남 장소

    # 상태
    status = Column(String(20), default="예약됨")                # 예약됨/완료됨/취소됨

    # 타임스탬프
    created_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)


class MeetingReview(Base):
    """만남 후기/평가 모델"""
    __tablename__ = "meeting_reviews"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False)

    # 작성자 정보
    reviewer_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    reviewed_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)

    # 평가 내용
    rating = Column(Integer, nullable=False)                     # 1-5점 평가
    content = Column(Text, nullable=True)                        # 후기 내용

    # 다음 만남 의향
    next_meeting_intent = Column(String(20), nullable=True)      # 원함/미정/원하지않음

    # 비공개 여부 (상대방에게 공개할지)
    is_private = Column(Boolean, default=True)                   # 기본: 관리자만 열람

    # 타임스탬프
    created_at = Column(DateTime, nullable=True)


# 테이블 생성 함수
def create_tables():
    """데이터베이스 테이블 생성"""
    Base.metadata.create_all(bind=engine)
