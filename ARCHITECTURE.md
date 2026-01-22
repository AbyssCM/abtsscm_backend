# ABTSSCM Backend Architecture

> AI 바이브 코더를 위한 아키텍처 문서 (tok_mcp 기반)

## Overview

결혼 매칭 서비스를 위한 마이크로서비스 백엔드 아키텍처입니다.

| 항목 | 값 |
|------|-----|
| 서비스 유형 | B2C 결혼 매칭 서비스 |
| 아키텍처 | 마이크로서비스 |
| 예상 규모 | DAU ~100명 (MVP) |
| 월 예산 | $50 이하 |

## System Architecture

```
                                    ┌──────────────────────────────────────────────────────────┐
                                    │                        AWS Cloud                          │
                                    ├──────────────────────────────────────────────────────────┤
                                    │                                                           │
┌──────────────────┐                │   ┌─────────────────┐                                    │
│  React Frontend  │                │   │  login-service  │                                    │
│  (www.abysscm)   │───────────────▶│   │     :8000       │                                    │
└──────────────────┘                │   └────────┬────────┘                                    │
                                    │            │                                              │
┌──────────────────┐                │            ▼                                              │
│  Admin Frontend  │                │   ┌─────────────────┐      ┌─────────────────┐           │
│ (admin.abysscm)  │───────────────▶│   │  user-service   │─────▶│ RDS PostgreSQL  │           │
└──────────────────┘                │   │     :8001       │      │   (db.t3.micro) │           │
                                    │   └────────┬────────┘      └─────────────────┘           │
                                    │            │                        ▲                     │
                                    │            │               ┌────────┴────────┐           │
                                    │            └──────────────▶│     AWS S3      │           │
                                    │                            │  (사진/메모)     │           │
                                    │   ┌─────────────────┐      └─────────────────┘           │
                                    │   │   pay-service   │                                    │
                                    │   │     :8002       │                                    │
                                    │   └────────┬────────┘                                    │
                                    │            │                                              │
                                    │   ┌─────────────────┐                                    │
                                    │   │  place-service  │                                    │
                                    │   │     :8003       │                                    │
                                    │   └────────┬────────┘                                    │
                                    │            │                                              │
                                    │   ┌─────────────────┐      ┌─────────────────┐           │
                                    │   │ notification-   │─────▶│  Firebase FCM   │           │
                                    │   │ service :8004   │      └─────────────────┘           │
                                    │   └─────────────────┘                                    │
                                    │            │                                              │
                                    │   ┌─────────────────┐                                    │
                                    │   │  chat-service   │◀─────WebSocket                     │
                                    │   │     :8005       │                                    │
                                    │   └────────┬────────┘                                    │
                                    │            │                                              │
                                    └────────────┼──────────────────────────────────────────────┘
                                                 │
                              ┌──────────────────┼──────────────────┐
                              ▼                  ▼                  ▼
                ┌─────────────────────┐  ┌─────────────┐  ┌─────────────────┐
                │  Toss Payments API  │  │  Kakao API  │  │  Naver Maps API │
                └─────────────────────┘  └─────────────┘  └─────────────────┘
```

## Services

### login-service (Port 8000)

| 항목 | 설명 |
|------|------|
| 책임 | 인증 및 세션 관리 (일반 회원 + 관리자) |
| 기술 | FastAPI, JWT (HS256) |
| 외부 연동 | 카카오 OAuth 2.0 |

**엔드포인트:**
| Method | Path | 설명 |
|--------|------|------|
| POST | `/login/kakao` | 카카오 인증 코드로 로그인 |
| POST | `/submit` | 회원가입 정보 제출 |
| POST | `/admin/login/kakao` | 관리자 카카오 로그인 (허용된 계정만) |
| GET | `/admin/verify` | 관리자 JWT 토큰 검증 |

### user-service (Port 8001)

| 항목 | 설명 |
|------|------|
| 책임 | 회원 정보 CRUD, 매칭 관리, 상담/만남 관리 |
| 기술 | FastAPI, SQLAlchemy, PostgreSQL |
| 외부 연동 | AWS S3 (메모 저장) |

