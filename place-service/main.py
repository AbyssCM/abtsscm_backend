# place-service/main.py
# 데이트 장소 큐레이팅 서비스
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from db import SessionLocal, DatePlace, DateCourse, DateCoursePlace, create_tables
from naver_api import (
    search_places,
    search_places_by_category,
    parse_place_result,
    DATE_CATEGORIES,
    NaverAPIError
)

app = FastAPI(title="Place Service", description="데이트 장소 큐레이팅 서비스")

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


# ===== Pydantic 모델 =====

class PlaceSearchRequest(BaseModel):
    query: str
    display: int = 5


class PlaceCategorySearchRequest(BaseModel):
    location: str          # 위치 (예: "강남", "홍대")
    category: str          # 카테고리 키
    display: int = 5


class CourseCreateRequest(BaseModel):
    creator_id: int
    title: str
    description: Optional[str] = None


class CoursePlaceAddRequest(BaseModel):
    place_id: int
    order_index: int
    memo: Optional[str] = None
    estimated_duration: Optional[int] = None


class CourseShareRequest(BaseModel):
    shared_with: int       # 공유 대상 user_id


# ===== 헬스체크 =====

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "place-service"}


# ===== 장소 검색 API =====

@app.get("/places/search")
async def search_places_api(
    query: str = Query(..., description="검색어"),
    display: int = Query(5, ge=1, le=5, description="결과 개수")
):
    """
    장소 검색 (네이버 API)
    - query: 검색어 (예: "강남 카페", "홍대 맛집")
    - display: 결과 개수 (1-5)
    """
    try:
        result = await search_places(query, display=display)
        places = [parse_place_result(item) for item in result.get("items", [])]

        # DB에 캐싱 (선택적)
        db = SessionLocal()
        try:
            for place_data in places:
                # 이름으로 중복 체크 (간단한 캐싱)
                existing = db.query(DatePlace).filter(
                    DatePlace.name == place_data["name"],
                    DatePlace.address == place_data["address"]
                ).first()

                if not existing:
                    new_place = DatePlace(
                        **place_data,
                        created_at=datetime.now(),
                        updated_at=datetime.now()
                    )
                    db.add(new_place)

            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[캐싱 오류] {e}")
        finally:
            db.close()

        return {"total": len(places), "places": places}

    except NaverAPIError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"검색 오류: {str(e)}")


@app.get("/places/category")
async def search_places_by_category_api(
    location: str = Query(..., description="위치 (예: 강남, 홍대)"),
    category: str = Query(..., description="카테고리"),
    display: int = Query(5, ge=1, le=5, description="결과 개수")
):
    """
    카테고리 기반 장소 검색
    - location: 위치 (예: "강남", "홍대")
    - category: 카테고리 (예: "카페", "레스토랑")
    """
    try:
        places = await search_places_by_category(location, category, display)
        return {"total": len(places), "places": places}

    except NaverAPIError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"검색 오류: {str(e)}")


@app.get("/places/categories")
def get_categories():
    """
    사용 가능한 카테고리 목록 반환
    """
    return {
        "categories": list(DATE_CATEGORIES.keys()),
        "details": DATE_CATEGORIES
    }


@app.get("/places/{place_id}")
def get_place_detail(place_id: int):
    """
    캐싱된 장소 상세 정보 조회
    """
    db = SessionLocal()
    try:
        place = db.query(DatePlace).filter(DatePlace.id == place_id).first()
        if not place:
            raise HTTPException(status_code=404, detail="장소를 찾을 수 없습니다")

        return {
            "id": place.id,
            "name": place.name,
            "category": place.category,
            "address": place.address,
            "road_address": place.road_address,
            "phone": place.phone,
            "description": place.description,
            "image_url": place.image_url,
            "homepage_url": place.homepage_url,
            "latitude": place.latitude,
            "longitude": place.longitude
        }
    finally:
        db.close()


# ===== 코스 관리 API =====

