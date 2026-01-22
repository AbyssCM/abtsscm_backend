# chat-service/main.py
# 채팅 서비스 (WebSocket + REST API)
import os
import uuid
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import httpx
import boto3
from botocore.exceptions import BotoCoreError, ClientError

from db import SessionLocal, ChatRoom, Message, create_tables
from connection import manager

app = FastAPI(title="Chat Service", description="채팅 서비스 (WebSocket)")

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

# 알림 서비스 URL
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://notification-service:8004")


# ===== Pydantic 모델 =====

class RoomCreateRequest(BaseModel):
    user1_id: int
    user2_id: int


class MessageCreateRequest(BaseModel):
    sender_id: int
    content: str


# ===== 헬스체크 =====

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "chat-service"}


# ===== 채팅방 API =====

@app.post("/rooms")
def create_room(data: RoomCreateRequest):
    """채팅방 생성 (매칭 후 호출)"""
    db = SessionLocal()
    try:
        # 기존 채팅방 확인
        existing = db.query(ChatRoom).filter(
            ((ChatRoom.user1_id == data.user1_id) & (ChatRoom.user2_id == data.user2_id)) |
            ((ChatRoom.user1_id == data.user2_id) & (ChatRoom.user2_id == data.user1_id))
        ).first()

        if existing:
            # 기존 채팅방 활성화
            existing.is_active = True
            db.commit()
            return {
                "room_id": existing.id,
                "message": "기존 채팅방이 활성화되었습니다"
            }

        room = ChatRoom(
            user1_id=data.user1_id,
            user2_id=data.user2_id,
            is_active=True,
            created_at=datetime.now()
        )
        db.add(room)
        db.commit()
        db.refresh(room)

        return {
            "room_id": room.id,
            "message": "채팅방이 생성되었습니다"
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"채팅방 생성 실패: {str(e)}")
    finally:
        db.close()


@app.get("/rooms")
def get_my_rooms(user_id: int = Query(...)):
    """내 채팅방 목록"""
    db = SessionLocal()
    try:
        rooms = db.query(ChatRoom).filter(
            (ChatRoom.user1_id == user_id) | (ChatRoom.user2_id == user_id),
            ChatRoom.is_active == True
        ).order_by(ChatRoom.last_message_at.desc().nullsfirst()).all()

        result = []
        for room in rooms:
            # 상대방 ID
            partner_id = room.user2_id if room.user1_id == user_id else room.user1_id

            # 마지막 메시지
            last_message = db.query(Message).filter(
                Message.room_id == room.id
            ).order_by(Message.created_at.desc()).first()

            # 읽지 않은 메시지 수
            unread_count = db.query(Message).filter(
                Message.room_id == room.id,
                Message.sender_id != user_id,
                Message.is_read == False
            ).count()

            result.append({
                "room_id": room.id,
                "partner_id": partner_id,
                "last_message": {
                    "content": last_message.content if last_message else None,
                    "message_type": last_message.message_type if last_message else None,
                    "created_at": str(last_message.created_at) if last_message else None
                } if last_message else None,
                "unread_count": unread_count,
                "last_message_at": str(room.last_message_at) if room.last_message_at else None
            })

        return {"total": len(result), "rooms": result}

    finally:
        db.close()


@app.get("/rooms/{room_id}/messages")
def get_messages(
    room_id: int,
    user_id: int = Query(...),
    limit: int = 50,
    before_id: Optional[int] = None
):
    """메시지 기록 조회 (페이징)"""
    db = SessionLocal()
    try:
        # 채팅방 접근 권한 확인
        room = db.query(ChatRoom).filter(ChatRoom.id == room_id).first()
        if not room:
            raise HTTPException(status_code=404, detail="채팅방을 찾을 수 없습니다")

        if room.user1_id != user_id and room.user2_id != user_id:
            raise HTTPException(status_code=403, detail="접근 권한이 없습니다")

        query = db.query(Message).filter(Message.room_id == room_id)

        if before_id:
            query = query.filter(Message.id < before_id)

        messages = query.order_by(Message.id.desc()).limit(limit).all()

        # 읽음 처리
        db.query(Message).filter(
            Message.room_id == room_id,
            Message.sender_id != user_id,
            Message.is_read == False
        ).update({"is_read": True})
        db.commit()

        return {
            "room_id": room_id,
            "messages": [
                {
                    "id": m.id,
                    "sender_id": m.sender_id,
                    "content": m.content,
                    "message_type": m.message_type,
                    "image_url": m.image_url,
                    "is_read": m.is_read,
                    "created_at": str(m.created_at) if m.created_at else None
                }
                for m in reversed(messages)
            ]
        }

    finally:
        db.close()


