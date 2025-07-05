curl -s -X POST http://localhost:3000/start  -H "Content-Type: application/json"  -d '{"url": "https://datarabbit.com"}' | jq
curl -s -X POST http://localhost:3000/execute  -H "Content-Type: application/json"  -d '{"command": [":move-mouse", ":to", 100, 200]}' | jq
curl -s -X POST http://localhost:3000/execute  -H "Content-Type: application/json"  -d '{"command": [":move-mouse", ":to", 200, 10]}' | jq
curl -s -X POST http://localhost:3000/execute  -H "Content-Type: application/json"  -d '{"command": [":move-mouse", ":to", 10, 1230]}' | jq
curl -s -X POST http://localhost:3000/execute  -H "Content-Type: application/json"  -d '{"command": [":click"]}' | jq
curl -s -X POST http://localhost:3000/execute  -H "Content-Type: application/json"  -d '{"command": [":drag", ":from", 100, 100, ":to", 200, 200]}' | jq
curl -s -X POST http://localhost:3000/end | jq


