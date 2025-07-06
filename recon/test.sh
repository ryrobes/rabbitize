
curl -X POST "https://recon3-242806648227.us-central1.run.app/start" \
  -H "Content-Type: application/json" \
  -d '{"playwright_url": "http://10.0.0.40:8889", "target_url": "https://status.cloud.google.com/",
  "objective": "Please browse this site and tell me what the current status is of Google Cloud SQL system in the us-central1 region please.  You will likely need to go to the Americas tab and scroll down, but please find it and verify.",
  "client_id": "buffy-ai", "test_id": "cloud-sql-status", "max_steps": 18}'
