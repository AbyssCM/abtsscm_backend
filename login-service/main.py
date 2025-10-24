# login-service/main.py
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
import jwt
import datetime
import httpx

from jwt_utils import create_jwt, decode_jwt

app = FastAPI()

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173","http://localhost:5174","http://172.30.1.12:5173"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 환경 변수 (Docker 환경에서 세팅)
REST_API_KEY = os.getenv("KAKAO_REST_API_KEY")
CLIENT_SECRET = os.getenv("KAKAO_CLIENT_SECRET")
REDIRECT_URI = os.getenv("KAKAO_REDIRECT_URI")

USER_SERVICE_URL = os.getenv("USER_SERVICE_URL")


class KakaoCodeRequest(BaseModel):
    code: str

class SubmitRequest(BaseModel):
    username: str
    birthDate: str
    birthTime: str
    calendar: str
    ampm: str
    userphonenumber: str
    gender: str

@app.post("/login/kakao")
async def login_kakao(data: KakaoCodeRequest):
    print("[요청] 카카오 코드:", data.code)  # 요청 받은 코드 출력

    # 1. 카카오 access token 얻기
    token_url = "https://kauth.kakao.com/oauth/token"
    token_data = {
        "grant_type": "authorization_code",
        "client_id": REST_API_KEY,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": data.code,
    }
    token_res = requests.post(token_url, data=token_data)
    print("[카카오 토큰 요청] 상태:", token_res.status_code)
    print("[카카오 토큰 요청] 응답:", token_res.text)

    if token_res.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid authorization code")
    access_token = token_res.json().get("access_token")
    print("[카카오 access token]:", access_token)

    # 2. 카카오에서 이메일, 닉네임 가져오기
    user_info_res = requests.get(
        "https://kapi.kakao.com/v2/user/me",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    print("[카카오 사용자 정보 요청] 상태:", user_info_res.status_code)
    print("[카카오 사용자 정보 요청] 응답:", user_info_res.text)

    if user_info_res.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid Kakao token")

    user_info = user_info_res.json()
    kakao_account = user_info.get("kakao_account", {})
    nickname = kakao_account.get("profile", {}).get("nickname")
    kakao_id = user_info.get("id")  # 여기서 가져와야 함
    print(f"[카카오 사용자 정보] nickname: {nickname}, id: {kakao_id}")

    # 3. user-service에 이메일 확인 요청
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{USER_SERVICE_URL}/users/login-or-register", json={
            "kakao_id": str(kakao_id),  # 이메일 대신 카카오 ID
            "nickname": nickname
        })

    print("[User-service 요청] 상태:", response.status_code)
    print("[User-service 응답]:", response.text)

    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="User service error")

    user = response.json()

    # 4. 회원/비회원 판정
    if user.get("member_status") == "회원":
        url = f"{USER_SERVICE_URL}/users/{kakao_id}"
        try:
            response = httpx.get(url, timeout=5.0)
            response.raise_for_status()
            user_data = response.json()
            name = user_data.get("name")  # user-service에서 받은 이름
            print(f"[회원 조회] 이름: {name}")
        except httpx.HTTPStatusError as e:
            print(f"[UserService] 조회 실패: {e}")
            name = None
        except Exception as e:
            print(f"[UserService] 요청 에러: {e}")
            name = None
        print(f"[로그인] 회원")
        # 5. JWT 생성 후 반환
        jwt_token = create_jwt({"nickname": nickname, "kakaotoken" : access_token })
        print("[JWT 생성] token:", jwt_token)
    else:
        # 5. JWT 생성 후 반환
        jwt_token = create_jwt({"nickname": nickname, "kakaotoken" : access_token })
        print("[JWT 생성] token:", jwt_token)
        print(f"[로그인] 비회원")

    return {"jwt": jwt_token, "user": user}

@app.post("/submit")
async def submit_user_data(request: Request, data: SubmitRequest):
    # 1. JWT 토큰 가져오기
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="JWT 토큰이 필요합니다.")
    
    token = auth_header.split(" ")[1]

    # 2. JWT 디코드
    try:
        payload = decode_jwt(token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    print("디코드된 JWT:", payload)
    print("프론트에서 전달된 데이터:", data.dict())

    # 3. 카카오 토큰으로 카카오 API 호출
    kakao_token = payload.get("kakaotoken")
    if not kakao_token:
        raise HTTPException(status_code=401, detail="JWT에 카카오 토큰이 없습니다.")

    kakao_res = requests.get(
        "https://kapi.kakao.com/v2/user/me",
        headers={"Authorization": f"Bearer {kakao_token}"}
    )
    if kakao_res.status_code != 200:
        raise HTTPException(status_code=401, detail="카카오 토큰이 유효하지 않습니다.")

    kakao_info = kakao_res.json()
    kakao_id = kakao_info.get("id")
    kakao_account = kakao_info.get("kakao_account", {})
    email = kakao_account.get("email")
    print(email)

    # 4. 생년월일 + 시간 + 양력/음력 + 오전/오후 합치기
    birth_time = f"{data.birthTime[:2]}:{data.birthTime[2:]}"
    calendar_str = "양력" if data.calendar == "solar" else "음력"
    ampm_str = "오전" if data.ampm == "AM" else "오후"
    final_birth_str = f"{data.birthDate} {birth_time} {ampm_str} ({calendar_str})"

    # 5. 최종 JSON
    result = {
        **data.dict(),
        "kakao_id": kakao_id,
        "final_birth_str": final_birth_str,
    }

    print("최종 JSON:", result)

    # 6. user-service로 전송
    USER_SERVICE_URL = os.getenv("USER_SERVICE_URL")  # 예: http://user-service:8000/users
    async with httpx.AsyncClient() as client:
        user_res = await client.post(f"{USER_SERVICE_URL}/users/add", json=result)
    
    if user_res.status_code != 200:
        raise HTTPException(status_code=500, detail="User service DB 삽입 실패")
    
    print("User-service 응답:", user_res.json())

    return {"status": "success", "jwt_payload": payload, "submitted_data": result, "user_service": user_res.json()}