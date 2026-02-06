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
        // development 브랜치: BuildKit 캐시 기반 빌드 & 배포
        // BuildKit이 레이어 캐시로 변경 없는 서비스는 즉시 스킵
        // 변경된 이미지의 컨테이너만 자동 재생성
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
                echo '🚀 Build & Deploy to development environment...'

                withCredentials([usernamePassword(credentialsId: 'my-prime-jennie-github', usernameVariable: 'GIT_USER', passwordVariable: 'GIT_PASS')]) {
                    sh '''
                        apk add --no-cache git

                        cd /home/youngs75/projects/my-prime-jennie
                        git config --global --add safe.directory "*"

                        # 1. 최신 코드 동기화
                        git fetch https://${GIT_USER}:${GIT_PASS}@github.com/youngs7596/my-prime-jennie.git development
                        git reset --hard FETCH_HEAD
                        git clean -fd

                        echo "=========================================="
                        echo "📝 Deploying: $(git log --oneline -1)"
                        echo "=========================================="

                        # 2. 오래된 빌드 캐시 정리
                        docker builder prune -f --filter "until=24h" || true

                        # 3. 빌드 & 배포 (BuildKit 캐시가 알아서 처리)
                        #    - 변경 없는 서비스: 레이어 캐시 히트 → 이미지 동일 → 컨테이너 유지
                        #    - 변경된 서비스: 해당 레이어만 재빌드 → 컨테이너 재생성
                        docker compose -p ${COMPOSE_PROJECT_NAME} \
                            -f ${DOCKER_COMPOSE_FILE} \
                            --profile real \
                            up -d --build

                        # 4. 미사용 이미지 정리
                        docker image prune -f || true

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