**회원 엔드포인트:**
| Method | Path | 설명 |
|--------|------|------|
| POST | `/users/login-or-register` | 로그인/등록 확인 |
| POST | `/users/add` | 새 회원 추가 |
| GET | `/users/{kakao_id}` | 회원 정보 조회 |
| PATCH | `/users/{user_id}/membership` | 회원 등급 업데이트 |

**상담 엔드포인트:**
| Method | Path | 설명 |
|--------|------|------|
| POST | `/consultations` | 상담 요청 생성 |
| GET | `/consultations/my` | 내 상담 목록 |
| GET | `/consultations/{id}` | 상담 상세 조회 |
| PUT | `/consultations/{id}/cancel` | 상담 취소 |

**만남 엔드포인트:**
| Method | Path | 설명 |
|--------|------|------|
| POST | `/meetings` | 만남 일정 생성 |
| GET | `/meetings/my` | 내 만남 목록 |
| GET | `/meetings/{id}` | 만남 상세 조회 |
| PUT | `/meetings/{id}/complete` | 만남 완료 처리 |
| PUT | `/meetings/{id}/cancel` | 만남 취소 |
| POST | `/meetings/{id}/reviews` | 후기 작성 |

**관리자 전용 엔드포인트:**
| Method | Path | 설명 |
|--------|------|------|
| GET | `/admin/users` | 전체 회원 목록 |
| GET | `/admin/users/search` | 회원 필터링 조회 (상태, 결제, 매칭 등) |
| GET | `/admin/users/{user_id}` | 회원 상세 조회 |
| PUT | `/admin/users/memo/{user_id}` | 회원 메모 저장 (S3) |
| GET | `/admin/users/memo/{user_id}` | 회원 메모 조회 (S3) |
| POST | `/admin/users/match/{user_id}/{partner_id}` | 회원 매칭 처리 |
| DELETE | `/admin/users/match/{user_id}` | 매칭 해제 |
| GET | `/admin/users/candidates/{user_id}` | 매칭 후보자 목록 조회 |
| DELETE | `/admin/users/{user_id}` | 회원 탈퇴 처리 |
| POST | `/admin/users/{user_id}/ban` | 회원 추방 (블랙리스트) |
| GET | `/admin/stats` | 통계 대시보드 (회원수, 매칭수 등) |
| GET | `/admin/consultations` | 전체 상담 목록 |
| PUT | `/admin/consultations/{id}/confirm` | 상담 확정 |
| PUT | `/admin/consultations/{id}/complete` | 상담 완료 처리 |
| GET | `/admin/meetings` | 전체 만남 목록 |
| GET | `/admin/reviews` | 전체 후기 열람 |
| GET | `/admin/meetings/stats` | 만남 통계 |

**프로필 엔드포인트:**
| Method | Path | 설명 |
|--------|------|------|
| GET | `/profile/my` | 내 프로필 조회 |
| PUT | `/profile/my` | 프로필 수정 |
| POST | `/profile/photos` | 사진 업로드 (S3) |
| DELETE | `/profile/photos/{id}` | 사진 삭제 |
| PUT | `/profile/photos/{id}/order` | 사진 순서 변경 |

**매칭 추천 엔드포인트:**
| Method | Path | 설명 |
|--------|------|------|
| GET | `/recommendations` | 내 추천 목록 |
| POST | `/admin/recommendations/calculate` | 점수 재계산 |

**성혼 후기 엔드포인트:**
| Method | Path | 설명 |
|--------|------|------|
| POST | `/success-stories` | 성혼 후기 작성 |
| GET | `/success-stories/public` | 공개 후기 목록 |
| GET | `/admin/success-stories` | 전체 후기 관리 |
| PUT | `/admin/success-stories/{id}/approve` | 후기 승인 |
| PUT | `/admin/success-stories/{id}/reject` | 후기 거부 |

**추천인 엔드포인트:**
| Method | Path | 설명 |
|--------|------|------|
| GET | `/referral/my-code` | 내 추천 코드 조회 |
| POST | `/referral/apply` | 추천 코드 적용 |
| GET | `/referral/my-referrals` | 내가 추천한 사람 목록 |
| GET | `/admin/referrals` | 전체 추천 현황 |
| PUT | `/admin/referrals/{id}/reward` | 보상 지급 처리 |

