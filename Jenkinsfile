pipeline {
    agent any

    stages {
        stage('Checkout') {
            steps {
                // Checkout your repo
                git branch: 'main', url: 'https://github.com/nkrao8506/learn.git'
            }
        }

        stage('Install Dependencies') {
            steps {
                echo 'Installing dependencies...'
                // If you have dependencies, install them here (example)
                sh 'pip install -r requirements.txt || true'
            }
        }

        stage('Run Tests') {
            steps {
                echo 'Running unit tests...'
                // Run your python tests (assuming unittest in tests/ folder)
                sh 'python3 -m unittest discover tests'
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
