# Gmail to Google Calendar Event Detection Service

## High-Level Architecture

### Overview

This service automatically detects event-related emails in a user's Gmail inbox and creates corresponding events in their Google Calendar. The system is designed for multi-user support from day one, with secure OAuth2 token management and a pluggable event extraction pipeline.

### System Components

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CLIENT LAYER                                    │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────────────┐  │
│  │   Web Frontend  │    │   Mobile App    │    │   Third-party Clients   │  │
│  └────────┬────────┘    └────────┬────────┘    └───────────┬─────────────┘  │
└───────────┼──────────────────────┼─────────────────────────┼────────────────┘
            │                      │                         │
            └──────────────────────┼─────────────────────────┘
                                   │ HTTP/REST
┌──────────────────────────────────┼──────────────────────────────────────────┐
│                           API GATEWAY LAYER                                  │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                        FastAPI Application                            │   │
│  │  • Request validation (Pydantic)                                     │   │
│  │  • Authentication middleware                                         │   │
│  │  • Rate limiting & CORS                                              │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                   │
┌──────────────────────────────────┼──────────────────────────────────────────┐
│                           SERVICE LAYER                                      │
│                                                                              │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐  ┌──────────────┐  │
│  │  Auth Service │  │ Gmail Service │  │Event Extractor│  │Calendar Svc  │  │
│  │               │  │               │  │               │  │              │  │
│  │ • OAuth flow  │  │ • Watch/Poll  │  │ • Heuristics  │  │ • Create     │  │
│  │ • Token mgmt  │  │ • Fetch msgs  │  │ • LLM calls   │  │ • Update     │  │
│  │ • Session     │  │ • Mark read   │  │ • Validation  │  │ • Delete     │  │
│  └───────┬───────┘  └───────┬───────┘  └───────┬───────┘  └──────┬───────┘  │
│          │                  │                  │                 │          │
│  ┌───────┴──────────────────┴──────────────────┴─────────────────┴───────┐  │
│  │                        Event Processing Pipeline                       │  │
│  │  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐             │  │
│  │  │  Gmail  │───▶│ Extract │───▶│Validate │───▶│ Calendar│             │  │
│  │  │  Poll   │    │  Event  │    │  Event  │    │  Sync   │             │  │
│  │  └─────────┘    └─────────┘    └─────────┘    └─────────┘             │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                   │
┌──────────────────────────────────┼──────────────────────────────────────────┐
│                          DATA LAYER                                           │
│                                                                              │
│  ┌─────────────────────────┐    ┌─────────────────────────────────────────┐  │
│  │      PostgreSQL DB      │    │            Redis Cache (Optional)       │  │
│  │  • Users & tokens       │    │  • Session cache                        │  │
│  │  • User settings        │    │  • Rate limit counters                  │  │
│  │  • Processed messages   │    │  • Temporary event data                 │  │
│  │  • Event records        │    │                                         │  │
│  └─────────────────────────┘    └─────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                   │
┌──────────────────────────────────┼──────────────────────────────────────────┐
│                        EXTERNAL SERVICES                                      │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐  │
│  │  Google OAuth2  │  │   Gmail API     │  │   Google Calendar API       │  │
│  │                 │  │                 │  │                             │  │
│  │ • Authorization │  │ • users.watch   │  │ • events.insert             │  │
│  │ • Token refresh │  │ • messages.list │  │ • events.update             │  │
│  │                 │  │ • messages.get  │  │ • events.delete             │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────────────────┘  │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────────────────────────────────────┐   │
│  │  Google Pub/Sub │  │              LLM Provider (Pluggable)           │   │
│  │  (Optional)     │  │  • OpenAI / Anthropic / Local models            │   │
│  │                 │  │  • Abstracted via call_llm() interface          │   │
│  └─────────────────┘  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Data Flow: Gmail → Service → Calendar

