# Config Registry 가이드 (env > DB > default)

## 우선순위
1. **메모리 캐시**: 런타임 set() 값  
2. **환경변수(env)**: 배포/런타임 오버라이드 (최우선)  
3. **DB CONFIG**: 운영 튜닝용 (대시보드/PUT API로 저장)  
4. **레지스트리 기본값**: `shared/settings/registry.py`에 선언된 value/type/desc  

## env로 잠그는 키(예시)
- 인증/비밀번호/토큰류: `DASHBOARD_USERNAME`, `DASHBOARD_PASSWORD`, `JWT_SECRET` 등  
- 외부 API 키: OpenAI/Anthropic/Gemini/KIS 등 모든 secret 키  
- 인프라 주소/포트: DB 호스트/포트, Redis, Gateway URL 등  
→ 이런 키는 env에서만 설정하고, 대시보드 편집은 차단(읽기 전용)합니다.

## DB 저장/편집
- API: `GET /api/config`, `PUT /api/config/{key}`  
- 프런트: Settings 화면에서 조회/편집(단, env 우선 키는 “env 고정”으로 노출)

## 레지스트리 위치
- 파일: `shared/settings/registry.py`  
- 필드: `value`, `type`, `desc`, `category` (필요 시 min/max/sensitive 확장 가능)

## 덤프/점검
- `scripts/dump_config.py` 실행 시 현재값과 소스(env/db/default)를 한눈에 확인


