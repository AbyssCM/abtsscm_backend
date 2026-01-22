# chat-service/connection.py
# WebSocket 연결 관리자
from fastapi import WebSocket
from typing import Dict, List
import json


class ConnectionManager:
    """WebSocket 연결 관리"""

    def __init__(self):
        # room_id -> List[WebSocket]
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, room_id: int):
        """WebSocket 연결"""
        await websocket.accept()

        if room_id not in self.active_connections:
            self.active_connections[room_id] = []

        self.active_connections[room_id].append(websocket)
        print(f"[WebSocket] Connected to room {room_id}, total: {len(self.active_connections[room_id])}")

    def disconnect(self, websocket: WebSocket, room_id: int):
        """WebSocket 연결 해제"""
        if room_id in self.active_connections:
            if websocket in self.active_connections[room_id]:
                self.active_connections[room_id].remove(websocket)
                print(f"[WebSocket] Disconnected from room {room_id}")

            if len(self.active_connections[room_id]) == 0:
                del self.active_connections[room_id]

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """개인 메시지 전송"""
        await websocket.send_json(message)

    async def broadcast(self, message: dict, room_id: int, exclude: WebSocket = None):
        """방 전체에 메시지 브로드캐스트"""
        if room_id not in self.active_connections:
            return

        for connection in self.active_connections[room_id]:
            if connection != exclude:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    print(f"[WebSocket] Broadcast error: {e}")

    def get_room_connections(self, room_id: int) -> int:
        """방의 연결 수 조회"""
        return len(self.active_connections.get(room_id, []))


# 전역 연결 관리자 인스턴스
manager = ConnectionManager()