#### 1. Authentication Flow
```
User → Frontend → [GET /auth/google] → Google OAuth Consent
      ↓
Google redirects to [GET /auth/callback] with authorization code
      ↓
Service exchanges code for tokens (access + refresh)
      ↓
Tokens encrypted and stored in PostgreSQL
      ↓
User session established, redirect to dashboard
```

#### 2. Email Processing Flow (Polling Mode - Default)
```
┌─────────────────────────────────────────────────────────────────┐
│                    SCHEDULER (Every 5 minutes)                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  FOR EACH ACTIVE USER:                                          │
│  1. Get valid access token (refresh if expired)                 │
│  2. Fetch Gmail history since last processed message            │
│  3. For each new message:                                       │
│     ├─ Check if already processed (by message ID)               │
│     ├─ Skip if matches exclusion filters                        │
│     ├─ Extract sender, subject, snippet                         │
│     ├─ Run through Event Extractor                              │
│     └─ If event detected:                                       │
│         ├─ Create "proposed" event record                       │
│         ├─ If auto-add enabled: Create calendar event           │
│         └─ Mark message as processed                            │
└─────────────────────────────────────────────────────────────────┘
```

#### 3. Email Processing Flow (Pub/Sub Mode - Production)
```
┌─────────────────────────────────────────────────────────────────┐
│  GMAIL PUB/SUB WATCH                                            │
│  • Service calls gmail.users.watch()                            │
│  • Gmail publishes to Google Pub/Sub topic                      │
│  • Webhook receives push notification                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  WEBHOOK HANDLER [POST /webhook/gmail]                          │
│  1. Validate Pub/Sub message signature                          │
│  2. Extract user email from notification                        │
│  3. Trigger async processing for that user                      │
└─────────────────────────────────────────────────────────────────┘
```

#### 4. Event Extraction Pipeline
```
┌─────────────────────────────────────────────────────────────────┐
│  INPUT: Email (subject, sender, body, headers)                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STAGE 1: HEURISTIC FILTER                                      │
│  • Keyword matching (meeting, event, appointment, etc.)         │
│  • Sender domain analysis (calendar invites, known domains)     │
│  • Subject line pattern matching                                │
│  • Quick rejection if clearly not event-related                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ (if passes)
┌─────────────────────────────────────────────────────────────────┐
│  STAGE 2: LLM EXTRACTION                                        │
│  • Construct prompt with email content                          │
│  • Call LLM via abstracted interface                            │
│  • Parse JSON response                                          │
│  • Calculate confidence score                                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STAGE 3: VALIDATION & SANITIZATION                             │
│  • Validate required fields (title, datetime)                   │
│  • Parse and validate datetime formats                          │
│  • Sanitize text fields (XSS prevention)                        │
│  • Validate timezone                                            │
│  • Set default values for optional fields                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  OUTPUT: EventCandidate                                         │
│  • title: str                                                   │
│  • description: str                                             │
│  • start_datetime: datetime                                     │
│  • end_datetime: datetime (optional)                            │
│  • timezone: str                                                │
│  • location: str (optional)                                     │
│  • importance_score: float (0-1)                                │
│  • confidence_score: float (0-1)                                │
│  • source_email_id: str                                         │
└─────────────────────────────────────────────────────────────────┘
```

#### 5. Calendar Sync Flow
```
┌─────────────────────────────────────────────────────────────────┐
│  EVENT CREATION (Auto or Manual)                                │
│  1. Get user's valid Calendar access token                      │
│  2. Create event via Calendar API                               │
│  3. Store calendar_event_id in our database                     │
│  4. Update event status (proposed → auto_created/accepted)      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  EVENT UPDATE/DELETE                                            │
│  • Sync changes from our DB to Calendar API                     │
│  • Handle conflicts (event deleted externally)                  │
│  • Soft delete in our DB when rejected                          │
└─────────────────────────────────────────────────────────────────┘
```

### Security Considerations

