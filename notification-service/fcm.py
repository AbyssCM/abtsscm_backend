# notification-service/fcm.py
# Firebase Cloud Messaging 연동 모듈
import os
import json
import base64
import firebase_admin
from firebase_admin import credentials, messaging
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

load_dotenv()


class FCMError(Exception):
    """FCM 관련 에러"""
    pass


# Firebase 초기화 (싱글톤)
_firebase_app = None


def init_firebase():
    """Firebase Admin SDK 초기화"""
    global _firebase_app

    if _firebase_app is not None:
        return _firebase_app

    # 환경변수에서 credentials JSON 가져오기 (base64 인코딩)
    creds_json = os.getenv("FIREBASE_CREDENTIALS_JSON")

    if not creds_json:
        print("[FCM] Firebase credentials not found, running in mock mode")
        return None

    try:
        # base64 디코딩
        creds_dict = json.loads(base64.b64decode(creds_json))
        cred = credentials.Certificate(creds_dict)
        _firebase_app = firebase_admin.initialize_app(cred)
        print("[FCM] Firebase initialized successfully")
        return _firebase_app
    except Exception as e:
        print(f"[FCM] Firebase initialization error: {e}")
        return None


def send_notification(
    token: str,
    title: str,
    body: str,
    data: Optional[Dict[str, str]] = None
) -> bool:
    """
    단일 디바이스에 푸시 알림 전송

    Args:
        token: FCM 토큰
        title: 알림 제목
        body: 알림 내용
        data: 추가 데이터 (optional)

    Returns:
        성공 여부
    """
    if _firebase_app is None:
        print(f"[FCM Mock] Sending to {token[:20]}...: {title}")
        return True

    try:
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body
            ),
            data=data or {},
            token=token
        )

        response = messaging.send(message)
        print(f"[FCM] Message sent: {response}")
        return True

    except messaging.UnregisteredError:
        print(f"[FCM] Token unregistered: {token[:20]}...")
        return False
    except Exception as e:
        print(f"[FCM] Send error: {e}")
        return False


def send_notification_batch(
    tokens: List[str],
    title: str,
    body: str,
    data: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    여러 디바이스에 푸시 알림 배치 전송

    Args:
        tokens: FCM 토큰 목록
        title: 알림 제목
        body: 알림 내용
        data: 추가 데이터 (optional)

    Returns:
        성공/실패 토큰 정보
    """
    if not tokens:
        return {"success_count": 0, "failure_count": 0, "failed_tokens": []}

    if _firebase_app is None:
        print(f"[FCM Mock] Batch sending to {len(tokens)} devices: {title}")
        return {
            "success_count": len(tokens),
            "failure_count": 0,
            "failed_tokens": []
        }

    try:
        message = messaging.MulticastMessage(
            notification=messaging.Notification(
                title=title,
                body=body
            ),
            data=data or {},
            tokens=tokens
        )

        response = messaging.send_multicast(message)

        # 실패한 토큰 수집
        failed_tokens = []
        if response.failure_count > 0:
            for idx, send_response in enumerate(response.responses):
                if not send_response.success:
                    failed_tokens.append(tokens[idx])

        print(f"[FCM] Batch sent: {response.success_count} success, {response.failure_count} failed")

        return {
            "success_count": response.success_count,
            "failure_count": response.failure_count,
            "failed_tokens": failed_tokens
        }

    except Exception as e:
        print(f"[FCM] Batch send error: {e}")
        return {
            "success_count": 0,
            "failure_count": len(tokens),
            "failed_tokens": tokens
        }


# 알림 유형별 템플릿
NOTIFICATION_TEMPLATES = {
    "consultation_confirmed": {
        "title": "상담 일정이 확정되었습니다",
        "body": "{date} {time}에 상담이 예정되어 있습니다."
    },
    "consultation_reminder": {
        "title": "상담 리마인더",
        "body": "내일 {time}에 상담이 예정되어 있습니다."
    },
    "meeting_created": {
        "title": "새로운 만남이 예약되었습니다",
        "body": "{date}에 {partner_name}님과의 만남이 예정되어 있습니다."
    },
    "meeting_reminder": {
        "title": "만남 리마인더",
        "body": "내일 {partner_name}님과의 만남이 예정되어 있습니다."
    },
    "match_created": {
        "title": "새로운 매칭이 성사되었습니다!",
        "body": "매칭 상대를 확인해보세요."
    },
    "new_message": {
        "title": "새 메시지가 도착했습니다",
        "body": "{sender_name}: {preview}"
    },
    "photo_approved": {
        "title": "프로필 사진이 승인되었습니다",
        "body": "이제 다른 회원들에게 사진이 공개됩니다."
    },
    "photo_rejected": {
        "title": "프로필 사진이 반려되었습니다",
        "body": "새로운 사진을 업로드해주세요."
    }
}


def get_notification_content(
    notification_type: str,
    **kwargs
) -> Dict[str, str]:
    """
    알림 유형에 따른 제목/내용 생성

    Args:
        notification_type: 알림 유형
        **kwargs: 템플릿 변수

    Returns:
        {"title": ..., "body": ...}
    """
    template = NOTIFICATION_TEMPLATES.get(notification_type)

    if not template:
        return {
            "title": "알림",
            "body": "새로운 알림이 있습니다."
        }

    return {
        "title": template["title"].format(**kwargs),
        "body": template["body"].format(**kwargs)
    }
