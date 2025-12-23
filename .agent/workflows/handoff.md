---
description: 현재 세션을 종료하고, .ai/sessions에 컨텍스트를 저장한 후 Git 동기화를 수행합니다
---
1. 현재 세션에서 수행한 작업을 분석합니다.
   - (정본 규칙) 루트 `rules.md`의 “세션 종료(Handoff)” 절차를 따릅니다.
2. `CHANGELOG.md`에 오늘 작업 내용을 한 줄 요약으로 업데이트합니다.
3. `.ai/sessions/session-YYYY-MM-DD-HH-MM.md` 경로에 새로운 세션 파일을 생성합니다.
   - 형식:
     ```markdown
     # Session Handoff: [제목]
     ## 요약 (Summary)
     [간단한 설명]
     ## 변경 사항 (Changes)
     - [파일]: [변경 내용]
     ## 다음 단계 (Next Steps)
     - [할 일 항목]
     ```
4. `git add .` 명령어를 실행합니다.
5. `git commit -m "Session Handoff: [제목]"` 명령어를 실행합니다.
6. `git push origin development` 명령어를 실행합니다.
7. 사용자에게 "세션 핸드오프 완료"라고 알립니다.
