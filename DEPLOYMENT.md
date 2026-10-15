# Deployment Guide - YouTube Automator Unified

## Quick Start

### Prerequisites
- Python 3.8+ with pip
- Node.js 18+ with npm
- Google Cloud Project with YouTube Data API v3 enabled
- OpenAI API key (optional, for AI features)

### 1. Backend Setup

```bash
# Navigate to backend directory
cd backend

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env file with your actual values

# Place your Google credentials file
# Download credentials.json from Google Cloud Console
# Place it in the backend directory

# Run the backend server
python app.py
```

### 2. Frontend Setup

```bash
# Navigate to frontend directory
cd frontend

# Install dependencies
npm install

# Set up environment variables
cp .env.example .env
# Edit .env file with your API URL

# Run the development server
npm run dev
```

### 3. Hetzner production target

Hetzner is the production target. This guide is a migration plan and does not claim that production has been deployed or cut over.

The current `docker-compose.yml` starts the Flask API and worker with persistent Docker volumes. The frontend is a separate Vite build, and Compose does not include a frontend server or HTTPS reverse proxy. The sample database defaults to SQLite; choose and validate the production database and migration plan before cutover.

Before production cutover:

1. Provision a Hetzner Linux host, secure SSH access, and restrict inbound traffic to SSH and HTTPS.
2. Configure DNS and an HTTPS reverse proxy. Keep the API port private behind the proxy; the current Compose file publishes port 5000 on all interfaces.
3. Store Google OAuth credentials, `SECRET_KEY`, `TOKEN_ENCRYPTION_KEY`, and other production secrets outside Git. Configure `DATABASE_URL`, `FRONTEND_URL`, and exact HTTPS `CORS_ORIGINS` from `backend/.env.example`.
4. Build the frontend with `VITE_API_URL=https://YOUR_DOMAIN/api`; serve the build output with SPA fallback.
5. Back up the database, uploads, generated media, and OAuth configuration. Restore them on the target and verify persistence and ownership.
6. Apply schema migrations, then verify API, worker, OAuth, upload, and database behavior against the target data.
7. Verify TLS, firewall rules, monitoring, scheduled backups, restore, and the documented rollback path before switching production traffic.

Record the host, DNS change, backup identifier, deployment revision, verification evidence, and rollback decision in the release record. Do not claim a completed migration until these checks pass.

## Configuration

### Environment Variables

Use `backend/.env.example` and `frontend/.env.example` as the current variable references. Keep real secrets and OAuth credential files outside Git. A production frontend build must use the HTTPS API URL; never use a localhost address in the production build.

### Google API Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable YouTube Data API v3
4. Create OAuth 2.0 credentials (Web application)
5. Add authorized redirect URIs:
   - `http://localhost:5000/api/auth/callback` (development)
   - `https://YOUR_DOMAIN/api/auth/callback` (production)
6. Download credentials as JSON file

## Features Overview

### ✅ Implemented Features
- **Authentication**: Google OAuth2 integration
- **Video Upload**: Direct upload to YouTube
- **AI Metadata**: OpenAI-powered title/description generation
- **Playlist Management**: Create and manage playlists
- **Speed Testing**: Upload speed measurement
- **Modern UI**: React with Tailwind CSS
- **API Architecture**: RESTful Flask backend

### 🚧 Extensible Features (Ready for Implementation)
- **Transcription**: Video-to-text conversion
- **Thumbnail Generation**: Custom thumbnail creation
- **Scheduling**: Video publication scheduling
- **Analytics**: Upload and performance tracking

## API Documentation

### Authentication Endpoints
- `GET /api/auth/status` - Check authentication status
- `GET /api/auth/login` - Initiate OAuth flow
- `GET /api/auth/callback` - Handle OAuth callback
- `POST /api/auth/logout` - Logout user

### Upload Endpoints
- `POST /api/upload/video` - Upload video to YouTube
- `POST /api/upload/validate` - Validate video file

### Metadata Endpoints
- `POST /api/metadata/generate` - Generate complete metadata
- `POST /api/metadata/title` - Generate title only
- `POST /api/metadata/description` - Generate description only

### Playlist Endpoints
- `GET /api/playlists/` - List user playlists
- `POST /api/playlists/` - Create new playlist
- `GET /api/playlists/{id}/videos` - List playlist videos

## Troubleshooting

### Common Issues

**1. Authentication Fails**
- Check Google credentials file path
- Verify redirect URIs in Google Console
- Ensure scopes are correctly configured

**2. Upload Fails**
- Check file size limits (YouTube: 256GB, App: 500MB default)
- Verify video format is supported
- Check YouTube API quotas

**3. Metadata Generation Fails**
- Verify OpenAI API key is set
- Check API key has sufficient credits
- Ensure network connectivity

**4. CORS Issues**
- Update CORS_ORIGINS in backend configuration
- Check frontend API URL configuration

### Logs and Debugging

**Backend Logs**
```bash
# View Flask logs
python app.py

# Enable debug mode
export FLASK_ENV=development
```

**Frontend Logs**
```bash
# View build logs
npm run build

# View development logs
npm run dev
```

## Security Considerations

1. **API Keys**: Never commit API keys to version control
2. **HTTPS**: Use HTTPS in production
3. **CORS**: Configure CORS properly for production domains
4. **Token Storage**: Secure token file storage
5. **File Uploads**: Validate file types and sizes

## Performance Optimization

1. **File Compression**: Compress videos before upload
2. **Chunked Upload**: Use resumable uploads for large files
3. **Caching**: Implement Redis for session caching
4. **CDN**: Use CDN for static assets
5. **Database**: Add database for metadata persistence

## Monitoring

1. **Health Checks**: Use `/api/health` endpoint
2. **Error Tracking**: Implement Sentry or similar
3. **Analytics**: Track upload success rates
4. **Performance**: Monitor API response times

## Support

For issues and questions:
1. Check this deployment guide
2. Review the main README.md
3. Check API documentation
4. Create an issue with detailed information
