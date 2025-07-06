
# curl -X POST "http://localhost:3737/start" \
#   -H "Content-Type: application/json" \
#   -d '{"rabbitize_url": "http://localhost:3037", "target_url": "https://status.cloud.google.com/", "client_id": "interactive", "test_id": "interactive", "rabbitize_runs_dir": "/home/ryanr/rabbitize-public/rabbitize-runs/",
#   "objective": "Please browse this site and tell me what the current status is of Google Cloud SQL system in the us-central1 region please.  You will likely need to go to the Americas tab and scroll down, but please find it and verify.",
#   "session_id": "interactive", "max_steps": 10}'

# curl -X POST "http://localhost:3737/start" \
#   -H "Content-Type: application/json" \
#   -d '{"rabbitize_url": "http://localhost:3037", "target_url": "https://metallica.com/", "client_id": "interactive", "test_id": "interactive", "rabbitize_runs_dir": "/home/ryanr/rabbitize-public/rabbitize-runs/",
#   "objective": "If Today is July 5th, 2025 - When is Metallicas next show in the US?",
#   "session_id": "interactive", "max_steps": 21}'

curl -X POST "http://localhost:3737/start" \
  -H "Content-Type: application/json" \
  -d '{"rabbitize_url": "http://localhost:3037", "target_url": "https://open-meteo.com/", "client_id": "interactive", "test_id": "interactive", "rabbitize_runs_dir": "/home/ryanr/rabbitize-public/rabbitize-runs/",
  "objective": "What is the weather going to be like this week in Nashville, TN?",
  "session_id": "interactive", "max_steps": 20}'