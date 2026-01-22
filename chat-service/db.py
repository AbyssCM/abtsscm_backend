# chat-service/db.py
# 채팅 DB 모델
import os
from sqlalchemy import create_engine, Column, Integer, String, DateTime, BigInteger, Boolean, Text, ForeignKey
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


class ChatRoom(Base):
    """채팅방 모델"""
    __tablename__ = "chat_rooms"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user1_id = Column(BigInteger, nullable=False)
    user2_id = Column(BigInteger, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, nullable=True)
    last_message_at = Column(DateTime, nullable=True)


class Message(Base):
    """메시지 모델"""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    room_id = Column(Integer, ForeignKey("chat_rooms.id"), nullable=False)
    sender_id = Column(BigInteger, nullable=False)
    content = Column(Text, nullable=True)
    message_type = Column(String(20), default="text")  # text/image
    image_url = Column(String(500), nullable=True)     # S3 URL (이미지인 경우)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, nullable=True)


def create_tables():
    """데이터베이스 테이블 생성"""
    Base.metadata.create_all(bind=engine)
