# place-service/naver_api.py
# 네이버 지도 API 연동 모듈
import os
import httpx
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

# 네이버 API 기본 URL
NAVER_LOCAL_SEARCH_URL = "https://openapi.naver.com/v1/search/local.json"
NAVER_GEOCODE_URL = "https://naveropenapi.apigw.ntruss.com/map-geocode/v2/geocode"


class NaverAPIError(Exception):
    """네이버 API 에러"""
    pass


async def search_places(
    query: str,
    display: int = 10,
    start: int = 1,
    sort: str = "random"
) -> Dict[str, Any]:
    """
    네이버 지역 검색 API

    Args:
        query: 검색어 (예: "강남 카페", "홍대 레스토랑")
        display: 결과 개수 (1-5)
        start: 시작 인덱스
        sort: 정렬 방식 (random/comment)

    Returns:
        검색 결과 딕셔너리
    """
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        raise NaverAPIError("네이버 API 키가 설정되지 않았습니다")

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }

    params = {
        "query": query,
        "display": min(display, 5),  # 최대 5개
        "start": start,
        "sort": sort
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(
            NAVER_LOCAL_SEARCH_URL,
            headers=headers,
            params=params,
            timeout=10.0
        )

        if response.status_code != 200:
            raise NaverAPIError(f"네이버 API 오류: {response.status_code}")

        return response.json()


def parse_place_result(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    네이버 검색 결과를 DB 저장 형식으로 변환

    Args:
        item: 네이버 API 응답의 개별 아이템

    Returns:
        변환된 장소 정보
    """
    # HTML 태그 제거 (네이버 API는 <b> 태그로 검색어 하이라이트)
    def clean_html(text: str) -> str:
        if not text:
            return ""
        return text.replace("<b>", "").replace("</b>", "")

    # 좌표 변환 (네이버 API는 KATEC 좌표계 사용)
    # mapx, mapy를 위경도로 변환 필요
    mapx = item.get("mapx", "0")
    mapy = item.get("mapy", "0")

    # KATEC -> WGS84 변환 (간단한 근사값 사용)
    try:
        longitude = float(mapx) / 10000000.0 if mapx else None
        latitude = float(mapy) / 10000000.0 if mapy else None
    except (ValueError, TypeError):
        longitude = None
        latitude = None

    return {
        "name": clean_html(item.get("title", "")),
        "category": item.get("category", ""),
        "address": item.get("address", ""),
        "road_address": item.get("roadAddress", ""),
        "phone": item.get("telephone", ""),
        "description": item.get("description", ""),
        "homepage_url": item.get("link", ""),
        "latitude": latitude,
        "longitude": longitude,
        "naver_place_id": None  # 지역검색 API는 place_id 미제공
    }


# 데이트 카테고리 정의
DATE_CATEGORIES = {
    "카페": ["카페", "디저트", "베이커리"],
    "레스토랑": ["한식", "양식", "일식", "중식", "분식"],
    "문화": ["영화관", "공연장", "전시관", "박물관"],
    "액티비티": ["방탈출", "볼링장", "당구장", "노래방"],
    "자연": ["공원", "산책로", "한강"],
    "쇼핑": ["백화점", "쇼핑몰", "아울렛"]
}


def get_search_query(location: str, category: str) -> str:
    """
    위치와 카테고리로 검색어 생성

    Args:
        location: 위치 (예: "강남", "홍대")
        category: 카테고리 키 (예: "카페", "레스토랑")

    Returns:
        검색어 문자열
    """
    return f"{location} {category}"


async def search_places_by_category(
    location: str,
    category: str,
    display: int = 5
) -> List[Dict[str, Any]]:
    """
    카테고리 기반 장소 검색

    Args:
        location: 위치 (예: "강남", "홍대")
        category: 카테고리 키
        display: 결과 개수

    Returns:
        장소 목록
    """
    query = get_search_query(location, category)
    result = await search_places(query, display=display)

    places = []
    for item in result.get("items", []):
        place = parse_place_result(item)
        place["search_category"] = category
        places.append(place)

    return places
