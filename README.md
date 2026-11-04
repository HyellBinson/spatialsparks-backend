# SpatialSparks Backend

The backend service powering **SpatialSparks**, an AI-assisted visual inspection and troubleshooting platform for electronic hardware.

SpatialSparks allows users to upload images of electronic devices, inspect visual components, and interact with an AI copilot for explanations and troubleshooting guidance.

## Features

- FastAPI REST API
- Supabase authentication integration
- PostgreSQL database for conversations and messages
- Supabase Storage for inspection images
- AI-powered inspection chat using Muse Spark Open through Baseten
- Image segmentation through a SAM 3-powered Hugging Face Space
- Google sign-in support
- User-specific conversation and upload records

## Technology Stack

- Python
- FastAPI
- PostgreSQL
- Supabase Auth and Storage
- Psycopg
- Baseten inference API
- Hugging Face Gradio Client
- fal.ai integration

## Local Setup

### 1. Clone the repository

```bash
git clone https://github.com/HyellBinson/spatialsparks-backend.git
cd spatialsparks-backend
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

### 3. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file using `.env.example` as your template.

Fill in the required credentials. Never commit your actual `.env` file.

### 5. Start the server

```bash
python -m uvicorn app.main:app --reload
```

API: `http://127.0.0.1:8000`

Interactive documentation: `http://127.0.0.1:8000/docs`

## Environment Variables

See `.env.example` for the configuration template.

The backend uses environment variables for:

- Supabase database and storage access
- Baseten AI inference
- Image segmentation integrations
- Google OAuth
- JWT authentication settings

Keep all secret keys on the backend. Never expose service-role keys or provider API keys in frontend code.

## Frontend

https://github.com/HyellBinson/spatialsparks

## Security

- Credentials are loaded through environment variables.
- `.env` files are excluded from version control.
- User-specific data is associated with authenticated accounts.
- Uploaded images are stored using Supabase Storage.

## Project

**SpatialSparks** — Making electronic hardware inspection more accessible through AI and computer vision.