**대시보드 엔드포인트:**
| Method | Path | 설명 |
|--------|------|------|
| GET | `/admin/dashboard` | 종합 대시보드 |
| GET | `/admin/analytics/users` | 사용자 분석 |
| GET | `/admin/analytics/matches` | 매칭 분석 |
| GET | `/admin/analytics/consultations` | 상담 분석 |
| GET | `/admin/photos/pending` | 승인 대기 사진 |
| PUT | `/admin/photos/{id}/approve` | 사진 승인 |
| PUT | `/admin/photos/{id}/reject` | 사진 거부 |

### pay-service (Port 8002)

| 항목 | 설명 |
|------|------|
| 책임 | 결제 처리 |
| 기술 | FastAPI, Toss Payments API |
| 외부 연동 | 토스페이먼츠 |

**엔드포인트:**
| Method | Path | 설명 |
|--------|------|------|
| POST | `/payments/ready` | 결제 준비 |
| POST | `/payments/confirm` | 결제 승인 |
| GET | `/payments/{payment_key}` | 결제 내역 조회 |
| GET | `/health` | 헬스체크 |

### place-service (Port 8003)

| 항목 | 설명 |
|------|------|
| 책임 | 데이트 장소 큐레이팅 |
| 기술 | FastAPI, Naver Maps API |
| 외부 연동 | 네이버 지역 검색 API |

**장소 검색 엔드포인트:**
| Method | Path | 설명 |
|--------|------|------|
| GET | `/places/search` | 장소 검색 (네이버 API) |
| GET | `/places/category` | 카테고리 기반 장소 검색 |
| GET | `/places/categories` | 사용 가능한 카테고리 목록 |
| GET | `/places/{place_id}` | 캐싱된 장소 상세 정보 |

**코스 관리 엔드포인트:**
| Method | Path | 설명 |
|--------|------|------|
| POST | `/courses` | 데이트 코스 생성 |
| GET | `/courses/my` | 내 코스 목록 |
| GET | `/courses/shared` | 공유받은 코스 목록 |
| GET | `/courses/{course_id}` | 코스 상세 (장소 포함) |
| POST | `/courses/{course_id}/places` | 코스에 장소 추가 |
| DELETE | `/courses/{course_id}/places/{place_id}` | 코스에서 장소 제거 |
| POST | `/courses/{course_id}/share` | 매칭 상대와 코스 공유 |
| PUT | `/courses/{course_id}/complete` | 코스 완성 처리 |
| DELETE | `/courses/{course_id}` | 코스 삭제 |
| GET | `/health` | 헬스체크 |

### notification-service (Port 8004)

| 항목 | 설명 |
|------|------|
| 책임 | 푸시 알림 관리 (FCM) |
| 기술 | FastAPI, Firebase Admin SDK |
| 외부 연동 | Firebase Cloud Messaging |

**엔드포인트:**
| Method | Path | 설명 |
|--------|------|------|
| POST | `/devices/register` | FCM 토큰 등록 |
| DELETE | `/devices/{token}` | FCM 토큰 삭제 |
| POST | `/send` | 알림 전송 (내부용) |
| POST | `/send/batch` | 배치 알림 전송 |
| GET | `/notifications/my` | 내 알림 목록 |
| PUT | `/notifications/{id}/read` | 알림 읽음 처리 |
| GET | `/health` | 헬스체크 |

### chat-service (Port 8005)

| 항목 | 설명 |
|------|------|
| 책임 | 실시간 채팅 (WebSocket) |
| 기술 | FastAPI, WebSocket, SQLAlchemy |
| 외부 연동 | AWS S3 (이미지), notification-service |

**REST 엔드포인트:**
| Method | Path | 설명 |
|--------|------|------|
| POST | `/rooms` | 채팅방 생성 |
| GET | `/rooms` | 내 채팅방 목록 |
| GET | `/rooms/{room_id}/messages` | 메시지 기록 조회 |
| POST | `/rooms/{room_id}/messages` | 메시지 전송 |
| POST | `/rooms/{room_id}/images` | 이미지 업로드 |
| GET | `/health` | 헬스체크 |

**WebSocket 엔드포인트:**
| Path | 설명 |
|------|------|
| `/ws/{room_id}?user_id=` | 실시간 채팅 연결 |

**WebSocket 메시지 타입:**
- `message`: 텍스트/이미지 메시지
- `typing`: 타이핑 인디케이터
- `read`: 읽음 처리

