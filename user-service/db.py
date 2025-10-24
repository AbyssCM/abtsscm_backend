# db.py
import os
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Enum, BigInteger
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# 환경변수에서 DB 정보 가져오기
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_NAME = os.getenv("DB_NAME")



# SQLAlchemy 연결 URL
SQLALCHEMY_DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# 엔진 생성
engine = create_engine(SQLALCHEMY_DATABASE_URL, echo=True, future=True)

# 세션 로컬 생성
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base 클래스 선언 (모델 상속용)
Base = declarative_base()

# 기존 테이블 조회용 User 모델
class User(Base):
    __tablename__ = "users"  # 실제 DB 테이블명

    user_id = Column(BigInteger, primary_key=True, index=True)  # 회원번호 (긴 숫자)
    name = Column(String(50), nullable=False)                   # 이름
    email = Column(String(100), unique=True, nullable=True)     # 이메일
    phone_number = Column(String(20), nullable=True)            # 전화번호
    age = Column(String(3), nullable=True)                      # 나이
    gender = Column(Enum("남", "여", name="gender_enum"), nullable=True)  # 성별
    birth_date = Column(String(30), nullable=True)              # 생년월일
    matching_count = Column(Integer, default=0)                 # 매칭횟수
    status = Column(
        Enum("매칭전", "매칭중", "성혼", "만료", name="status_enum"),
        default="매칭전"
    )                                                            # 현재상태

    # 상담 관련 컬럼
    first_consultation = Column(DateTime, nullable=True)        # 최초 상담일
    last_consultation = Column(DateTime, nullable=True)         # 마지막 상담일
    consultation_count = Column(Integer, default=0)             # 상담횟수
    matched_partner = Column(BigInteger, nullable=True)          # 매칭된 상대 회원 ID

    # ✅ 결제 관련 컬럼
    membership_type = Column(
        Enum("일반회원", "정회원", "결제회원", name="membership_enum"),
        default="일반회원",
        nullable=False
    )                                                           # 결제정보 (회원 등급)
    payment_date = Column(DateTime, nullable=True)              # 결제일