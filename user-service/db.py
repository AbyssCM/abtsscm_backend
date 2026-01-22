# db.py
# PostgreSQL 버전 (MySQL에서 마이그레이션)
import os
from sqlalchemy import create_engine, Column, Integer, String, DateTime, BigInteger, Boolean, Text
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


# 테이블 생성 함수
def create_tables():
    """데이터베이스 테이블 생성"""
    Base.metadata.create_all(bind=engine)
