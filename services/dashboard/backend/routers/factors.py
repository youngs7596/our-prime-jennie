from fastapi import APIRouter
from typing import List, Dict, Any
from pydantic import BaseModel

from shared.config import ConfigManager

router = APIRouter(
    prefix="/api/settings", # Changed to /api/settings to match frontend routing
    tags=["factors"],
    responses={404: {"description": "Not found"}},
)

class FactorSchema(BaseModel):
    key: str
    value: Any
    desc: str
    category: str

@router.get("/factors", response_model=List[FactorSchema])
async def get_factors():
    """
    트레이딩 팩터 목록 조회
    
    config.py의 _defaults에 정의된 설명(desc)과 카테고리(category)를 포함하여 반환합니다.
    """
    config = ConfigManager()
    
    # 1. 기본값 정보 가져오기 (설명 및 카테고리가 여기에 있음)
    defaults = config._defaults
    
    factors = []
    for key, info in defaults.items():
        # Dictionary 구조가 아니면 건너뜀 (레거시 지원)
        if not isinstance(info, dict):
            continue
            
        # 2. 현재 활성화된 값 가져오기 (DB/환경변수 오버라이드 포함)
        current_value = config.get(key)
        
        factors.append(FactorSchema(
            key=key,
            value=current_value,
            desc=info.get("desc", ""),
            category=info.get("category", "General")
        ))
    
    # 카테고리별 정렬
    factors.sort(key=lambda x: (x.category, x.key))
    
    return factors
