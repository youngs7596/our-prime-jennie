pipeline {
    agent any

    environment {
        DOCKER_COMPOSE_FILE = 'docker-compose.yml'
        // docker-compose.yml의 name: my-prime-jennie와 일치
        COMPOSE_PROJECT_NAME = 'my-prime-jennie'
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
                    image 'python:3.11-slim'
                    args '-v $PWD:/app -w /app'
                    reuseNode true
                }
            }
            steps {
                echo '🧪 Running Unit Tests...'
                sh '''
                    pip install --quiet -r requirements.txt
                    pip install --quiet pytest pytest-cov
                    pytest tests/ -v --tb=short --junitxml=test-results.xml || true
                '''
            }
            post {
                always {
                    junit allowEmptyResults: true, testResults: 'test-results.xml'
                }
            }
        }

        stage('Integration Test') {
            agent {
                docker {
                    image 'python:3.11-slim'
                    args '-v $PWD:/app -w /app'
                    reuseNode true
                }
            }
            steps {
                echo '🔗 Running Integration Tests...'
                sh '''
                    pip install --quiet -r requirements.txt
                    pip install --quiet pytest pytest-cov
                    pytest tests/integration/ -v --tb=short --junitxml=integration-test-results.xml || true
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
                echo '🐳 Building Docker images...'
                sh '''
                    docker compose -p ${COMPOSE_PROJECT_NAME} -f ${DOCKER_COMPOSE_FILE} build --no-cache
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
