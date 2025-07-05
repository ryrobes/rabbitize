# curl -X POST "https://recon3-242806648227.us-central1.run.app/start" \
#   -H "Content-Type: application/json" \
#   -d '{"playwright_url": "http://10.0.0.40:8889", "target_url":
"https://test.dash8.day8.com.au/client/index_prod.html?site=chaos&name=day8test&email=support@day8.com.au&sudo=14a56dc856e1f7ec&dev=true",
 "objective": "This is an Australian TV data analysis system - please click around, examine all the screens and their otions, try to figure out the UI, run some queries and see if you can learn anything. Try to take your time and give a comprehensive look over by investigating the various modules that you see available.  When you are satisfied that you have gleaned all you can from it. Please present what you have learned as well as how the UI could be improved to be more intuitive.", "client_id": "buffy-ai", "test_id": "dash8-recon", "max_steps": 30}'

# curl -X POST "https://recon3-242806648227.us-central1.run.app/start" \
#   -H "Content-Type: application/json" \
#   -d '{"playwright_url": "http://10.0.0.40:8889", "target_url": "https://test.dash8.day8.com.au/client/index_prod.html?site=chaos&name=day8test&email=support@day8.com.au&sudo=14a56dc856e1f7ec&dev=true", "objective": "Using the Dash8 interface can you explore and tell me what the most watched Program on the Nine network is, and how big that audience is? You will have to find the correct report - dont give up until you find the answer.", "client_id": "buffy-ai", "test_id": "dash8-recon-program", "max_steps": 100}'


curl -X POST "https://recon3-242806648227.us-central1.run.app/start" \
  -H "Content-Type: application/json" \
  -d '{"playwright_url": "http://10.0.0.40:8889", "target_url": "https://status.cloud.google.com/",
  "objective": "Please browse this site and tell me what the current status is of Google Cloud SQL system in the us-central1 region please.  You will likely need to go to the Americas tab and scroll down, but please find it and verify.",
  "client_id": "buffy-ai", "test_id": "cloud-sql-status", "max_steps": 18}'





curl -X POST "https://recon3-242806648227.us-central1.run.app/start" \
  -H "Content-Type: application/json" \
  -d '{"playwright_url": "http://10.0.0.84:8889", "target_url": "https://pxre-1v0r-428b-41871-v0-3-stellar-profit-dash.grinx.ai/", "objective": "1. Navigate to the main application page where the map is visible.\n2. **Map Smoothness Test:**\n    *   Click and drag the map to pan it in various directions (left, right, up, down).\n    *   Use the mouse scroll wheel (or map controls if available) to zoom in and out significantly on different areas of the map.\n    *   Report: Does the panning and zooming feel smooth and responsive, or is there noticeable stuttering, lag, or choppiness?\n3. **Tooltip Functionality Test:**\n    *   Identify at least 3 cyan (profitable) circle markers of different sizes on the map. Hover the mouse cursor over each one.\n    *   Identify at least 2 orange (unprofitable) circle markers of different sizes on the map. Hover the mouse cursor over each one.\n    *   For each of these 5 points, report:\n        *   Does a tooltip appear upon hover?\n        *   Does the tooltip contain all the following fields with plausible data: City, State, Total Sales, Total Profit, Profit Ratio, Number of Orders? (Verify all 6 fields are present and populated).", "client_id": "grinx-ai", "test_id": "grinx-ai", "max_steps": 30}'


curl -X POST "https://recon3-242806648227.us-central1.run.app/start" \
  -H "Content-Type: application/json" \
  -d '{"playwright_url": "http://10.0.0.90:8889", "target_url": "https://pxre-1oho-ed7e-28568-v4-0-hello-dark-mode.grinx.ai/", "objective": "1. **Locate the Button:** On the webpage, find the button labeled GET GREETING. It is a bright pink, rectangular button, located centrally on the page, below the main illustration of a woman interacting with a complex machine.\n2. **Click the Button:** Perform a single left-click on this GET GREETING button.\n3. **Observe the Display Area:** Look at the rectangular area positioned directly below the GET GREETING button. This area initially appears as a dark, empty box with a glowing orange border.\n4. **Report Text:** After clicking the button, report precisely what text, if any, appears within this bordered box. The expected text is Hello, World!. Note if any other text appears or if it remains empty.\n5.", "client_id": "grinx-ai", "test_id": "grinx-ai", "max_steps": 20}'




# curl -X POST "https://recon3-242806648227.us-central1.run.app/start" \
#   -H "Content-Type: application/json" \
#   -d '{"playwright_url": "http://10.0.0.32:8889",
#   "target_url": "https://test.dash8.day8.com.au/client/index_prod.html?site=chaos&name=day8test&email=support@day8.com.au&sudo=14a56dc856e1f7ec&dev=true",
#   "objective": "Is yesterdays OzTam data available? When was the last time it refreshed?.",
#   "client_id": "buffy-ai", "test_id": "dash8-recon", "max_steps": 50}'

# curl -X POST "https://recon3-242806648227.us-central1.run.app/start" \
#   -H "Content-Type: application/json" \
#   -d '{"playwright_url": "http://10.0.0.3:8889", "target_url": "https://metallica.com", "objective": "When and where is Metallicas next show?", "client_id": "buffy-ai", "test_id": "tallica-recon", "max_steps": 50}'


### https://silflay.rabbitize.ai/direct/extra-rabbit-worker47/api/stream/1

# curl -X POST "https://recon3-242806648227.us-central1.run.app/start" \
#   -H "Content-Type: application/json" \
#   -d '{"playwright_url": "http://10.0.0.40:8889", "target_url": "https://status.cloud.google.com/",
#   "objective": "Please browse this site and tell me what the current status is of Google Cloud SQL system in the us-central1 region please.  You will likely need to go to the Americas tab and scroll down, but please find it and verify.",
#   "client_id": "*client-id*", "test_id": "recon-flow", "max_steps": 18}'