## Data Flow

### 회원가입 플로우

```
1. 프론트엔드 ──[카카오 인증코드]──▶ login-service
2. login-service ──[토큰 교환]──▶ 카카오 API
3. login-service ──[회원 조회]──▶ user-service
4. user-service ──[저장]──▶ PostgreSQL
5. login-service ──[JWT 토큰]──▶ 프론트엔드
```

### 결제 플로우

```
1. 프론트엔드 ──[결제 요청]──▶ pay-service
2. pay-service ──[결제 준비]──▶ 토스페이먼츠
3. pay-service ──[결제창 URL]──▶ 프론트엔드
4. 사용자 ──[결제 진행]──▶ 토스 결제창
5. 토스 ──[리다이렉트]──▶ 프론트엔드
6. 프론트엔드 ──[승인 요청]──▶ pay-service
7. pay-service ──[최종 승인]──▶ 토스페이먼츠
8. pay-service ──[등급 업데이트]──▶ user-service
```

## Data Model

### User 테이블

```sql
CREATE TABLE users (
    user_id BIGINT PRIMARY KEY,          -- 카카오 ID
    name VARCHAR(50) NOT NULL,           -- 이름
    email VARCHAR(100) UNIQUE,           -- 이메일
    phone_number VARCHAR(20),            -- 전화번호
    age VARCHAR(3),                      -- 나이
    gender VARCHAR(2),                   -- 성별 (남/여)
    birth_date VARCHAR(30),              -- 생년월일 문자열
    matching_count INTEGER DEFAULT 0,    -- 매칭 횟수
    status VARCHAR(10) DEFAULT '매칭전', -- 상태
    first_consultation TIMESTAMP,        -- 최초 상담일
    last_consultation TIMESTAMP,         -- 마지막 상담일
    consultation_count INTEGER DEFAULT 0,-- 상담 횟수
    matched_partner BIGINT,              -- 매칭된 상대 ID
    membership_type VARCHAR(10),         -- 회원 등급
    payment_date TIMESTAMP               -- 결제일
);
```

### Consultation 테이블 (상담 요청)

```sql
CREATE TABLE consultations (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id),
    requested_date DATE NOT NULL,        -- 희망 상담일
    requested_time VARCHAR(10) NOT NULL, -- 희망 시간
    consultation_type VARCHAR(20) NOT NULL, -- 초기상담/매칭상담/사후상담
    description TEXT,                    -- 상담 내용
    status VARCHAR(20) DEFAULT '요청됨', -- 요청됨/확인됨/완료됨/취소됨
    admin_note TEXT,                     -- 관리자 메모
    confirmed_date DATE,                 -- 확정된 상담일
    confirmed_time VARCHAR(10),          -- 확정된 시간
    created_at TIMESTAMP
);
```

### Meeting 테이블 (만남 일정)

```sql
CREATE TABLE meetings (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id),
    partner_id BIGINT REFERENCES users(user_id),
    meeting_date DATE NOT NULL,          -- 만남 날짜
    meeting_time VARCHAR(10),            -- 만남 시간
    location VARCHAR(200),               -- 만남 장소
    status VARCHAR(20) DEFAULT '예약됨', -- 예약됨/완료됨/취소됨
    created_at TIMESTAMP
);
```

### MeetingReview 테이블 (만남 후기)

```sql
CREATE TABLE meeting_reviews (
    id SERIAL PRIMARY KEY,
    meeting_id INTEGER REFERENCES meetings(id),
    reviewer_id BIGINT REFERENCES users(user_id),
    reviewed_id BIGINT REFERENCES users(user_id),
    rating INTEGER NOT NULL,             -- 1-5점 평가
    content TEXT,                        -- 후기 내용
    next_meeting_intent VARCHAR(20),     -- 원함/미정/원하지않음
    is_private BOOLEAN DEFAULT TRUE,     -- 관리자만 열람
    created_at TIMESTAMP
);
```

### DatePlace 테이블 (장소 캐싱)

```sql
CREATE TABLE date_places (
    id SERIAL PRIMARY KEY,
    naver_place_id VARCHAR(100) UNIQUE,
    name VARCHAR(200) NOT NULL,
    category VARCHAR(100),
    address VARCHAR(500),
    road_address VARCHAR(500),
    latitude FLOAT,
    longitude FLOAT,
    phone VARCHAR(20),
    description TEXT,
    image_url VARCHAR(500),
    homepage_url VARCHAR(500),
    created_at TIMESTAMP
);
```

