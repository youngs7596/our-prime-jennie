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
                echo '🧪 Running Unit Tests...'
                sh '''
                    # Force fresh install to avoid cache issues
                    pip install --no-cache-dir -r requirements.txt
                    
                    # Verify key library versions for debugging
                    python -c "import numpy; print(f'NumPy version: {numpy.__version__}')"
                    python -c "import pandas; print(f'Pandas version: {pandas.__version__}')"
                    python -c "import flask_limiter; print(f'Flask-Limiter version: {flask_limiter.__version__}')"
                    
                    # Run pytest for services tests (pytest fixtures are required)
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
                echo '🔗 Running Integration Tests...'
                sh '''
                    pip install -r requirements.txt
                    # pytest is included in requirements.txt
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
                    
                    # 캐시 활용 + 최신 베이스 이미지 풀 (--no-cache 제거로 빌드 속도 향상)
                    # 병렬 빌드 무제한 (COMPOSE_PARALLEL_LIMIT 제거)
                    docker compose -p ${COMPOSE_PROJECT_NAME} -f ${DOCKER_COMPOSE_FILE} build --pull --parallel
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
                echo '🚀 Deploying to development environment...'

                withCredentials([usernamePassword(credentialsId: 'my-prime-jennie-github', usernameVariable: 'GIT_USER', passwordVariable: 'GIT_PASS')]) {
                    sh '''
                        git config --global --add safe.directory "*" 
                        
                        cd /home/youngs75/projects/my-prime-jennie

                        # 1. 최신 코드 강제 동기화 (development 브랜치)
                        git fetch https://${GIT_USER}:${GIT_PASS}@github.com/youngs7596/my-prime-jennie.git development
                        git reset --hard FETCH_HEAD
                        git clean -fd
                        
                        # 2. --profile real 추가해서 기존 real 컨테이너 내리기
                        docker compose -p ${COMPOSE_PROJECT_NAME} -f ${DOCKER_COMPOSE_FILE} --profile real down --remove-orphans --timeout 30 || true
                        
                        # 3. --profile real 추가 + 강제 빌드 + 강제 재생성
                        docker compose -p ${COMPOSE_PROJECT_NAME} -f ${DOCKER_COMPOSE_FILE} --profile real up -d --build --force-recreate
                        
                        # 4. 상태 확인
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
