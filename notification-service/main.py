# notification-service/main.py
# 알림 서비스 (FCM 푸시 알림)
import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, BigInteger, Boolean, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

from fcm import init_firebase, send_notification, send_notification_batch, get_notification_content

load_dotenv()

app = FastAPI(title="Notification Service", description="FCM 푸시 알림 서비스")

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://www.abysscm.com",
        "http://www.abysscm.com:5173",
        "http://www.abysscm.com:5174",
        "http://admin.abysscm.com",
        "http://admin.abysscm.com:5173",
        "http://admin.abysscm.com:5174"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# DB 설정
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME")

SQLALCHEMY_DATABASE_URL = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_engine(SQLALCHEMY_DATABASE_URL, echo=True, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ===== DB 모델 =====

class UserDevice(Base):
    """사용자 디바이스 (FCM 토큰)"""
    __tablename__ = "user_devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    fcm_token = Column(String(500), nullable=False)
    device_type = Column(String(20), nullable=True)  # ios/android/web
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)


class Notification(Base):
    """알림 기록"""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=True)
    notification_type = Column(String(50), nullable=True)  # consultation/meeting/match/chat
    data = Column(Text, nullable=True)  # JSON 추가 데이터
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, nullable=True)


def create_tables():
    Base.metadata.create_all(bind=engine)


# ===== Pydantic 모델 =====

class DeviceRegisterRequest(BaseModel):
    user_id: int
    fcm_token: str
    device_type: Optional[str] = None  # ios/android/web


class SendNotificationRequest(BaseModel):
    user_id: int
    notification_type: str
    title: Optional[str] = None
    body: Optional[str] = None
    data: Optional[dict] = None


class BatchNotificationRequest(BaseModel):
    user_ids: List[int]
    notification_type: str
    title: Optional[str] = None
    body: Optional[str] = None
    data: Optional[dict] = None


# ===== API 엔드포인트 =====

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "notification-service"}


@app.post("/devices/register")
def register_device(data: DeviceRegisterRequest):
    """
    FCM 토큰 등록
    - 기존 토큰이 있으면 업데이트
    - 다른 사용자의 같은 토큰은 비활성화 (디바이스 이동 시)
    """
    db = SessionLocal()
    try:
        # 다른 사용자의 같은 토큰 비활성화
        db.query(UserDevice).filter(
            UserDevice.fcm_token == data.fcm_token,
            UserDevice.user_id != data.user_id
        ).update({"is_active": False, "updated_at": datetime.now()})

        # 기존 토큰 확인
        existing = db.query(UserDevice).filter(
            UserDevice.user_id == data.user_id,
            UserDevice.fcm_token == data.fcm_token
        ).first()

        if existing:
            existing.is_active = True
            existing.device_type = data.device_type
            existing.updated_at = datetime.now()
        else:
            device = UserDevice(
                user_id=data.user_id,
                fcm_token=data.fcm_token,
                device_type=data.device_type,
                is_active=True,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            db.add(device)

        db.commit()
        return {"message": "디바이스가 등록되었습니다"}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"등록 실패: {str(e)}")
    finally:
        db.close()


@app.delete("/devices/{token}")
def unregister_device(token: str):
    """FCM 토큰 삭제 (로그아웃 시)"""
    db = SessionLocal()
    try:
        result = db.query(UserDevice).filter(
            UserDevice.fcm_token == token
        ).update({"is_active": False, "updated_at": datetime.now()})

        db.commit()

        if result == 0:
            raise HTTPException(status_code=404, detail="토큰을 찾을 수 없습니다")

        return {"message": "디바이스가 해제되었습니다"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"해제 실패: {str(e)}")
    finally:
        db.close()


