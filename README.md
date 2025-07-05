# 🐰 Rabbitize

**Turn browser automation into a feedback loop.** Rabbitize is a REST API server that wraps Playwright, designed for AI agents, testing pipelines, and anyone who needs programmatic browser control with visual feedback.

## Why Rabbitize?

Traditional browser automation is blind - you send commands and hope they work. Rabbitize changes that:

- **See what's happening**: Every action is recorded with video + screenshots
- **Build interactively**: Use Flow Builder to create automations by clicking, then export as code
- **AI-friendly**: Send a command, get a screenshot back, decide what to do next
- **Observable by default**: Real-time streaming dashboard shows all active sessions

### 🎯 Real User Actions, Not DOM Tricks

While other tools cheat with invisible DOM manipulation, Rabbitize performs **actual user actions**:

```json
// What you see is what you get
[":move-mouse", ":to", 500, 300]
[":click", ":at", 500, 300]
[":drag", ":from", 100, 100, ":to", 400, 400]

// Not this nonsense
{"selector": "#app > div.container > form > input[data-testid='email-field-2']", 
 "action": "setValue", 
 "value": "test@example.com",
 "waitForSelector": true,
 "timeout": 30000}
```

- **Mouse actually moves** - Watch the cursor travel across the screen
- **Real coordinates** - Click at (x,y) just like a human would
- **Visual feedback** - See every action happen in real-time
- **No hidden shortcuts** - If a human can't do it, neither can Rabbitize

This matters because:
- ✅ Tests what users actually experience
- ✅ Works when DOM selectors break
- ✅ Catches visual bugs that DOM automation misses
- ✅ Anyone can understand `[":click", ":at", 400, 300]`

## Quick Start

```bash
# Start a session
curl -X POST http://localhost:3037/start \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'

# Click on something  
curl -X POST http://localhost:3037/execute \
  -H "Content-Type: application/json" \
  -d '{"command": [":click", ".button"]}'

# Get feedback (screenshot saved automatically)
# End session and get video
curl -X POST http://localhost:3037/end
```

## Key Features

### 🎯 Command-First Design
Simple JSON arrays for complex automations:
```json
[":click", ":at", 500, 300]
[":type", "Hello World"]
[":wait", 2]
[":screenshot"]
```

### 🎬 Rich Data Output - Every Detail Captured
Every Rabbitize session generates a comprehensive data archive:

**Visual Assets:**
- 📹 Full session video (WebM) with command overlay
- 📸 Screenshots: pre/post each command + thumbnails + zoomed views
- 🎞️ Animated GIF preview of the session
- 📺 Live mJPEG streaming during execution
- 🎬 Individual command video clips (optional)

**Structured Data:**
- 📊 `metrics.json` - Real-time performance metrics (CPU, memory, timing)
- 🎯 `commands.json` - Complete command log with status, timestamps, and results
- 🗺️ `dom_coords/*.json` - DOM element positions and attributes after each step
- 📄 `dom_snapshots/*.md` - Markdown representation of page content
- 📋 `session-metadata.json` - High-level session summary

**Analysis Ready:**
```
rabbitize-runs/
├── client-id/
│   └── test-id/
│       └── session-id/
│           ├── screenshots/     # All visual captures
│           ├── video/          # Session recordings
│           ├── dom_coords/     # Element positioning data
│           ├── dom_snapshots/  # Page content as markdown
│           ├── metrics.json    # Performance timeline
│           ├── commands.json   # Execution audit trail
│           └── latest.md       # Current page state
```

This rich output enables debugging, testing, monitoring, and AI analysis - all from a single run.

### ⚡ Flow Builder
Click-to-code automation builder:
1. Open Flow Builder UI
2. Navigate and click around
3. Export as CLI, cURL, or JSON
4. Replay and modify flows

### 🤖 Built for AI Agents
Perfect for LLMs that need to browse:
- REST API = works with any LLM tool framework
- Screenshots auto-saved to predictable paths
- Session stays alive between commands
- AI can analyze images and decide next steps

### 🔄 True Feedback Loops
```
POST /execute -> [":screenshot"]
Read: rabbitize-runs/.../screenshots/latest.jpg
AI analyzes image -> determines next action
POST /execute -> [":click", ":at", 400, 300]
Repeat until task complete
```

## Installation

```bash
git clone https://github.com/yourusername/rabbitize.git
cd rabbitize
npm install
npm start -- --client-id my-project --test-id test-1
```

## No Code? No Problem

**You don't need to be a developer to use Rabbitize.** Just want to record and replay web workflows?

