# login-service/jwt_utils.py
import jwt
import datetime
import os

SECRET_KEY = os.getenv("JWT_SECRET", "supersecret")
ALGORITHM = "HS256"

def create_jwt(data: dict):
    to_encode = data.copy()
    expire = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_jwt(token: str):
    """
    JWT 디코드 함수
    만료된 토큰은 예외 발생
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise ValueError("JWT 토큰이 만료되었습니다.")
    except jwt.InvalidTokenError:
        raise ValueError("유효하지 않은 JWT 토큰입니다.")
