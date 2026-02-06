pipeline {
    agent any

    environment {
        DOCKER_COMPOSE_FILE = 'docker-compose.yml'
        // docker-compose.yml의 name: my-prime-jennie와 일치
        COMPOSE_PROJECT_NAME = 'my-prime-jennie'
        // BuildKit 병렬 빌드 최적화 (9950X3D + 64GB RAM 활용)
        DOCKER_BUILDKIT = '1'
        COMPOSE_DOCKER_CLI_BUILD = '1'
    }

    options {
        disableConcurrentBuilds()
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                echo "🔀 Branch: ${env.BRANCH_NAME ?: env.GIT_BRANCH}"
                echo "📝 Commit: ${env.GIT_COMMIT}"
            }
        }

        stage('Unit Test') {
            agent {
                docker {
                    image 'python:3.12-slim'
                    args '-v $PWD:/app -w /app -v pip-cache:/root/.cache/pip'
                    reuseNode true
                }
            }
            steps {
                echo '🧪 Running Unit Tests (parallel with pytest-xdist)...'
                sh '''
                    # pip 캐시 활용
                    pip install -q -r requirements.txt

                    # [최적화] pytest-xdist로 병렬 테스트 실행 (-n auto: CPU 코어 수만큼 워커)
                    pytest tests/services/ tests/shared/ -n auto -v --tb=short --dist=loadfile
                '''
            }
            post {
                always {
                    echo 'Unit Tests Completed'
                }
            }
        }

        stage('Integration Test') {
            agent {
                docker {
                    image 'python:3.12-slim'
                    args '-v $PWD:/app -w /app -v pip-cache:/root/.cache/pip'
                    reuseNode true
                }
            }
            steps {
                echo '🔗 Running Integration Tests (parallel)...'
                sh '''
                    # 캐시된 패키지 재사용
                    pip install -q -r requirements.txt

                    # [최적화] Integration Test도 병렬화 (-n 4: 4 workers, DB 경합 방지)
                    pytest tests/integration/ -n 4 -v --tb=short --dist=loadfile --junitxml=integration-test-results.xml
                '''
            }
            post {
                always {
                    junit allowEmptyResults: true, testResults: 'integration-test-results.xml'
                }
            }
        }

        // ====================================================
        // development 브랜치에서만 실행: Smart Build & Deploy
        // 핵심: Build(변경 서비스만 이미지 빌드) → Deploy(전체 재시작)
        // ====================================================
        stage('Build & Deploy') {
            when {
                anyOf {
                    branch 'development'
                    expression { env.GIT_BRANCH?.contains('development') }
                }
            }
            agent {
                docker {
                    image 'docker:cli'
                    args '-v /var/run/docker.sock:/var/run/docker.sock -v /home/youngs75/projects/my-prime-jennie:/home/youngs75/projects/my-prime-jennie'
                    reuseNode true
                }
            }
            steps {
                echo '🚀 Smart Build & Deploy to development environment...'

                withCredentials([usernamePassword(credentialsId: 'my-prime-jennie-github', usernameVariable: 'GIT_USER', passwordVariable: 'GIT_PASS')]) {
                    sh '''
                        # Install dependencies
                        apk add --no-cache python3 git

                        # Host Path로 이동 (빌드 + 배포 동일 경로에서 실행)
                        cd /home/youngs75/projects/my-prime-jennie

                        git config --global --add safe.directory "*"

                        # 1. 최신 코드 강제 동기화 (development 브랜치)
                        git fetch https://${GIT_USER}:${GIT_PASS}@github.com/youngs7596/my-prime-jennie.git development
                        git reset --hard FETCH_HEAD
                        git clean -fd

                        # 2. 변경 범위 감지
                        # 마지막 성공 빌드 커밋 기록 파일 사용 (재시도 시에도 정확한 diff 보장)
                        echo "=========================================="
                        echo "🧠 Smart Build: 변경된 서비스 감지"
                        echo "=========================================="

                        LAST_BUILD_FILE="/home/youngs75/projects/my-prime-jennie/.last_successful_build"
                        CURRENT_HEAD=$(git rev-parse HEAD)

                        if [ -f "$LAST_BUILD_FILE" ]; then
                            LAST_BUILD=$(cat "$LAST_BUILD_FILE")
                            if [ "$LAST_BUILD" = "$CURRENT_HEAD" ]; then
                                echo "ℹ️ HEAD == last successful build. No new commits."
                                TARGET_RANGE=""
                            elif git merge-base --is-ancestor "$LAST_BUILD" HEAD 2>/dev/null; then
                                TARGET_RANGE="${LAST_BUILD}..HEAD"
                            else
                                echo "⚠️ Last build commit not in history. Triggering FULL BUILD."
                                TARGET_RANGE=""
                                FORCE_FULL_BUILD=true
                            fi
                        else
                            echo "🚨 No last build record. Triggering FULL BUILD (bootstrap)."
                            TARGET_RANGE=""
                            FORCE_FULL_BUILD=true
                        fi

                        # 3. Build: 변경된 서비스만 이미지 빌드 (또는 전체 빌드)
                        echo "=========================================="
                        echo "🏗️ Step 1: 서비스 이미지 빌드"
                        echo "=========================================="
                        docker builder prune -f --filter "until=24h" || true

                        if [ "${FORCE_FULL_BUILD:-false}" = "true" ]; then
                            echo "🏗️ FULL BUILD triggered."
                            python3 scripts/smart_build.py --action build --services ALL
                        elif [ -n "$TARGET_RANGE" ]; then
                            echo "📏 Commit range: $TARGET_RANGE"
                            python3 scripts/smart_build.py --action build --commit-range "$TARGET_RANGE"
                        else
                            echo "✨ No new commits to build."
                        fi

                        # 4. Deploy: 전체 서비스 재시작 (이미지 빌드 완료 상태)
                        echo "=========================================="
                        echo "🚀 Step 2: 전체 서비스 재시작"
                        echo "=========================================="
                        python3 scripts/smart_build.py --action deploy --services ALL

                        # 5. 성공 시 현재 커밋 기록 (다음 빌드에서 정확한 diff 범위 사용)
                        echo "$CURRENT_HEAD" > "$LAST_BUILD_FILE"
                        echo "✅ Last successful build recorded: $CURRENT_HEAD"

                        echo ""
                        echo "=========================================="
                        echo "📊 배포 완료 - 서비스 상태"
                        echo "=========================================="
                        docker compose -p ${COMPOSE_PROJECT_NAME} -f ${DOCKER_COMPOSE_FILE} --profile real ps
                    '''
                }
            }
        }
    }

    post {
        always {
            echo '📋 Pipeline finished!'
        }
        success {
            script {
                def branchName = env.BRANCH_NAME ?: env.GIT_BRANCH ?: ''
                if (branchName.contains('main')) {
                    echo '✅ Build & Deploy succeeded!'
                } else {
                    echo '✅ Unit Tests passed!'
                }
            }
        }
        failure {
            echo '❌ Pipeline failed!'
        }
    }
}