1. **Start Rabbitize** - One command to launch
2. **Open Flow Builder** - Visit `http://localhost:3037/flow-builder`
3. **Click around** - Build your workflow visually
4. **Re-run anytime** - Your flow is saved and replayable from the dashboard
5. **Get all assets** - Videos, screenshots, clips automatically saved to `rabbitize-runs/`

Perfect for:
- **QA Engineers** - Record bugs with full visual proof
- **Product Managers** - Document workflows and user journeys
- **Support Teams** - Create visual guides and tutorials
- **Anyone** - If you can click, you can automate

Want to schedule your flow? Just copy the provided CLI command and add it to cron. No coding required - it's already written for you.

## Use Cases

### Automated Testing
```bash
# Run regression tests with visual proof
node src/index.js \
  --client-id regression \
  --test-id login-flow \
  --batch-url "https://myapp.com" \
  --batch-commands='[[":click", "#login"], [":type", "user@example.com"]]'
```

### Web Scraping
```bash
# Extract data with visual verification
./scrape.sh | rabbitize --client-id scraper --test-id daily
```

### Monitoring
```bash
# Schedule with cron, get videos of failures
0 */4 * * * rabbitize-monitor.sh
```

### AI Assistants
```bash
# REST calls + watch output folder = AI browser control
POST /execute -> {"command": [":click", ".search"]}
# Screenshot appears in: rabbitize-runs/client/test/session/screenshots/
# LLM analyzes image, decides next action
POST /execute -> {"command": [":type", "AI query"]}
# Session stays alive, maintaining state between decisions
```

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Your App  │────▶│  Rabbitize  │────▶│ Playwright  │
│  (AI/Script)│◀────│    Server   │◀────│  Browser    │
└─────────────┘     └─────────────┘     └─────────────┘
       │                    │                    │
       │                    ▼                    │
       │            ┌─────────────┐              │
       └───────────▶│  Dashboard  │◀─────────────┘
                    │ (Live View) │
                    └─────────────┘
```

## Command Reference

### Core Commands
- `:navigate` - Go to URL
- `:click` - Click element or coordinates
- `:type` - Type text
- `:wait` - Wait seconds
- `:screenshot` - Capture screenshot
- `:scroll` - Scroll page

### Advanced Commands
- `:drag` - Drag elements
- `:hover` - Hover over element
- `:key` - Send keyboard key
- `:exec` - Execute JavaScript
- `:wait-for` - Wait for element/condition
- `:extract` - Extract text from area

[Full command reference →](docs/commands.md)

## Configuration

```bash
# Basic usage
npm start -- --client-id my-app --test-id test-1

# With video processing
npm start -- \
  --client-id my-app \
  --test-id test-1 \
  --process-video \
  --create-clips

# For production
npm start -- \
  --client-id prod \
  --test-id monitoring \
  --port 3037 \
  --stability-detection \
  --live-screenshots
```

## Dashboard

Access the real-time dashboard at `http://localhost:3037/streaming`:

- Live session monitoring
- Video playback with command overlay
- Session history and re-runs
- Export commands for replay

## Flow Builder

Interactive automation designer at `http://localhost:3037/flow-builder`:

1. Enter URL and start session
2. Click around to build your flow
3. See commands in real-time
4. Export as code when done

## Comparison

| Feature | Rabbitize | Playwright Test | Puppeteer | Selenium |
|---------|-----------|-----------------|-----------|----------|
| REST API | ✅ Native | ❌ Code only | ❌ Code only | ❌ Code only |
| Visual Feedback | ✅ Built-in | 🟡 Screenshots | 🟡 Screenshots | 🟡 Screenshots |
| Live Monitoring | ✅ Dashboard | ❌ Terminal | ❌ Terminal | ❌ Terminal |
| Click-to-Code | ✅ Flow Builder | 🟡 Codegen | ❌ None | ❌ None |
| AI-Friendly | ✅ Designed for | 🟡 Possible | 🟡 Possible | 🟡 Possible |
| Command Replay | ✅ Multiple formats | ❌ Code only | ❌ Code only | ❌ Code only |
| **Real Mouse Movement** | ✅ Always | ❌ DOM shortcuts | ❌ DOM shortcuts | ❌ DOM shortcuts |
| **Coordinate-Based** | ✅ Primary | 🟡 Secondary | 🟡 Secondary | 🟡 Secondary |
| **Visual Testing** | ✅ Natural | 🟡 Add-ons | 🟡 Add-ons | 🟡 Add-ons |
| **Human-Like Actions** | ✅ Default | ❌ Synthetic | ❌ Synthetic | ❌ Synthetic |

## Examples

See the [examples/](examples/) directory for:
- AI agent web browsing
- Visual regression testing  
- Data extraction pipelines
- Scheduled monitoring
- Batch processing

## Contributing

PRs welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT

---

Built with 🐰 by the Rabbitize team