node src/index.js \
  --stability-detection false \
  --exit-on-end true \
  --process-video true \
  --client-id "test" \
  --port 3337 \
  --test-id "batchtest" \
  --batch-url "https://datarabbit.com" \
  --batch-commands='[
    [":move-mouse", ":to", 1600, 75],
    [":move-mouse", ":to", 1600, 575],
    [":scroll-wheel-down", 3],
    [":wait", 5],
    [":scroll-wheel-up", 3],
    [":move-mouse", ":to", 1600, 75],
    [":click"],
    [":wait", 15],
    [":move-mouse", ":to", 1000, 200],
    [":move-mouse", ":to", 2000, 1200],
    [":keypress", "Shift-f"],
    [":wait", 5],
    [":keypress", "Shift-f"],
    [":wait", 5],
    [":keypress", "Shift-q"],
    [":wait", 5],
    [":keypress", "Shift-q"],
    [":wait", 5],
    [":move-mouse", ":to", 1000, 100],
    [":drag", ":from", 1000, 100, ":to", 2000, 200],
    [":click"],
    [":wait", 10],
    [":keypress", "Space"],
    [":scroll-wheel-down", 10],
    [":wait", 10],
    [":scroll-wheel-up", 13],
    [":keypress", "Space"],
    [":click"],
    [":keypress", "Tab"],
    [":keypress", "Tab"],
    [":keypress", "Tab"],
    [":keypress", "Tab"],
    [":keypress", "Tab"],
    [":keypress", "e"],
    [":keypress", "e"],
    [":keypress", "e"],
    [":keypress", "e"],
    [":keypress", "e"],
    [":keypress", "Space"],
    [":scroll-wheel-down", 5],
    [":drag", ":from", 2000, 200, ":to", 2000, 400],
    [":scroll-wheel-up", 5],
    [":keypress", "Space"]
  ]'

