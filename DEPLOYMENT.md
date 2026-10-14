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

### 3. Production deployment target: Hetzner

Hetzner is the production target. This repository has not yet completed a Hetzner cutover; review `DEPLOYMENT_TARGET.md` and complete the per-app topology before exposing a production service.

The application uses a Flask API and worker, a React frontend, a database, and OAuth callbacks. Before cutover, confirm persistent database and upload storage, configure the exact HTTPS frontend/API origins and Google OAuth redirect URIs, provision secrets outside Git, and document backups, TLS, health monitoring, and rollback. The included Compose configuration is a single-host starting point, not production acceptance.

Build the frontend with `npm run build` and serve the generated `dist` output from the reviewed Hetzner service. Set `VITE_API_URL` at build time to the public HTTPS API URL and configure `CORS_ORIGINS` with the exact production frontend origin.

## Configuration

### Environment Variables

#### Backend (.env)
```
GOOGLE_CLIENT_SECRETS_FILE=credentials.json
TOKEN_FILE=token.json
OPENAI_API_KEY=sk-your-openai-key
SECRET_KEY=your-secret-key-here
FLASK_ENV=production
PORT=5000
```

#### Frontend (.env)
```
VITE_API_URL=https://your-backend-url.com/api
```

### Google API Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable YouTube Data API v3
4. Create OAuth 2.0 credentials (Web application)
5. Add authorized redirect URIs:
   - `http://localhost:5000/api/auth/callback` (development)
   - `https://your-domain.com/api/auth/callback` (production)
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
