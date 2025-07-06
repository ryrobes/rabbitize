# Rabbitize (🐰👀)

**Point. Click. Rabbitize.**

*Turn Playwright into a live, stateful REST service - recording video, screenshots, and DOM snapshots for every step—so humans and AI agents can SEE automation, not just hope it worked.*

![playwright rabbit masks](https://raw.githubusercontent.com/ryrobes/rabbitize/refs/heads/main/resources/streaming/images/rabbitize-masks.png "Rabbitize + Playwright")

[![CI](https://github.com/ryrobes/rabbitize/actions/workflows/node.js.yml/badge.svg)](https://github.com/ryrobes/rabbitize/actions) [![npm](https://img.shields.io/npm/v/rabbitize.svg)](https://www.npmjs.com/package/rabbitize) [![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

```bash
# LFG
npm install rabbitize
sudo npx playwright install-deps # required for PW to work
npx rabbitize # start server for interactive sessions
# http://localhost:3037
```

## Why Rabbitize?
- Visual by default – video + before/after screenshots for every command.
- Stateful sessions – keep browsers warm between API calls.
- AI-ready – deterministic file paths for screenshots & DOM dumps.
- Human-like coordinates – real mouse movement, not synthetic DOM clicks.
- Click-to-code Flow Builder – non-devs can point-and-automate.
- Declarative - just some simple JSON

![video](https://github.com/user-attachments/assets/5f7ff405-1c11-48f6-810f-78aa8b73bf91)

## The Problem

1. Traditional browser automation is blind. You write scripts, run them, and hope they work. When they fail, you're left guessing why.
2. These tools are often geared toward developers and have a high bar for entry for people just looking to locally automate some workflow.

## The Solution

Rabbitize changes browser automation from a black box into a visual feedback loop:

```bash
# Send a command
curl -X POST localhost:3037/execute -d '{"command": [":move-mouse", ":to", 240, 1230]}'

# Get instant visual feedback
ls rabbitize-runs/session/screenshots/
# before-click.jpg
# after-click.jpg
# zoomed-click.jpg
```

Every action generates screenshots, videos, a markdown'd DOM, and performance data. Sessions stay alive between commands, enabling true interactive automation.

## Two Ways to Use It

### For Everyone: Flow Builder & Browser
Point, click, and create automations without writing code:
1. Open `http://localhost:3037/flow-builder`
2. Click around any website
3. Watch your automation build itself
4. End the session (saves)
4. Export as cURL, CLI, schedule with cron, or go to the Dashboard and re-run it with a single click
5. Browse historical data collected via the UI or your harddrive (no weird formats)

### For Developers: REST API
Perfect for AI agents and complex integrations:
```python
# Start session
response = requests.post("http://localhost:3000/start", json={"url": "https://example.com"})

# AI analyzes screenshot, decides next action
response = requests.post("http://localhost:3000/execute", json={"command": [":click", ":at", 400, 300]})

# Session maintains state, ready for next command when you are
# or script CURL commands!
```

```bash
# or run the whole thing in one shot (once your commands are nailed down, just run it - process will end on completion)
node src/index.js \
  --stability-detection false \
  --exit-on-end true \
  --process-video true \
  --client-id "test" \
  --port 3000 \
  --test-id "batchtest" \
  --batch-url "https://rvbbit.com" \
  --batch-commands='[
    [":move-mouse", ":to", 1600, 75],
    [":move-mouse", ":to", 1600, 575],
    [":scroll-wheel-down", 3],
    [":wait", 5],
    [":scroll-wheel-up", 3],
    [":move-mouse", ":to", 1600, 75]
    # ...etc...
  ]'
```

## What Makes It Different

| Traditional Automation | Rabbitize |
|------------------------|-----------|
| DOM selectors break | Uses visual coordinates |
| Blind execution | See every action happen |
| Code-only | Click-to-create + API |
| Start from scratch each time | Stateful sessions |
| "Did it work?" | Full video + screenshots |

- **Mouse actually moves** - Watch the cursor travel across the screen
- **Real coordinates** - Click at (x,y) just like a human would
- **Visual feedback** - See every action happen in real(ish)-time
- **No hidden shortcuts** - If a human can't do it, neither should your tests

## Real-World Use Cases

- **QA Engineers**: Record bugs with visual proof, no coding required
- **AI Developers**: Build web agents that can see and react
- **Business Users**: Automate daily tasks by showing, not coding
- **DevOps**: Monitor sites with video evidence of failures

## Example: AI Web Agent

```javascript
// 1. Start browser
await fetch('/start', {
  method: 'POST',
  body: JSON.stringify({ url: 'https://news.ycombinator.com' })
});

// 2. AI reads screenshot from deterministic filepath: rabbitize-runs/.../screenshots/latest.jpg
// 3. AI decides: "Click on the top story"

await fetch('/execute', {
  method: 'POST',
  body: JSON.stringify({ command: [':click', ':at', 150, 200] })
});

// 4. New screenshot appears, AI continues...

// OR scripted as a "tool" for an LLM to use
```

## Boatloads of data at every step

Every session creates:

```
rabbitize-runs/
└── session-id/
    ├── video.webm          # Full session recording
    ├── screenshots/        # Before/after each action
    ├── commands.json       # Detailed audit trail
    ├── metrics.json        # Performance data
    ├── dom_snapshots/      # Page content as markdown text
    └── dom_coords/         # All useful DOM info in simple JSON
```

## Commands Are Simple

```json
[":navigate", "https://rvbbit.com"]
[":move-mouse", ":to", 150, 200]
[":click"]
[":type", "Hello World"]
[":scroll-wheel-down", 5]
[":wait", 2]
```

## Real coordinates. Real mouse movement. Real results. No javascript required.

## Dashboard

Watch automations run live at `http://localhost:3037`:

## License

MIT

---

**Stop writing blind browser automation.** Start seeing what actually happens.

_Ryan Robitaille 2025_