@app.post("/send")
def send_notification_api(data: SendNotificationRequest):
    """
    단일 사용자에게 알림 전송
    - notification_type에 따라 템플릿 사용
    - title/body 직접 지정 가능
    """
    db = SessionLocal()
    try:
        # 사용자의 활성 디바이스 조회
        devices = db.query(UserDevice).filter(
            UserDevice.user_id == data.user_id,
            UserDevice.is_active == True
        ).all()

        if not devices:
            return {"message": "등록된 디바이스가 없습니다", "sent": False}

        # 알림 내용 결정
        if data.title and data.body:
            title = data.title
            body = data.body
        else:
            content = get_notification_content(
                data.notification_type,
                **(data.data or {})
            )
            title = data.title or content["title"]
            body = data.body or content["body"]

        # FCM 전송
        tokens = [d.fcm_token for d in devices]
        success_count = 0

        for token in tokens:
            if send_notification(token, title, body, data.data):
                success_count += 1

        # 알림 기록 저장
        notification = Notification(
            user_id=data.user_id,
            title=title,
            body=body,
            notification_type=data.notification_type,
            data=str(data.data) if data.data else None,
            is_read=False,
            created_at=datetime.now()
        )
        db.add(notification)
        db.commit()

        return {
            "message": "알림이 전송되었습니다",
            "sent": True,
            "device_count": len(tokens),
            "success_count": success_count
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"전송 실패: {str(e)}")
    finally:
        db.close()


@app.post("/send/batch")
def send_batch_notification(data: BatchNotificationRequest):
    """
    여러 사용자에게 알림 배치 전송
    """
    db = SessionLocal()
    try:
        # 모든 대상 사용자의 활성 디바이스 조회
        devices = db.query(UserDevice).filter(
            UserDevice.user_id.in_(data.user_ids),
            UserDevice.is_active == True
        ).all()

        if not devices:
            return {"message": "등록된 디바이스가 없습니다", "sent": False}

        # 알림 내용 결정
        if data.title and data.body:
            title = data.title
            body = data.body
        else:
            content = get_notification_content(
                data.notification_type,
                **(data.data or {})
            )
            title = data.title or content["title"]
            body = data.body or content["body"]

        # FCM 배치 전송
        tokens = [d.fcm_token for d in devices]
        result = send_notification_batch(tokens, title, body, data.data)

        # 각 사용자별 알림 기록 저장
        for user_id in data.user_ids:
            notification = Notification(
                user_id=user_id,
                title=title,
                body=body,
                notification_type=data.notification_type,
                data=str(data.data) if data.data else None,
                is_read=False,
                created_at=datetime.now()
            )
            db.add(notification)

        db.commit()

        return {
            "message": "배치 알림이 전송되었습니다",
            "sent": True,
            "total_devices": len(tokens),
            "success_count": result["success_count"],
            "failure_count": result["failure_count"]
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"배치 전송 실패: {str(e)}")
    finally:
        db.close()


@app.get("/notifications/my")
def get_my_notifications(
    user_id: int = Query(..., description="사용자 ID"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """내 알림 목록 조회"""
    db = SessionLocal()
    try:
        notifications = db.query(Notification).filter(
            Notification.user_id == user_id
        ).order_by(Notification.created_at.desc()).offset(offset).limit(limit).all()

        # 읽지 않은 알림 수
        unread_count = db.query(Notification).filter(
            Notification.user_id == user_id,
            Notification.is_read == False
        ).count()

        result = []
        for n in notifications:
            result.append({
                "id": n.id,
                "title": n.title,
                "body": n.body,
                "notification_type": n.notification_type,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat() if n.created_at else None
            })

        return {
            "total": len(result),
            "unread_count": unread_count,
            "notifications": result
        }

    finally:
        db.close()


@app.put("/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int):
    """알림 읽음 처리"""
    db = SessionLocal()
    try:
        notification = db.query(Notification).filter(
            Notification.id == notification_id
        ).first()

        if not notification:
            raise HTTPException(status_code=404, detail="알림을 찾을 수 없습니다")

        notification.is_read = True
        db.commit()

        return {"message": "읽음 처리되었습니다"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"처리 실패: {str(e)}")
    finally:
        db.close()


@app.put("/notifications/read-all")
def mark_all_notifications_read(user_id: int = Query(...)):
    """모든 알림 읽음 처리"""
    db = SessionLocal()
    try:
        db.query(Notification).filter(
            Notification.user_id == user_id,
            Notification.is_read == False
        ).update({"is_read": True})

        db.commit()
        return {"message": "모든 알림이 읽음 처리되었습니다"}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"처리 실패: {str(e)}")
    finally:
        db.close()


# ===== 앱 시작 시 초기화 =====

@app.on_event("startup")
def startup():
    create_tables()
    init_firebase()
    print("[notification-service] 시작됨")
