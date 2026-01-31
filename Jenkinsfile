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
                        echo "🔧 Phase 1: 모든 이미지 병렬 빌드"
                        echo "=========================================="

                        # [최적화] 모든 이미지를 먼저 병렬로 빌드 (배포 전)
                        docker compose -p ${COMPOSE_PROJECT_NAME} -f ${DOCKER_COMPOSE_FILE} --profile real build --parallel

                        echo ""
                        echo "=========================================="
                        echo "🔄 Phase 2: Rolling Deployment (무중단 배포)"
                        echo "=========================================="

                        # 핵심 트레이딩 서비스 순서 (의존성 고려)
                        TRADING_SERVICES="kis-gateway buy-scanner buy-executor sell-executor price-monitor"

                        # Rolling Deploy: 서비스별 순차 재시작 (빌드 없이 이미지만 교체)
                        for SERVICE in $TRADING_SERVICES; do
                            echo ""
                            echo "🔄 [$SERVICE] 배포 시작..."

                            # 이미 빌드된 이미지로 서비스 재시작 (--no-build: 빌드 스킵)
                            docker compose -p ${COMPOSE_PROJECT_NAME} -f ${DOCKER_COMPOSE_FILE} --profile real up -d --no-build --no-deps $SERVICE

                            # Health check 대기 (최대 40초, 2초 간격)
                            CONTAINER_NAME="${COMPOSE_PROJECT_NAME}-${SERVICE}-1"
                            echo "   ⏳ Health check 대기 중..."

                            for i in $(seq 1 20); do
                                HEALTH=$(docker inspect --format='{{.State.Health.Status}}' $CONTAINER_NAME 2>/dev/null || echo "unknown")

                                if [ "$HEALTH" = "healthy" ]; then
                                    echo "   ✅ [$SERVICE] healthy (${i}회차)"
                                    break
                                elif [ "$HEALTH" = "unhealthy" ]; then
                                    echo "   ❌ [$SERVICE] unhealthy!"
                                    docker logs --tail 10 $CONTAINER_NAME
                                    break
                                fi

                                [ $i -eq 20 ] && echo "   ⚠️ [$SERVICE] 타임아웃"
                                sleep 2
                            done

                            # [최적화] 안정화 대기 5초 → 2초
                            sleep 2
                            echo "   ✅ [$SERVICE] 배포 완료"
                        done

                        echo ""
                        echo "=========================================="
                        echo "🎯 Phase 3: 기타 서비스 일괄 배포"
                        echo "=========================================="

                        # 비핵심 서비스 일괄 업데이트 (이미 빌드됨, --no-build)
                        docker compose -p ${COMPOSE_PROJECT_NAME} -f ${DOCKER_COMPOSE_FILE} --profile real up -d --no-build

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