@app.post("/courses")
def create_course(data: CourseCreateRequest):
    """
    데이트 코스 생성
    """
    db = SessionLocal()
    try:
        course = DateCourse(
            creator_id=data.creator_id,
            title=data.title,
            description=data.description,
            status="작성중",
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        db.add(course)
        db.commit()
        db.refresh(course)

        return {
            "message": "코스가 생성되었습니다",
            "course_id": course.id
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"코스 생성 실패: {str(e)}")
    finally:
        db.close()


@app.get("/courses/my")
def get_my_courses(user_id: int = Query(..., description="사용자 ID")):
    """
    내가 만든 코스 목록
    """
    db = SessionLocal()
    try:
        courses = db.query(DateCourse).filter(
            DateCourse.creator_id == user_id
        ).order_by(DateCourse.created_at.desc()).all()

        result = []
        for course in courses:
            # 코스에 포함된 장소 수
            place_count = db.query(DateCoursePlace).filter(
                DateCoursePlace.course_id == course.id
            ).count()

            result.append({
                "id": course.id,
                "title": course.title,
                "description": course.description,
                "status": course.status,
                "is_shared": course.is_shared,
                "shared_with": course.shared_with,
                "place_count": place_count,
                "created_at": course.created_at.isoformat() if course.created_at else None
            })

        return {"total": len(result), "courses": result}
    finally:
        db.close()


@app.get("/courses/shared")
def get_shared_courses(user_id: int = Query(..., description="사용자 ID")):
    """
    나에게 공유된 코스 목록
    """
    db = SessionLocal()
    try:
        courses = db.query(DateCourse).filter(
            DateCourse.shared_with == user_id,
            DateCourse.is_shared == True
        ).order_by(DateCourse.shared_at.desc()).all()

        result = []
        for course in courses:
            place_count = db.query(DateCoursePlace).filter(
                DateCoursePlace.course_id == course.id
            ).count()

            result.append({
                "id": course.id,
                "title": course.title,
                "description": course.description,
                "creator_id": course.creator_id,
                "place_count": place_count,
                "shared_at": course.shared_at.isoformat() if course.shared_at else None
            })

        return {"total": len(result), "courses": result}
    finally:
        db.close()


@app.get("/courses/{course_id}")
def get_course_detail(course_id: int):
    """
    코스 상세 정보 (장소 목록 포함)
    """
    db = SessionLocal()
    try:
        course = db.query(DateCourse).filter(DateCourse.id == course_id).first()
        if not course:
            raise HTTPException(status_code=404, detail="코스를 찾을 수 없습니다")

        # 코스에 포함된 장소 목록
        course_places = db.query(DateCoursePlace).filter(
            DateCoursePlace.course_id == course_id
        ).order_by(DateCoursePlace.order_index).all()

        places = []
        for cp in course_places:
            place = db.query(DatePlace).filter(DatePlace.id == cp.place_id).first()
            if place:
                places.append({
                    "order_index": cp.order_index,
                    "place": {
                        "id": place.id,
                        "name": place.name,
                        "category": place.category,
                        "address": place.address,
                        "phone": place.phone
                    },
                    "memo": cp.memo,
                    "estimated_duration": cp.estimated_duration
                })

        return {
            "id": course.id,
            "title": course.title,
            "description": course.description,
            "creator_id": course.creator_id,
            "status": course.status,
            "is_shared": course.is_shared,
            "shared_with": course.shared_with,
            "places": places,
            "created_at": course.created_at.isoformat() if course.created_at else None
        }
    finally:
        db.close()


@app.post("/courses/{course_id}/places")
def add_place_to_course(course_id: int, data: CoursePlaceAddRequest):
    """
    코스에 장소 추가
    """
    db = SessionLocal()
    try:
        # 코스 존재 확인
        course = db.query(DateCourse).filter(DateCourse.id == course_id).first()
        if not course:
            raise HTTPException(status_code=404, detail="코스를 찾을 수 없습니다")

        # 장소 존재 확인
        place = db.query(DatePlace).filter(DatePlace.id == data.place_id).first()
        if not place:
            raise HTTPException(status_code=404, detail="장소를 찾을 수 없습니다")

        # 중복 체크
        existing = db.query(DateCoursePlace).filter(
            DateCoursePlace.course_id == course_id,
            DateCoursePlace.place_id == data.place_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="이미 추가된 장소입니다")

        course_place = DateCoursePlace(
            course_id=course_id,
            place_id=data.place_id,
            order_index=data.order_index,
            memo=data.memo,
            estimated_duration=data.estimated_duration,
            created_at=datetime.now()
        )
        db.add(course_place)

        # 코스 업데이트 시간 갱신
        course.updated_at = datetime.now()
        db.commit()

        return {"message": "장소가 추가되었습니다"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"장소 추가 실패: {str(e)}")
    finally:
        db.close()


@app.delete("/courses/{course_id}/places/{place_id}")
def remove_place_from_course(course_id: int, place_id: int):
    """
    코스에서 장소 제거
    """
    db = SessionLocal()
    try:
        course_place = db.query(DateCoursePlace).filter(
            DateCoursePlace.course_id == course_id,
            DateCoursePlace.place_id == place_id
        ).first()

        if not course_place:
            raise HTTPException(status_code=404, detail="코스에 해당 장소가 없습니다")

        db.delete(course_place)
        db.commit()

        return {"message": "장소가 제거되었습니다"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"장소 제거 실패: {str(e)}")
    finally:
        db.close()


@app.post("/courses/{course_id}/share")
def share_course(course_id: int, data: CourseShareRequest):
    """
    매칭 상대와 코스 공유
    """
    db = SessionLocal()
    try:
        course = db.query(DateCourse).filter(DateCourse.id == course_id).first()
        if not course:
            raise HTTPException(status_code=404, detail="코스를 찾을 수 없습니다")

        course.is_shared = True
        course.shared_with = data.shared_with
        course.shared_at = datetime.now()
        course.status = "완성"
        course.updated_at = datetime.now()

        db.commit()

        return {"message": "코스가 공유되었습니다"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"공유 실패: {str(e)}")
    finally:
        db.close()


@app.put("/courses/{course_id}/complete")
def complete_course(course_id: int):
    """
    코스 완성 처리
    """
    db = SessionLocal()
    try:
        course = db.query(DateCourse).filter(DateCourse.id == course_id).first()
        if not course:
            raise HTTPException(status_code=404, detail="코스를 찾을 수 없습니다")

        course.status = "완성"
        course.updated_at = datetime.now()
        db.commit()

        return {"message": "코스가 완성되었습니다"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"상태 변경 실패: {str(e)}")
    finally:
        db.close()


@app.delete("/courses/{course_id}")
def delete_course(course_id: int):
    """
    코스 삭제
    """
    db = SessionLocal()
    try:
        course = db.query(DateCourse).filter(DateCourse.id == course_id).first()
        if not course:
            raise HTTPException(status_code=404, detail="코스를 찾을 수 없습니다")

        # 연결된 장소 관계 삭제
        db.query(DateCoursePlace).filter(
            DateCoursePlace.course_id == course_id
        ).delete()

        db.delete(course)
        db.commit()

        return {"message": "코스가 삭제되었습니다"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"삭제 실패: {str(e)}")
    finally:
        db.close()


# ===== 앱 시작 시 테이블 생성 =====

@app.on_event("startup")
def startup():
    create_tables()
    print("[place-service] 데이터베이스 테이블 생성 완료")