### DateCourse 테이블 (데이트 코스)

```sql
CREATE TABLE date_courses (
    id SERIAL PRIMARY KEY,
    creator_id BIGINT NOT NULL,          -- 생성자 user_id
    title VARCHAR(200) NOT NULL,
    description TEXT,
    is_shared BOOLEAN DEFAULT FALSE,
    shared_with BIGINT,                  -- 공유 대상 user_id
    shared_at TIMESTAMP,
    status VARCHAR(20) DEFAULT '작성중', -- 작성중/완성/사용됨
    created_at TIMESTAMP
);
```

### UserProfile 테이블 (상세 프로필)

```sql
CREATE TABLE user_profiles (
    id SERIAL PRIMARY KEY,
    user_id BIGINT UNIQUE REFERENCES users(user_id),
    height INTEGER,                      -- 키 (cm)
    job VARCHAR(100),                    -- 직업
    company VARCHAR(100),                -- 회사/학교
    education VARCHAR(50),               -- 학력
    religion VARCHAR(20),                -- 종교
    smoking VARCHAR(20),                 -- 흡연 여부
    drinking VARCHAR(20),                -- 음주 여부
    mbti VARCHAR(4),
    hobbies TEXT,                        -- JSON 배열
    introduction TEXT,                   -- 자기소개
    ideal_age_min INTEGER,
    ideal_age_max INTEGER,
    ideal_height_min INTEGER,
    ideal_height_max INTEGER,
    ideal_location VARCHAR(100),
    ideal_religion VARCHAR(20),
    ideal_smoking VARCHAR(20),
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

### UserPhoto 테이블 (프로필 사진)

```sql
CREATE TABLE user_photos (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id),
    photo_url VARCHAR(500) NOT NULL,     -- S3 URL
    photo_type VARCHAR(20),              -- profile/additional
    order_index INTEGER DEFAULT 0,
    is_approved BOOLEAN DEFAULT FALSE,   -- 관리자 승인
    created_at TIMESTAMP
);
```

### ChatRoom 테이블 (채팅방)

```sql
CREATE TABLE chat_rooms (
    id SERIAL PRIMARY KEY,
    user1_id BIGINT NOT NULL,
    user2_id BIGINT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP,
    last_message_at TIMESTAMP
);
```

### Message 테이블 (채팅 메시지)

```sql
CREATE TABLE messages (
    id SERIAL PRIMARY KEY,
    room_id INTEGER REFERENCES chat_rooms(id),
    sender_id BIGINT NOT NULL,
    content TEXT,
    message_type VARCHAR(20),            -- text/image
    image_url VARCHAR(500),              -- S3 URL
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP
);
```

### SuccessStory 테이블 (성혼 후기)

```sql
CREATE TABLE success_stories (
    id SERIAL PRIMARY KEY,
    user1_id BIGINT REFERENCES users(user_id),
    user2_id BIGINT REFERENCES users(user_id),
    title VARCHAR(200),
    content TEXT,
    photo_url VARCHAR(500),
    is_public BOOLEAN DEFAULT FALSE,
    display_names VARCHAR(100),
    status VARCHAR(20),                  -- draft/pending/approved/rejected
    admin_note TEXT,
    created_at TIMESTAMP,
    approved_at TIMESTAMP
);
```

### Referral 테이블 (추천인)

```sql
CREATE TABLE referrals (
    id SERIAL PRIMARY KEY,
    referrer_id BIGINT REFERENCES users(user_id),
    referee_id BIGINT REFERENCES users(user_id),
    referral_code VARCHAR(20),
    reward_status VARCHAR(20),           -- pending/eligible/rewarded
    reward_type VARCHAR(50),
    created_at TIMESTAMP,
    rewarded_at TIMESTAMP
);
```

## Infrastructure

### AWS Resources

| 서비스 | 사양 | 용도 | 예상 비용 |
|--------|------|------|-----------|
| RDS PostgreSQL | db.t3.micro, 20GB | 회원 데이터 | ~$12/월 |
| S3 | 1GB 미만 | 사용자 메모 JSON | ~$0.02/월 |
| **합계** | | | **~$12/월** |

### Docker Compose 구성

```yaml
services:
  login-service:        8000:8000
  user-service:         8001:8001
  pay-service:          8002:8002
  place-service:        8003:8003
  notification-service: 8004:8004
  chat-service:         8005:8005
