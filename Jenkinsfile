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
                echo '🐳 Building Docker images (Smart Build)...'
                sh '''
                    # [Fix] 손상된 캐시만 정리 (24시간 이상 된 것)
                    docker builder prune -f --filter "until=24h" || true
                    
                    # Smart Build Script Execution
                    # 변경된 서비스만 감지하여 빌드 (HEAD~1..HEAD)
                    python3 scripts/smart_build.py --action build --commit-range HEAD~1..HEAD
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
                        
                        # 2. Smart Build & Deploy
                        # ORIG_HEAD..HEAD: git reset --hard 이전과 현재의 차이 감지
                        echo "=========================================="
                        echo "🧠 Smart Build: 변경된 서비스 감지 및 배포"
                        echo "=========================================="
                        
                        python3 scripts/smart_build.py --action deploy --commit-range ORIG_HEAD..HEAD
                        
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
