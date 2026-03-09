# Gmail Calendar Event Service

A production-ready web service that automatically reads Gmail, detects event-related emails, and creates corresponding events in Google Calendar using AI-powered extraction.

## Features

- **Secure OAuth2 Authentication** - Google login with minimal scopes (Gmail read-only, Calendar events)
- **Multi-User Support** - Each user has their own encrypted tokens and preferences
- **AI-Powered Event Extraction** - Uses LLM (OpenAI/Anthropic) to extract structured event data
- **Heuristic Pre-Filtering** - Fast filtering before LLM processing for efficiency
- **Flexible Configuration** - Auto-add events or require manual approval
- **Sender/Label Filters** - Include or exclude emails from specific sources
- **Real-time Notifications** - Gmail Pub/Sub support for instant processing (optional)
- **Audit Logging** - Track all user actions for compliance

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Google Cloud Project with APIs enabled
- OpenAI or Anthropic API key

### Installation

```bash
# Clone and setup
cd gmail-calendar-service
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your credentials

# Run migrations
alembic upgrade head

# Start server
uvicorn app.main:app --reload
```

### Configuration

Key environment variables (see `.env.example` for full list):

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `GOOGLE_REDIRECT_URI` | OAuth callback URL |
| `LLM_API_KEY` | OpenAI/Anthropic API key |
| `LLM_PROVIDER` | "openai" or "anthropic" |

See [SETUP_GUIDE.md](docs/SETUP_GUIDE.md) for detailed setup instructions.

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Gmail     │────▶│   Service   │────▶│  Calendar   │
│   (emails)  │     │  (extract)  │     │  (events)   │
└─────────────┘     └─────────────┘     └─────────────┘
                          │
                    ┌─────┴─────┐
                    │    LLM    │
                    │ (extract) │
                    └───────────┘
```

See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed system design.

## API Endpoints

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/auth/google` | Initiate Google OAuth |
| GET | `/auth/callback` | OAuth callback |
| POST | `/auth/logout` | Logout user |
| GET | `/auth/me` | Get current user |
| GET | `/auth/status` | Check auth status |

### Events

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/events` | List events (paginated) |
| GET | `/api/events/{id}` | Get event details |
| POST | `/api/events/{id}/accept` | Accept proposed event |
| POST | `/api/events/{id}/reject` | Reject event |
| PUT | `/api/events/{id}` | Update event |
| DELETE | `/api/events/{id}` | Delete event |

### Settings

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/settings` | Get user settings |
| PUT | `/api/settings` | Update settings |
| GET | `/api/settings/filters` | List filters |
| POST | `/api/settings/filters` | Create filter |
| DELETE | `/api/settings/filters/{id}` | Delete filter |

### Webhooks

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/webhook/gmail` | Gmail Pub/Sub notifications |
| POST | `/api/emails/process` | Manual email processing trigger |

## Event Extraction

The service uses a two-stage extraction process:

1. **Heuristic Filter** - Fast keyword and pattern matching to identify potential events
2. **LLM Extraction** - Structured extraction using AI for detailed event data

### LLM Prompt Template

```
Analyze the following email and extract event information.

EMAIL DETAILS:
Subject: {subject}
Sender: {sender}
Date: {date}

EMAIL BODY:
{body}

Extract as JSON:
- title: Event title
- description: Brief description
- start_datetime: ISO 8601 format
- end_datetime: ISO 8601 format (or null)
- timezone: Timezone (default UTC)
- location: Location or meeting link
- importance_score: 0-1
- confidence_score: 0-1
```

### Confidence Scoring

- Events with confidence ≥ 0.8 can be auto-added (configurable)
- Events with confidence < 0.5 are rejected
- Scores combine heuristic and LLM confidence

## Database Schema

Key tables:

- `users` - User accounts
- `oauth_tokens` - Encrypted Google tokens
- `user_settings` - User preferences
- `filters` - Sender/label filters
- `events` - Proposed and created events
- `processed_messages` - Deduplication
- `audit_logs` - Action history

See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for complete schema.

## Security

- **Token Encryption**: OAuth tokens encrypted with AES-256-GCM
- **Minimal Scopes**: Only `gmail.readonly` and `calendar.events`
- **JWT Authentication**: Short-lived access tokens with refresh
- **CSRF Protection**: State tokens in OAuth flow
- **Input Validation**: All inputs validated via Pydantic
- **Audit Logging**: All sensitive actions logged

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific tests
pytest tests/test_extraction.py -v
pytest tests/test_api.py -v
```

## Development

### Project Structure

```
gmail-calendar-service/
├── app/
│   ├── api/           # API route handlers
│   ├── auth/          # Authentication logic
│   ├── calendar/      # Google Calendar integration
│   ├── core/          # Configuration, database, security
│   ├── events/        # Event extraction logic
│   ├── gmail/         # Gmail API integration
│   ├── models/        # Database models and schemas
│   └── main.py        # FastAPI application
├── docs/              # Documentation
├── migrations/        # Database migrations
├── tests/             # Test suite
├── .env.example       # Environment template
├── requirements.txt   # Python dependencies
└── README.md          # This file
```

### Adding New LLM Provider

1. Create a class implementing `LLMProvider` interface:

```python
from app.events.llm_provider import LLMProvider

class MyLLMProvider(LLMProvider):
    async def generate(self, prompt: str, system_prompt: str = None) -> str:
        # Your implementation
        pass

    async def generate_json(self, prompt: str, system_prompt: str = None) -> dict:
        # Your implementation
        pass
```

2. Register in `get_llm_provider()` factory function.

### Adding New Extraction Rules

1. Add keywords to `HeuristicFilter.EVENT_KEYWORDS`
2. Add patterns to `HeuristicFilter.DATETIME_PATTERNS`
3. Create custom extraction logic in a new class

## Production Deployment

### Docker

```bash
docker build -t gmail-calendar-service .
docker run -p 8000:8000 --env-file .env gmail-calendar-service
```

### Docker Compose

```bash
docker-compose up -d
```

### Production Checklist

- [ ] Set `DEBUG=false`
- [ ] Change all secret keys
- [ ] Use managed PostgreSQL
- [ ] Configure Pub/Sub for real-time notifications
- [ ] Set up monitoring and alerting
- [ ] Configure proper CORS origins
- [ ] Use HTTPS

## License

MIT License - See LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests: `pytest`
5. Submit a pull request

## Support

For issues and questions, please open a GitHub issue.