```

## Security

### 인증 방식
- **외부 인증**: 카카오 OAuth 2.0
- **내부 인증**: JWT (HS256, 1시간 만료)

### CORS 허용 도메인
```
http://www.abysscm.com
http://www.abysscm.com:5173
http://www.abysscm.com:5174
http://admin.abysscm.com
http://admin.abysscm.com:5173
http://admin.abysscm.com:5174
```

## Environment Variables

### login-service
```env
KAKAO_REST_API_KEY=      # 카카오 REST API 키
KAKAO_CLIENT_SECRET=     # 카카오 클라이언트 시크릿
KAKAO_REDIRECT_URI=      # 카카오 리다이렉트 URI
USER_SERVICE_URL=        # user-service 내부 URL
JWT_SECRET=              # JWT 서명 키
```

### user-service
```env
DB_USER=                 # PostgreSQL 사용자
DB_PASSWORD=             # PostgreSQL 비밀번호
DB_HOST=                 # PostgreSQL 호스트
DB_PORT=5432             # PostgreSQL 포트
DB_NAME=                 # 데이터베이스 이름
AWS_ACCESS_KEY_ID=       # AWS 액세스 키
AWS_SECRET_ACCESS_KEY=   # AWS 시크릿 키
AWS_REGION=              # AWS 리전
S3_BUCKET_NAME=          # S3 버킷 이름
```

### pay-service
```env
TOSS_CLIENT_KEY=         # 토스 클라이언트 키
TOSS_SECRET_KEY=         # 토스 시크릿 키
USER_SERVICE_URL=        # user-service 내부 URL
```

### place-service
```env
DB_USER=                 # PostgreSQL 사용자
DB_PASSWORD=             # PostgreSQL 비밀번호
DB_HOST=                 # PostgreSQL 호스트
DB_PORT=5432             # PostgreSQL 포트
DB_NAME=                 # 데이터베이스 이름
NAVER_CLIENT_ID=         # 네이버 Client ID
NAVER_CLIENT_SECRET=     # 네이버 Client Secret
```

### notification-service
```env
DB_USER=                 # PostgreSQL 사용자
DB_PASSWORD=             # PostgreSQL 비밀번호
DB_HOST=                 # PostgreSQL 호스트
DB_PORT=5432             # PostgreSQL 포트
DB_NAME=                 # 데이터베이스 이름
FIREBASE_CREDENTIALS_JSON= # Base64 인코딩된 Firebase 서비스 계정
```

### chat-service
```env
DB_USER=                 # PostgreSQL 사용자
DB_PASSWORD=             # PostgreSQL 비밀번호
DB_HOST=                 # PostgreSQL 호스트
DB_PORT=5432             # PostgreSQL 포트
DB_NAME=                 # 데이터베이스 이름
AWS_ACCESS_KEY_ID=       # AWS 액세스 키
AWS_SECRET_ACCESS_KEY=   # AWS 시크릿 키
AWS_REGION=              # AWS 리전
S3_BUCKET_NAME=          # S3 버킷 이름
NOTIFICATION_SERVICE_URL= # 알림 서비스 URL
```

## Scaling Strategy

### 현재 (DAU ~100)
- 단일 인스턴스 구성
- 동기 처리로 충분

### 미래 확장 시 (DAU 1,000+)
- 로드 밸런서 추가 (ALB)
- 서비스별 독립 스케일링
- Redis 캐시 도입
- RDS 스케일업 (db.t3.small)

## Development

### 로컬 실행
```bash
# 빌드 및 실행
docker-compose up --build

# 백그라운드 실행
docker-compose up -d

# 로그 확인
docker-compose logs -f
```

### API 문서
- login-service: http://localhost:8000/docs
- user-service: http://localhost:8001/docs
- pay-service: http://localhost:8002/docs
- place-service: http://localhost:8003/docs
- notification-service: http://localhost:8004/docs
- chat-service: http://localhost:8005/docs
