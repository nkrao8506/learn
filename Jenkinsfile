pipeline {
    agent any

    stages {
        stage('Checkout') {
            steps {
                git branch: 'main', url: 'https://github.com/nkrao8506/learn.git'
            }
        }

        stage('Install Dependencies') {
            steps {
                echo 'Installing dependencies...'
                // Windows command for pip install
                bat 'pip install -r requirements.txt || exit 0'
            }
        }

        stage('Run Tests') {
            steps {
                echo 'Running unit tests...'
                // Windows command to run python tests
                bat 'python -m unittest discover tests'
            }
        }
    }

    post {
        success {
            echo 'Build and tests succeeded!'
        }
        failure {
            echo 'Build or tests failed!'
        }
    }
}
