# pay-service/main.py
# 토스페이먼츠 결제 서비스
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import httpx
import os
import base64

app = FastAPI(
    title="Pay Service",
    description="토스페이먼츠 결제 처리 서비스",
    version="1.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://www.abysscm.com",
        "http://www.abysscm.com:5173",
        "http://www.abysscm.com:5174",
        "http://admin.abysscm.com",
        "http://admin.abysscm.com:5173",
        "http://admin.abysscm.com:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 환경변수
TOSS_CLIENT_KEY = os.getenv("TOSS_CLIENT_KEY")
TOSS_SECRET_KEY = os.getenv("TOSS_SECRET_KEY")
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://user-service:8001")

# 토스 API 기본 URL
TOSS_API_BASE = "https://api.tosspayments.com/v1"


# ===== Pydantic Models =====

class PaymentReadyRequest(BaseModel):
    """결제 준비 요청"""
    user_id: int
    amount: int
    order_name: str  # 예: "정회원 결제"
    membership_type: str = "결제회원"  # "정회원" 또는 "결제회원"
    success_url: Optional[str] = None
    fail_url: Optional[str] = None


class PaymentReadyResponse(BaseModel):
    """결제 준비 응답"""
    order_id: str
    amount: int
    checkout_url: str  # 토스 결제창 URL


class PaymentConfirmRequest(BaseModel):
    """결제 승인 요청 (토스에서 리다이렉트 후)"""
    payment_key: str
    order_id: str
    amount: int


class PaymentConfirmResponse(BaseModel):
    """결제 승인 응답"""
    payment_key: str
    order_id: str
    status: str
    approved_at: Optional[str] = None
    receipt_url: Optional[str] = None
    total_amount: int


class PaymentStatusResponse(BaseModel):
    """결제 상태 조회 응답"""
    payment_key: str
    order_id: str
    status: str
    total_amount: int
    method: Optional[str] = None
    approved_at: Optional[str] = None


# ===== Helper Functions =====

def get_toss_auth_header() -> dict:
    """토스 API 인증 헤더 생성 (Basic Auth)"""
    if not TOSS_SECRET_KEY:
        raise HTTPException(status_code=500, detail="토스 시크릿 키가 설정되지 않았습니다")
    credentials = f"{TOSS_SECRET_KEY}:"
    encoded = base64.b64encode(credentials.encode()).decode()
    return {
        "Authorization": f"Basic {encoded}",
        "Content-Type": "application/json"
    }


def generate_order_id(user_id: int) -> str:
    """주문 ID 생성 (user_id + timestamp)"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")[:17]
    return f"ORDER_{user_id}_{timestamp}"


# ===== API Endpoints =====

@app.get("/health")
def health_check():
    """헬스체크"""
    return {"status": "ok", "service": "pay-service"}


@app.post("/payments/ready", response_model=PaymentReadyResponse)
async def payment_ready(req: PaymentReadyRequest):
    """
    결제 준비 API
    - 주문 ID 생성 및 결제창 URL 반환
    """
    order_id = generate_order_id(req.user_id)

    # 기본 URL 설정
    success_url = req.success_url or "http://www.abysscm.com/payment/success"
    fail_url = req.fail_url or "http://www.abysscm.com/payment/fail"

    # 토스페이먼츠 결제창 URL 생성
    # 클라이언트에서 토스 SDK를 사용해 결제창을 띄울 때 사용할 정보 반환
    checkout_url = (
        f"https://pay.toss.im/v1/payments?"
        f"clientKey={TOSS_CLIENT_KEY}&"
        f"orderId={order_id}&"
        f"amount={req.amount}&"
        f"orderName={req.order_name}&"
        f"successUrl={success_url}&"
        f"failUrl={fail_url}"
    )

    return PaymentReadyResponse(
        order_id=order_id,
        amount=req.amount,
        checkout_url=checkout_url
    )


@app.post("/payments/confirm", response_model=PaymentConfirmResponse)
async def payment_confirm(req: PaymentConfirmRequest):
    """
    결제 승인 API
    - 사용자가 결제창에서 결제 완료 후 호출
    - 토스에 최종 승인 요청 및 회원 등급 업데이트
    """
    # 토스 결제 승인 API 호출
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{TOSS_API_BASE}/payments/confirm",
            headers=get_toss_auth_header(),
            json={
                "paymentKey": req.payment_key,
                "orderId": req.order_id,
                "amount": req.amount
            },
            timeout=30.0
        )

    if response.status_code != 200:
        error_data = response.json()
        raise HTTPException(
            status_code=400,
            detail=f"결제 승인 실패: {error_data.get('message', '알 수 없는 오류')}"
        )

    data = response.json()

    # order_id에서 user_id 추출 (ORDER_{user_id}_{timestamp})
    try:
        parts = req.order_id.split("_")
        if len(parts) >= 2:
            user_id = int(parts[1])

            # 결제 성공 시 user-service에 회원 등급 업데이트 요청
            async with httpx.AsyncClient() as client:
                await client.patch(
                    f"{USER_SERVICE_URL}/users/{user_id}/membership",
                    json={
                        "membership_type": "결제회원",
                        "payment_date": data.get("approvedAt", datetime.now().isoformat())
                    },
                    timeout=10.0
                )
    except (ValueError, IndexError) as e:
        print(f"[결제 승인] user_id 추출 실패: {e}")

    return PaymentConfirmResponse(
        payment_key=data.get("paymentKey"),
        order_id=data.get("orderId"),
        status=data.get("status"),
        approved_at=data.get("approvedAt"),
        receipt_url=data.get("receipt", {}).get("url") if data.get("receipt") else None,
        total_amount=data.get("totalAmount", req.amount)
    )


@app.get("/payments/{payment_key}", response_model=PaymentStatusResponse)
async def get_payment(payment_key: str):
    """
    결제 상태 조회 API
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{TOSS_API_BASE}/payments/{payment_key}",
            headers=get_toss_auth_header(),
            timeout=10.0
        )

    if response.status_code != 200:
        raise HTTPException(status_code=404, detail="결제 정보를 찾을 수 없습니다")

    data = response.json()

    return PaymentStatusResponse(
        payment_key=data.get("paymentKey"),
        order_id=data.get("orderId"),
        status=data.get("status"),
        total_amount=data.get("totalAmount", 0),
        method=data.get("method"),
        approved_at=data.get("approvedAt")
    )


@app.post("/payments/cancel/{payment_key}")
async def cancel_payment(payment_key: str, cancel_reason: str = "고객 요청"):
    """
    결제 취소 API
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{TOSS_API_BASE}/payments/{payment_key}/cancel",
            headers=get_toss_auth_header(),
            json={"cancelReason": cancel_reason},
            timeout=30.0
        )

    if response.status_code != 200:
        error_data = response.json()
        raise HTTPException(
            status_code=400,
            detail=f"결제 취소 실패: {error_data.get('message', '알 수 없는 오류')}"
        )

    data = response.json()

    return {
        "status": "cancelled",
        "payment_key": payment_key,
        "cancel_amount": data.get("cancels", [{}])[0].get("cancelAmount", 0) if data.get("cancels") else 0
    }
