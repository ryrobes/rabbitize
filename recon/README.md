# Recon Service

Browser automation service for detecting and interacting with elements in web applications.

## Requirements

- Python 3.11+
- Docker (for containerized deployment)
- Google Cloud SDK (for GCP deployment)

## Local Development

1. Create a virtual environment:
   ```
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Set environment variables:
   ```
   export GEMINI_API_KEY=your_api_key_here
   ```

4. Run the application:
   ```
   uvicorn main:app --reload --host 0.0.0.0 --port 8080
   ```

## Docker Deployment

Build and run the Docker container:

```
docker build -t recon-service .
docker run -p 8080:8080 -e GEMINI_API_KEY=your_api_key_here recon-service
```

## Google Cloud Deployment

### Manual Deployment to Cloud Run

1. Build the container:
   ```
   docker build -t gcr.io/[PROJECT_ID]/recon-service .
   ```

2. Push to Container Registry:
   ```
   docker push gcr.io/[PROJECT_ID]/recon-service
   ```

3. Deploy to Cloud Run:
   ```
   gcloud run deploy recon-service \
     --image gcr.io/[PROJECT_ID]/recon-service \
     --platform managed \
     --region us-central1 \
     --allow-unauthenticated \
     --memory 512Mi \
     --cpu 1 \
     --timeout 600s \
     --set-env-vars GEMINI_API_KEY=your_api_key_here
   ```

### Automated Deployment with Cloud Build

Set up a trigger in Cloud Build to automatically build and deploy when changes are pushed to your repository:

1. Connect your repository to Cloud Build
2. Create a trigger that uses the provided `cloudbuild.yaml`
3. Set up environment variables in the Cloud Run service settings

**Important:** Make sure to set the `GEMINI_API_KEY` environment variable in the Cloud Run console or via the `gcloud` command.

## Environment Variables

- `GEMINI_API_KEY`: API key for Gemini API (required)
- `PORT`: Port for the server (defaults to 8080)