@app.post("/rooms/{room_id}/messages")
async def send_message(room_id: int, data: MessageCreateRequest):
    """메시지 전송 (REST API)"""
    db = SessionLocal()
    try:
        room = db.query(ChatRoom).filter(ChatRoom.id == room_id).first()
        if not room:
            raise HTTPException(status_code=404, detail="채팅방을 찾을 수 없습니다")

        message = Message(
            room_id=room_id,
            sender_id=data.sender_id,
            content=data.content,
            message_type="text",
            is_read=False,
            created_at=datetime.now()
        )
        db.add(message)

        room.last_message_at = datetime.now()
        db.commit()
        db.refresh(message)

        # WebSocket 브로드캐스트
        await manager.broadcast({
            "type": "message",
            "message": {
                "id": message.id,
                "sender_id": message.sender_id,
                "content": message.content,
                "message_type": message.message_type,
                "created_at": str(message.created_at)
            }
        }, room_id)

        # 상대방에게 푸시 알림 (비동기)
        receiver_id = room.user2_id if room.user1_id == data.sender_id else room.user1_id
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{NOTIFICATION_SERVICE_URL}/send",
                    json={
                        "user_id": receiver_id,
                        "notification_type": "new_message",
                        "data": {
                            "sender_name": str(data.sender_id),
                            "preview": data.content[:50] if data.content else ""
                        }
                    },
                    timeout=5.0
                )
        except Exception as e:
            print(f"[Chat] Notification error: {e}")

        return {
            "status": "success",
            "message_id": message.id
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"메시지 전송 실패: {str(e)}")
    finally:
        db.close()


@app.post("/rooms/{room_id}/images")
async def upload_image(
    room_id: int,
    sender_id: int = Query(...),
    file: UploadFile = File(...)
):
    """이미지 업로드"""
    db = SessionLocal()
    try:
        room = db.query(ChatRoom).filter(ChatRoom.id == room_id).first()
        if not room:
            raise HTTPException(status_code=404, detail="채팅방을 찾을 수 없습니다")

        # 파일 확장자 확인
        allowed_extensions = [".jpg", ".jpeg", ".png", ".gif"]
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in allowed_extensions:
            raise HTTPException(status_code=400, detail="허용되지 않는 파일 형식입니다")

        # S3 업로드
        image_id = str(uuid.uuid4())
        file_key = f"chat_images/{room_id}/{image_id}{file_ext}"

        contents = await file.read()
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=file_key,
            Body=contents,
            ContentType=file.content_type
        )

        image_url = f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{file_key}"

        # 메시지 저장
        message = Message(
            room_id=room_id,
            sender_id=sender_id,
            content=None,
            message_type="image",
            image_url=image_url,
            is_read=False,
            created_at=datetime.now()
        )
        db.add(message)

        room.last_message_at = datetime.now()
        db.commit()
        db.refresh(message)

        # WebSocket 브로드캐스트
        await manager.broadcast({
            "type": "message",
            "message": {
                "id": message.id,
                "sender_id": message.sender_id,
                "content": None,
                "message_type": "image",
                "image_url": image_url,
                "created_at": str(message.created_at)
            }
        }, room_id)

        return {
            "status": "success",
            "message_id": message.id,
            "image_url": image_url
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"이미지 업로드 실패: {str(e)}")
    finally:
        db.close()


# ===== WebSocket 엔드포인트 =====

@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: int, user_id: int = Query(...)):
    """WebSocket 연결"""
    db = SessionLocal()
    try:
        # 채팅방 접근 권한 확인
        room = db.query(ChatRoom).filter(ChatRoom.id == room_id).first()
        if not room:
            await websocket.close(code=4004)
            return

        if room.user1_id != user_id and room.user2_id != user_id:
            await websocket.close(code=4003)
            return

    finally:
        db.close()

    await manager.connect(websocket, room_id)

    try:
        while True:
            data = await websocket.receive_json()

            if data.get("type") == "message":
                # 메시지 저장
                db = SessionLocal()
                try:
                    message = Message(
                        room_id=room_id,
                        sender_id=user_id,
                        content=data.get("content"),
                        message_type="text",
                        is_read=False,
                        created_at=datetime.now()
                    )
                    db.add(message)

                    room = db.query(ChatRoom).filter(ChatRoom.id == room_id).first()
                    if room:
                        room.last_message_at = datetime.now()

                    db.commit()
                    db.refresh(message)

                    # 브로드캐스트
                    await manager.broadcast({
                        "type": "message",
                        "message": {
                            "id": message.id,
                            "sender_id": message.sender_id,
                            "content": message.content,
                            "message_type": message.message_type,
                            "created_at": str(message.created_at)
                        }
                    }, room_id)

                finally:
                    db.close()

            elif data.get("type") == "typing":
                # 타이핑 인디케이터
                await manager.broadcast({
                    "type": "typing",
                    "user_id": user_id
                }, room_id, exclude=websocket)

            elif data.get("type") == "read":
                # 읽음 처리
                db = SessionLocal()
                try:
                    db.query(Message).filter(
                        Message.room_id == room_id,
                        Message.sender_id != user_id,
                        Message.is_read == False
                    ).update({"is_read": True})
                    db.commit()

                    await manager.broadcast({
                        "type": "read",
                        "user_id": user_id
                    }, room_id, exclude=websocket)

                finally:
                    db.close()

    except WebSocketDisconnect:
        manager.disconnect(websocket, room_id)
        print(f"[WebSocket] User {user_id} disconnected from room {room_id}")


# ===== 앱 시작 시 테이블 생성 =====

@app.on_event("startup")
def startup():
    create_tables()
    print("[chat-service] 시작됨")
