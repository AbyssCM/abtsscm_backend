# place-service/db.py
# 데이트 장소 및 코스 관리용 DB 모델
import os
from sqlalchemy import create_engine, Column, Integer, String, DateTime, BigInteger, Boolean, Text, Float, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME")

SQLALCHEMY_DATABASE_URL = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_engine(SQLALCHEMY_DATABASE_URL, echo=True, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class DatePlace(Base):
    """데이트 장소 모델 (네이버 API 캐싱)"""
    __tablename__ = "date_places"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 네이버 API 정보
    naver_place_id = Column(String(100), unique=True, nullable=True)  # 네이버 장소 ID
    name = Column(String(200), nullable=False)                         # 장소명
    category = Column(String(100), nullable=True)                      # 카테고리 (카페/레스토랑/영화관 등)
    address = Column(String(500), nullable=True)                       # 주소
    road_address = Column(String(500), nullable=True)                  # 도로명 주소

    # 좌표
    latitude = Column(Float, nullable=True)                            # 위도
    longitude = Column(Float, nullable=True)                           # 경도

    # 상세 정보
    phone = Column(String(20), nullable=True)                          # 전화번호
    description = Column(Text, nullable=True)                          # 설명
    image_url = Column(String(500), nullable=True)                     # 대표 이미지 URL
    homepage_url = Column(String(500), nullable=True)                  # 홈페이지 URL

    # 메타 정보
    created_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)


class DateCourse(Base):
    """데이트 코스 모델"""
    __tablename__ = "date_courses"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 생성자 정보
    creator_id = Column(BigInteger, nullable=False)                    # 코스 생성자 (user_id)
    title = Column(String(200), nullable=False)                        # 코스 제목
    description = Column(Text, nullable=True)                          # 코스 설명

    # 공유 정보
    is_shared = Column(Boolean, default=False)                         # 상대방과 공유 여부
    shared_with = Column(BigInteger, nullable=True)                    # 공유 대상 (partner user_id)
    shared_at = Column(DateTime, nullable=True)                        # 공유 시간

    # 상태
    status = Column(String(20), default="작성중")                      # 작성중/완성/사용됨

    # 타임스탬프
    created_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)


class DateCoursePlace(Base):
    """코스-장소 연결 모델"""
    __tablename__ = "date_course_places"

    id = Column(Integer, primary_key=True, autoincrement=True)

    course_id = Column(Integer, ForeignKey("date_courses.id"), nullable=False)
    place_id = Column(Integer, ForeignKey("date_places.id"), nullable=False)

    # 순서 및 메모
    order_index = Column(Integer, nullable=False)                      # 코스 내 순서 (1, 2, 3...)
    memo = Column(Text, nullable=True)                                 # 장소별 메모

    # 예상 시간
    estimated_duration = Column(Integer, nullable=True)                # 예상 체류 시간 (분)

    created_at = Column(DateTime, nullable=True)


def create_tables():
    """데이터베이스 테이블 생성"""
    Base.metadata.create_all(bind=engine)
