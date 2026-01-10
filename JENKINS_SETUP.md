# Jenkins CI/CD Setup Guide (Step-by-Step)

## 1. Jenkins 접속 및 로그인
1.  **URL**: [http://localhost:8180](http://localhost:8180)
2.  **로그인**:
    *   **ID**: `youngs75`
    *   **PW**: `admin1234` (또는 변경한 비밀번호)

## 2. GitHub Credentials 등록 (가장 중요!)
`Jenkinsfile`이 `my-prime-jennie-github`라는 ID의 Credential을 찾으므로, **ID를 정확히 입력**해야 합니다.

1.  메인 대시보드에서 **Manage Jenkins** 클릭.
2.  **Credentials** 클릭 -> **System** 클릭 -> **Global credentials (unrestricted)** 클릭.
3.  우측 상단의 **+ Add Credentials** 버튼 클릭.
4.  다음과 같이 입력:
    *   **Kind**: `Username with password` 선택
    *   **Scope**: `Global (Jenkins, nodes, items, ...)` (기본값)
    *   **Username**: 본인의 GitHub 아이디 (예: `youngs7596`)
    *   **Password**: 발급받은 **GitHub PAT (Personal Access Token)** 붙여넣기
    *   **ID**: `my-prime-jennie-github` (**🚨 오타 주의 🚨**)
    *   **Description**: `GitHub Credentials` (자유 입력)
5.  **Create** 버튼 클릭.

## 3. Pipeline Job 생성
1.  메인 대시보드 좌측의 **+ New Item** 클릭.
2.  **Job 이름** 입력: `my-prime-jennie-pipeline` (원하는 이름)
3.  **Pipeline** 선택 후 하단의 **OK** 클릭.

## 4. Pipeline 설정
1.  스크롤을 내려 **Pipeline** 섹션으로 이동.
2.  **Definition**: `Pipeline script from SCM` 선택.
3.  **SCM**: `Git` 선택.
4.  **Repositories**:
    *   **Repository URL**: `https://github.com/youngs7596/my-prime-jennie.git`
    *   **Credentials**: 방금 만든 `my-prime-jennie-github` 선택. (에러 메시지가 사라져야 함)
5.  **Branches to build**:
    *   **Branch Specifier**: `*/development` (⚠️ `main` 대신 `development` 입력)
6.  **Script Path**: `Jenkinsfile` (기본값 유지)
7.  하단의 **Save** 클릭.

## 5. 파이프라인 실행 (Build)
1.  생성된 Job 화면 좌측의 **Build Now** 클릭.
2.  하단 **Build History**에 `#1`이 생기며 실행됨.
3.  `#1`을 클릭하고 **Console Output**을 확인하여 진행 상황 모니터링.
    *   `Checkout` -> `Unit Test` -> `Integration Test` -> `Docker Build` -> `Deploy` 순서로 진행됩니다.
