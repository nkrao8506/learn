# Setup Guide

This guide will walk you through setting up the Gmail Calendar Event Service from scratch.

## Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Google Cloud Project with Gmail and Calendar APIs enabled
- LLM API key (OpenAI or Anthropic) for event extraction

## Step 1: Google Cloud Project Setup

### 1.1 Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click "Select a project" → "New Project"
3. Name your project (e.g., "gmail-calendar-service")
4. Click "Create"

### 1.2 Enable Required APIs

1. In your project, go to "APIs & Services" → "Library"
2. Search for and enable the following APIs:
   - **Gmail API** - For reading emails
   - **Google Calendar API** - For creating events
   - **People API** (optional) - For user profile info

### 1.3 Configure OAuth Consent Screen

1. Go to "APIs & Services" → "OAuth consent screen"
2. Choose "External" user type (unless you have a Google Workspace account)
3. Fill in the required fields:
   - App name: "Gmail Calendar Event Service"
   - User support email: your email
   - Developer contact: your email
4. Add scopes:
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/calendar.events`
   - `https://www.googleapis.com/auth/userinfo.email`
   - `https://www.googleapis.com/auth/userinfo.profile`
5. Add test users (your email)
6. Click "Save and Continue"

### 1.4 Create OAuth 2.0 Credentials

1. Go to "APIs & Services" → "Credentials"
2. Click "Create Credentials" → "OAuth client ID"
3. Application type: "Web application"
4. Name: "Gmail Calendar Service"
5. Add authorized redirect URIs:
   - Development: `http://localhost:8000/auth/callback`
   - Production: `https://your-domain.com/auth/callback`
6. Click "Create"
7. **Save the Client ID and Client Secret** - you'll need these

### 1.5 Configure Pub/Sub (Optional, for Production)

For real-time email notifications:

1. Go to "Pub/Sub" in Google Cloud Console
2. Create a topic named "gmail-notifications"
3. Create a subscription (push or pull)
4. Grant `gmail-api-push@system.gserviceaccount.com` publish permissions on the topic
5. Note the full topic name: `projects/your-project-id/topics/gmail-notifications`

## Step 2: Database Setup

### 2.1 Install PostgreSQL

```bash
# macOS (Homebrew)
brew install postgresql@14
brew services start postgresql@14

# Ubuntu/Debian
sudo apt-get install postgresql-14
sudo systemctl start postgresql

# Docker
docker run --name postgres -e POSTGRES_PASSWORD=postgres -p 5432:5432 -d postgres:14
```

### 2.2 Create Database

```bash
# Connect to PostgreSQL
psql -U postgres

# Create database
CREATE DATABASE gmail_calendar;

# Create user (optional)
CREATE USER gmail_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE gmail_calendar TO gmail_user;

# Exit
\q
```

## Step 3: Application Setup

### 3.1 Clone and Install Dependencies

```bash
# Navigate to project directory
cd gmail-calendar-service

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3.2 Configure Environment Variables

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your values
nano .env
```

Required environment variables:

```bash
# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmail_calendar

# Google OAuth (from Step 1.4)
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback

# Encryption keys (generate new ones)
SECRET_KEY=openssl rand -hex 32
ENCRYPTION_KEY=openssl rand -base64 32
JWT_SECRET_KEY=openssl rand -hex 32

# LLM API
LLM_PROVIDER=openai
LLM_API_KEY=your-openai-api-key
LLM_MODEL=gpt-4
```

Generate secure keys:

```bash
# Secret key
openssl rand -hex 32

# Encryption key
openssl rand -base64 32
```

### 3.3 Run Database Migrations

```bash
# Initialize Alembic (if not done)
alembic upgrade head
```

Or, let the app create tables on startup (development only):

```bash
# Tables will be created automatically when you start the server
```

## Step 4: Run the Application

### 4.1 Development Server

```bash
# Start the server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4.2 Verify Installation

1. Open your browser and go to `http://localhost:8000/health`
2. You should see: `{"status": "healthy", "version": "1.0.0", ...}`

### 4.3 Test Authentication

1. Go to `http://localhost:8000/api/docs`
2. Click "Authorize" and enter your credentials
3. Or visit `http://localhost:8000/auth/google` to start OAuth flow

## Step 5: Testing the Service

### 5.1 Run Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test file
pytest tests/test_extraction.py -v
```

### 5.2 Manual Testing

1. **Login**: Visit `http://localhost:8000/auth/google`
2. **Grant permissions**: Accept the OAuth consent screen
3. **Get events**: Use the API to list proposed events
4. **Accept/Reject events**: Manage your events

## Step 6: Production Deployment

### 6.1 Environment Variables

Update your `.env` for production:

```bash
DEBUG=false
ENVIRONMENT=production
GOOGLE_REDIRECT_URI=https://your-domain.com/auth/callback
CORS_ORIGINS=["https://your-domain.com"]
```

### 6.2 Database

Use a managed PostgreSQL service (AWS RDS, Google Cloud SQL, etc.)

### 6.3 Security Checklist

- [ ] Change all secret keys
- [ ] Use HTTPS
- [ ] Set up proper CORS
- [ ] Configure rate limiting
- [ ] Set up logging and monitoring
- [ ] Use a production WSGI server (gunicorn + uvicorn workers)
- [ ] Set up Pub/Sub for real-time notifications

### 6.4 Docker Deployment (Optional)

Create a `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Build and run:

```bash
docker build -t gmail-calendar-service .
docker run -p 8000:8000 --env-file .env gmail-calendar-service
```

### 6.5 Docker Compose (Full Stack)

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  db:
    image: postgres:14
    environment:
      POSTGRES_DB: gmail_calendar
      POSTGRES_PASSWORD: postgres
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql+asyncpg://postgres:postgres@db:5432/gmail_calendar
    depends_on:
      - db
    env_file:
      - .env

volumes:
  postgres_data:
```

Run:

```bash
docker-compose up -d
```

## Troubleshooting

### Common Issues

1. **OAuth Error: redirect_uri_mismatch**
   - Ensure `GOOGLE_REDIRECT_URI` matches exactly what's configured in Google Cloud Console

2. **Database connection error**
   - Verify PostgreSQL is running
   - Check `DATABASE_URL` format
   - Ensure database exists

3. **Token encryption error**
   - Make sure `ENCRYPTION_KEY` is set
   - If you change the key, old tokens won't decrypt

4. **LLM API errors**
   - Verify your API key is valid
   - Check API quotas and limits

### Logs

Check application logs:

```bash
# If running with uvicorn
# Logs appear in terminal

# If running with systemd
journalctl -u gmail-calendar-service -f
```

### Reset Database

```bash
# Drop and recreate database
psql -U postgres -c "DROP DATABASE gmail_calendar;"
psql -U postgres -c "CREATE DATABASE gmail_calendar;"

# Run migrations
alembic downgrade base
alembic upgrade head
```

## Next Steps

- Set up a frontend application
- Configure Pub/Sub for real-time notifications
- Add more event extraction rules
- Customize LLM prompts for better extraction
- Set up monitoring and alerting

## Support

For issues and feature requests, please open a GitHub issue.
