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
                echo '🧪 Running Unit Tests (with pip cache)...'
                sh '''
                    # pip 캐시 활용 (--no-cache-dir 제거 → 빌드 속도 향상)
                    pip install -q -r requirements.txt
                    
                    # Run pytest for services tests
                    pytest tests/services/ tests/shared/ -v --tb=short
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
                echo '🔗 Running Integration Tests (reusing cached packages)...'
                sh '''
                    # 캐시된 패키지 재사용 (-q: quiet mode)
                    pip install -q -r requirements.txt
                    pytest tests/integration/ -v --tb=short --junitxml=integration-test-results.xml
                '''
            }
            post {
                always {
                    junit allowEmptyResults: true, testResults: 'integration-test-results.xml'
                }
            }
        }

        // ====================================================
        // development 브랜치에서만 실행: Docker Build & Deploy
        // ====================================================
        stage('Docker Build') {
            when {
                anyOf {
                    branch 'development'
                    expression { env.GIT_BRANCH?.contains('development') }
                }
            }
            steps {
                echo '🐳 Building Docker images (Cache Optimized + Parallel)...'
                sh '''
                    # [Fix] 손상된 캐시만 정리 (24시간 이상 된 것)
                    docker builder prune -f --filter "until=24h" || true
                    
                    # 캐시 활용 (기존 이미지/레이어 적극 재사용)
                    # 병렬 빌드 무제한 (COMPOSE_PARALLEL_LIMIT 제거)
                    docker compose -p ${COMPOSE_PROJECT_NAME} -f ${DOCKER_COMPOSE_FILE} build --parallel
                '''
            }
        }

        stage('Deploy') {
            when {
                anyOf {
                    branch 'development'
                    expression { env.GIT_BRANCH?.contains('development') }
                }
            }
            steps {
                echo '🚀 Rolling Deploy to development environment...'

                withCredentials([usernamePassword(credentialsId: 'my-prime-jennie-github', usernameVariable: 'GIT_USER', passwordVariable: 'GIT_PASS')]) {
                    sh '''
                        git config --global --add safe.directory "*"

                        cd /home/youngs75/projects/my-prime-jennie

                        # 1. 최신 코드 강제 동기화 (development 브랜치)
                        git fetch https://${GIT_USER}:${GIT_PASS}@github.com/youngs7596/my-prime-jennie.git development
                        git reset --hard FETCH_HEAD
                        git clean -fd

                        echo "=========================================="
                        echo "🔄 Rolling Deployment 시작 (무중단 배포)"
                        echo "=========================================="

                        # 핵심 트레이딩 서비스 순서 (의존성 고려)
                        # kis-gateway → buy-scanner → buy-executor → sell-executor → price-monitor
                        TRADING_SERVICES="kis-gateway buy-scanner buy-executor sell-executor price-monitor"

                        # 2. Rolling Deploy: 서비스별 순차 재시작
                        for SERVICE in $TRADING_SERVICES; do
                            echo ""
                            echo "🔄 [$SERVICE] 배포 시작..."

                            # 2-1. 새 이미지로 서비스 재시작 (--no-deps: 의존 서비스 재시작 방지)
                            docker compose -p ${COMPOSE_PROJECT_NAME} -f ${DOCKER_COMPOSE_FILE} --profile real up -d --build --no-deps $SERVICE

                            # 2-2. Health check 대기 (최대 60초)
                            CONTAINER_NAME="${COMPOSE_PROJECT_NAME}-${SERVICE}-1"
                            echo "   ⏳ Health check 대기 중: $CONTAINER_NAME"

                            for i in $(seq 1 30); do
                                # 컨테이너 상태 확인
                                HEALTH=$(docker inspect --format='{{.State.Health.Status}}' $CONTAINER_NAME 2>/dev/null || echo "unknown")

                                if [ "$HEALTH" = "healthy" ]; then
                                    echo "   ✅ [$SERVICE] healthy (${i}회차 체크)"
                                    break
                                elif [ "$HEALTH" = "unhealthy" ]; then
                                    echo "   ❌ [$SERVICE] unhealthy! 로그 확인 필요"
                                    docker logs --tail 20 $CONTAINER_NAME
                                    break
                                fi

                                if [ $i -eq 30 ]; then
                                    echo "   ⚠️ [$SERVICE] Health check 타임아웃 (계속 진행)"
                                fi

                                sleep 2
                            done

                            # 2-3. 안정화 대기 (5초)
                            echo "   💤 안정화 대기 (5초)..."
                            sleep 5

                            echo "   ✅ [$SERVICE] 배포 완료"
                        done

                        echo ""
                        echo "=========================================="
                        echo "🎯 기타 서비스 일괄 업데이트"
                        echo "=========================================="

                        # 3. 비핵심 서비스 일괄 업데이트 (scout-job, daily-briefing 등)
                        docker compose -p ${COMPOSE_PROJECT_NAME} -f ${DOCKER_COMPOSE_FILE} --profile real up -d --build

                        # 4. 최종 상태 확인
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