1. **Token Storage**: Refresh tokens are encrypted using AES-256-GCM before database storage
2. **Minimal Scopes**: Only request `gmail.readonly` and `calendar.events` scopes
3. **API Authentication**: JWT tokens for API access, with short expiration
4. **Rate Limiting**: Per-user and global rate limits to prevent abuse
5. **Input Validation**: All inputs validated via Pydantic models
6. **Output Sanitization**: XSS prevention on all text fields from LLM
7. **Audit Logging**: All sensitive operations logged with user ID and timestamp

### Scalability Considerations

1. **Horizontal Scaling**: Stateless API servers behind load balancer
2. **Background Jobs**: Celery or similar for email processing
3. **Database Connection Pooling**: SQLAlchemy async with connection pool
4. **Caching**: Redis for session data and rate limiting
5. **Monitoring**: Structured logging with correlation IDs

---

## API Design

### Authentication Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/auth/google` | Initiate Google OAuth flow |
| GET | `/auth/callback` | Handle OAuth callback from Google |
| POST | `/auth/logout` | Logout and invalidate session |
| GET | `/auth/me` | Get current user info |
| POST | `/auth/refresh` | Refresh access token |

### Event Management Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/events` | List all events (with filters) |
| GET | `/api/events/{event_id}` | Get event details |
| POST | `/api/events/{event_id}/accept` | Accept a proposed event |
| POST | `/api/events/{event_id}/reject` | Reject a proposed event |
| PUT | `/api/events/{event_id}` | Update event before accepting |
| DELETE | `/api/events/{event_id}` | Delete event |

### Settings Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/settings` | Get user settings |
| PUT | `/api/settings` | Update user settings |
| POST | `/api/settings/filters` | Add sender/label filter |
| DELETE | `/api/settings/filters/{filter_id}` | Remove filter |

### Webhook Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/webhook/gmail` | Handle Gmail Pub/Sub notifications |
| POST | `/webhook/gmail/renew` | Renew Gmail watch subscription |

### Admin/Monitoring Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check endpoint |
| GET | `/metrics` | Basic metrics (optional) |

---

## Request/Response Schemas

### Authentication

```python
# GET /auth/callback response
class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse

class UserResponse(BaseModel):
    id: str
    email: str
    name: Optional[str]
    picture: Optional[str]
    created_at: datetime
```

### Events

```python
class EventResponse(BaseModel):
    id: str
    title: str
    description: Optional[str]
    start_datetime: datetime
    end_datetime: Optional[datetime]
    timezone: str
    location: Optional[str]
    importance_score: float
    confidence_score: float
    status: EventStatus  # proposed, accepted, rejected, auto_created
    source_email_id: str
    calendar_event_id: Optional[str]
    created_at: datetime
    updated_at: datetime

class EventListResponse(BaseModel):
    events: List[EventResponse]
    total: int
    page: int
    page_size: int

class EventCreate(BaseModel):
    title: str
    description: Optional[str] = None
    start_datetime: datetime
    end_datetime: Optional[datetime] = None
    timezone: str = "UTC"
    location: Optional[str] = None

class EventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    start_datetime: Optional[datetime] = None
    end_datetime: Optional[datetime] = None
    timezone: Optional[str] = None
    location: Optional[str] = None
```

### Settings

```python
class UserSettings(BaseModel):
    auto_add_events: bool = False
    min_confidence_threshold: float = 0.7
    timezone: str = "UTC"
    email_notifications: bool = True
    created_at: datetime
    updated_at: datetime

class FilterCreate(BaseModel):
    filter_type: str  # "sender" or "label"
    filter_value: str
    action: str  # "include" or "exclude"

class FilterResponse(BaseModel):
    id: str
    filter_type: str
    filter_value: str
    action: str
    created_at: datetime
```

---

## Database Schema

### Core Tables

```sql
-- Users table
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    google_id VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255),
    picture_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE
);

-- OAuth tokens table (encrypted)
CREATE TABLE oauth_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    access_token TEXT NOT NULL,  -- Encrypted
    refresh_token TEXT NOT NULL, -- Encrypted
    token_type VARCHAR(50) DEFAULT 'Bearer',
    expires_at TIMESTAMP WITH TIME ZONE,
    scope TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id)
);

-- User settings table
CREATE TABLE user_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    auto_add_events BOOLEAN DEFAULT FALSE,
    min_confidence_threshold FLOAT DEFAULT 0.7,
    timezone VARCHAR(100) DEFAULT 'UTC',
    email_notifications BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id)
);

-- Filters table (sender/label filters)
CREATE TABLE filters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filter_type VARCHAR(50) NOT NULL,  -- 'sender' or 'label'
    filter_value VARCHAR(255) NOT NULL,
    action VARCHAR(50) NOT NULL,  -- 'include' or 'exclude'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, filter_type, filter_value)
);

-- Processed Gmail messages table
CREATE TABLE processed_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    gmail_message_id VARCHAR(255) NOT NULL,
    gmail_thread_id VARCHAR(255),
    processed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    result VARCHAR(50),  -- 'event_created', 'no_event', 'filtered_out', 'error'
    UNIQUE(user_id, gmail_message_id)
);

-- Events table
CREATE TABLE events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(500) NOT NULL,
    description TEXT,
    start_datetime TIMESTAMP WITH TIME ZONE NOT NULL,
    end_datetime TIMESTAMP WITH TIME ZONE,
    timezone VARCHAR(100) DEFAULT 'UTC',
    location VARCHAR(500),
    importance_score FLOAT DEFAULT 0.5,
    confidence_score FLOAT DEFAULT 0.5,
    status VARCHAR(50) DEFAULT 'proposed',  -- proposed, accepted, rejected, auto_created
    source_email_id VARCHAR(255) NOT NULL,
    source_email_subject VARCHAR(500),
    source_email_sender VARCHAR(255),
    calendar_event_id VARCHAR(255),
    calendar_synced_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Gmail watch history (for Pub/Sub mode)
CREATE TABLE gmail_watches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    history_id BIGINT NOT NULL,
    expiration TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id)
);

-- Audit log table
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50),
    resource_id UUID,
    details JSONB,
    ip_address VARCHAR(45),
    user_agent TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_events_user_status ON events(user_id, status);
CREATE INDEX idx_events_start_date ON events(start_datetime);
CREATE INDEX idx_processed_messages_user ON processed_messages(user_id, processed_at);
CREATE INDEX idx_filters_user ON filters(user_id);
CREATE INDEX idx_audit_logs_user ON audit_logs(user_id, created_at);
```

---

## Implementation Milestones

### Milestone 1: Foundation (Day 1)
- [x] Project structure setup
- [ ] Configuration module with environment variables
- [ ] Database models and migrations
- [ ] Logging setup

### Milestone 2: Authentication (Day 1-2)
- [ ] Google OAuth2 integration
- [ ] Token encryption/decryption
- [ ] Session management
- [ ] Auth middleware

### Milestone 3: Gmail Integration (Day 2-3)
- [ ] Gmail API client wrapper
- [ ] Message fetching logic
- [ ] Processing queue/scheduler
- [ ] Pub/Sub webhook handler (optional)

### Milestone 4: Event Extraction (Day 3-4)
- [ ] Heuristic filter implementation
- [ ] LLM abstraction interface
- [ ] Prompt templates
- [ ] Output validation and sanitization

### Milestone 5: Calendar Integration (Day 4-5)
- [ ] Calendar API client wrapper
- [ ] Event creation/update logic
- [ ] Sync status tracking

### Milestone 6: REST API (Day 5-6)
- [ ] Event management endpoints
- [ ] Settings endpoints
- [ ] Error handling
- [ ] Request validation

### Milestone 7: Testing & Documentation (Day 6-7)
- [ ] Unit tests for extraction
- [ ] Integration tests for API
- [ ] Setup guide
- [ ] API documentation
