#!/usr/bin/env node
// src/index.js
const express = require('express');
const PlaywrightSession = require('./PlaywrightSession');
const yargs = require('yargs/yargs');
const { hideBin } = require('yargs/helpers');
const SimpleLogger = require('./utils/simpleLogger');
const fs = require('fs');
const fsPromises = require('fs').promises;
const path = require('path');
const chalk = require('chalk');
const queueManager = require('./utils/queueManager');
const imageCompare = require('./utils/imageCompare');
const os = require('os');
const { EventEmitter } = require('events');
const { execFile, spawn } = require('child_process');
const net = require('net');
const crypto = require('crypto');

// --- Simple password auth (enabled when RABBITIZE_PASSWORD env var is set) ---
const RABBITIZE_PASSWORD = process.env.RABBITIZE_PASSWORD || null;
const validAuthTokens = new Set();

function parseCookies(cookieHeader) {
  const cookies = {};
  if (!cookieHeader) return cookies;
  cookieHeader.split(';').forEach(part => {
    const [name, ...rest] = part.split('=');
    if (name) cookies[name.trim()] = rest.join('=').trim();
  });
  return cookies;
}

function authMiddleware(req, res, next) {
  if (!RABBITIZE_PASSWORD) return next(); // Auth disabled
  const cookies = parseCookies(req.headers.cookie);
  if (cookies.rabbitize_auth && validAuthTokens.has(cookies.rabbitize_auth)) {
    return next();
  }
  // API / non-browser clients get a 401
  const accept = req.headers.accept || '';
  if (!accept.includes('text/html')) {
    return res.status(401).json({ error: 'Unauthorized - please log in via the web UI' });
  }
  res.redirect('/login');
}

const NUMERIC_STRING_RE = /^-?\d+\.?\d*$/;
const NUMERIC_ARG_INDEXES_BY_COMMAND = {
  ':wait': [1],
  ':move-mouse': [2, 3],
  ':click': [3, 4],
  ':right-click': [3, 4],
  ':middle-click': [3, 4],
  ':click-hold': [3, 4],
  ':click-release': [3, 4],
  ':right-click-hold': [3, 4],
  ':right-click-release': [3, 4],
  ':middle-click-hold': [3, 4],
  ':middle-click-release': [3, 4],
  ':drag': [2, 3, 5, 6],
  ':start-drag': [2, 3],
  ':end-drag': [2, 3],
  ':scroll-wheel-up': [1],
  ':scroll-wheel-down': [1],
  ':width': [1],
  ':height': [1],
  ':extract': [1, 2, 3, 4],
  ':rabbit-eyes': [1, 2, 3, 4],
  ':rabbit-eyes-DISABLED': [1, 2, 3, 4]
};

function normalizeCommandTypes(command) {
  if (!Array.isArray(command) || command.length === 0) {
    return command;
  }

  const commandType = command[0];
  if (typeof commandType !== 'string') {
    return command;
  }

  const numericIndexes = NUMERIC_ARG_INDEXES_BY_COMMAND[commandType];
  if (!numericIndexes) {
    return command;
  }

  return command.map((item, index) => {
    if (!numericIndexes.includes(index)) {
      return item;
    }

    if (typeof item === 'string' && NUMERIC_STRING_RE.test(item)) {
      return Number(item);
    }

    return item;
  });
}

// Parse command line arguments
const argv = yargs(hideBin(process.argv))
  .option('client-id', {
    alias: 'c',
    type: 'string',
    description: 'Client ID',
    default: 'interactive'
  })
  .option('test-id', {
    alias: 't',
    type: 'string',
    description: 'Test ID',
    default: 'interactive'
  })
  .option('hostname', {
    alias: 'h',
    type: 'string',
    description: 'Hostname identifier',
    default: 'unknown'
  })
  .option('port', {
    alias: 'p',
    type: 'number',
    description: 'Port number',
    default: 3037
  })
  .option('show-overlay', {
    alias: 'o',
    type: 'boolean',
    description: 'Show command overlay in recordings',
    default: true
  })
  .option('clip-segments', {
    type: 'boolean',
    description: 'Create individual video segments for each command',
    default: false
  })
  .option('batch-commands', {
    type: 'string',
    description: 'JSON string or file path containing batch commands'
  })
  .option('batch-url', {
    type: 'string',
    description: 'Starting URL for batch mode'
  })
  .option('exit-on-end', {
    type: 'boolean',
    description: 'Exit process after session ends',
    default: false
  })
  .option('process-video', {
    type: 'boolean',
    description: 'Convert webm to mp4 and create speed variants',
    default: true
  })
  .option('meta', {
    type: 'string',
    description: 'Additional metadata for the run',
    default: ''
  })
  .option('live-screenshots', {
    type: 'boolean',
    description: 'Enable live screenshots during session',
    default: true
  })
  .option('url', {
    description: 'URL to automatically start a session with',
    type: 'string'
  })
  .option('commands', {
    description: 'JSON array of commands to queue after URL start',
    type: 'string'
  })
  .option('stability-detection', {
    alias: 'sd',
    type: 'boolean',
    description: 'Enable stability detection between commands',
    default: false
  })
  .option('stability-wait', {
    type: 'number',
    description: 'Seconds to wait for stability',
    default: 3
  })
  .option('stability-sensitivity', {
    type: 'number',
    description: 'Difference threshold for stability (0-1)',
    default: 0.33
  })
  .option('stability-timeout', {
    type: 'number',
    description: 'Maximum seconds to wait for stability',
    default: 60
  })
  .option('stability-interval', {
    type: 'number',
    description: 'Milliseconds between stability checks (frames will be waitTime/interval)',
    default: 500
  })
  .option('session-id', {
    type: 'string',
    description: 'Session ID to use (for re-runs)',
    alias: 'sid'
  })
  // .option('cpu', {
  //   type: 'number',
  //   description: 'CPU cores available',
  //   default: 1
  // })
  // .option('mem', {
  //   type: 'number',
  //   description: 'Memory available in GB',
  //   default: 1
  // })
  .argv;

// Add debug logging for showOverlay
// console.log('\n[DEBUG] Command line arguments:');
// console.log('--show-overlay value:', argv.showOverlay);
// console.log('argv object:', JSON.stringify({
//   showOverlay: argv.showOverlay,
//   clientId: argv.clientId,
//   testId: argv.testId
// }, null, 2));

// After parsing argv
global.argv = argv;

// Add running state tracking at the top with other globals
let isRunning = false;

// Session state tracking
const sessionStates = new Map(); // Map of sessionKey -> state info

// Create a function to update running state
const updateRunningState = async (state) => {
  isRunning = state;
};

// mJPEG stream management
const frameEmitter = new EventEmitter();
frameEmitter.setMaxListeners(0); // Allow unlimited listeners
global.frameEmitter = frameEmitter; // Make it globally accessible
global.lastFrameBuffer = {}; // Store last frame for each session

// No Firebase hooks needed

async function executeBatchMode(session, url, commands) {
  try {
    // Initialize session (this will handle all Firebase state internally)
    await session.initialize(url)
      .then(initResult => {
        if (!initResult.success) {
          throw new Error('Failed to initialize session');
        }
      });

    // Execute commands in sequence (PlaywrightSession handles all Firebase logging)
    const results = [];
    for (const command of commands) {
      const result = await session.executeCommand(command);
      results.push(result);

      if (!result.success) {
        break;
      }
    }

    // End session (this handles all Firebase cleanup)
    const endResult = await session.end();

    return {
      success: true,
      results,
      endResult
    };
  } catch (error) {
    return {
      success: false,
      error: error.message || 'Unknown error in batch execution'
    };
  }
}

// Collect system metadata
const getSystemMetadata = () => {
  const cpus = os.cpus();
  return {
    'system-meta': {
      totalMemoryGB: Math.round(os.totalmem() / (1024 * 1024 * 1024)), // Convert bytes to GB
      cpuCount: cpus.length,
      cpuModel: cpus[0].model,
      platform: os.platform(),
      arch: os.arch(),
      hostname: os.hostname(),
      release: os.release()
    }
  };
};

// Add system metadata to argv
argv.systemMeta = getSystemMetadata();

async function main() {
  // Generate timestamp-based session ID
  const sessionTimestamp = argv.sessionId || new Date().toISOString().replace(/[:.]/g, '-');

    // Initialize logger
    const logger = new SimpleLogger(argv.clientId, argv.testId, sessionTimestamp);
    logger.log('Express app created');

    // Create express app first
    const app = express();

    // Setup CORS for Flow Builder cross-port requests
    app.use((req, res, next) => {
      res.header('Access-Control-Allow-Origin', '*');
      res.header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
      res.header('Access-Control-Allow-Headers', 'Content-Type, Authorization');
      if (req.method === 'OPTIONS') {
        return res.sendStatus(200);
      }
      next();
    });

    // Serve static files from resources directory (public - login page needs themes)
    app.use('/resources', express.static(path.join(__dirname, '..', 'resources')));

    // --- Auth: login/logout routes (must be before authMiddleware) ---
    if (RABBITIZE_PASSWORD) {
      app.get('/login', (req, res) => {
        res.sendFile(path.join(__dirname, '..', 'resources', 'streaming', 'login.html'));
      });

      app.post('/api/login', express.json({ limit: '1mb' }), (req, res) => {
        const { password } = req.body || {};
        if (password === RABBITIZE_PASSWORD) {
          const token = crypto.randomBytes(32).toString('hex');
          validAuthTokens.add(token);
          res.setHeader('Set-Cookie', `rabbitize_auth=${token}; HttpOnly; Path=/; Max-Age=${24 * 60 * 60}; SameSite=Lax`);
          res.json({ success: true });
        } else {
          res.status(401).json({ success: false, error: 'Invalid password' });
        }
      });

      app.post('/api/logout', (req, res) => {
        const cookies = parseCookies(req.headers.cookie);
        if (cookies.rabbitize_auth) validAuthTokens.delete(cookies.rabbitize_auth);
        res.setHeader('Set-Cookie', 'rabbitize_auth=; HttpOnly; Path=/; Max-Age=0; SameSite=Lax');
        res.redirect('/login');
      });
    }

    // --- Auth middleware: protects everything below this line ---
    app.use(authMiddleware);

    // Serve video files from rabbitize-runs directory (protected)
    app.use('/rabbitize-runs', express.static(path.join(process.cwd(), 'rabbitize-runs')));

    // HTTP proxy for spawned Flow Builder child sessions.
    // Routes browser requests through the main port so child ports don't need to be exposed
    // in Docker / AWS (only port 3037 needs to be open).
    app.all('/proxy/:proxySessionId/*', (req, res) => {
      const { proxySessionId } = req.params;
      const subPath = req.params[0] || '';
      const qs = req.originalUrl.includes('?') ? req.originalUrl.split('?').slice(1).join('?') : '';
      const childPath = `/${subPath}${qs ? '?' + qs : ''}`;

      if (!global.spawnedSessions || !global.spawnedSessions.has(proxySessionId)) {
        return res.status(404).json({ error: 'Session not found or no longer active' });
      }

      const { port: childPort } = global.spawnedSessions.get(proxySessionId);
      const proxyHeaders = { host: `127.0.0.1:${childPort}` };
      if (req.headers['content-type']) proxyHeaders['content-type'] = req.headers['content-type'];
      if (req.headers['content-length']) proxyHeaders['content-length'] = req.headers['content-length'];

      const proxyReq = require('http').request(
        { hostname: '127.0.0.1', port: childPort, path: childPath, method: req.method, headers: proxyHeaders },
        (proxyRes) => {
          res.writeHead(proxyRes.statusCode, proxyRes.headers);
          proxyRes.pipe(res, { end: true });
        }
      );

      proxyReq.on('error', () => {
        if (!res.headersSent) res.status(502).json({ error: 'Child session unavailable' });
        else res.end();
      });

      req.on('aborted', () => proxyReq.destroy());

      if (req.method === 'GET' || req.method === 'HEAD') {
        proxyReq.end();
        return;
      }

      req.pipe(proxyReq);
    });

    let server;

    // Setup all middleware and routes
    app.use((req, res, next) => {
      // Skip logging for status endpoint
      if (req.url === '/status') {
        return next();
      }

      const requestId = Math.random().toString(36).substring(7);
      req.requestId = requestId;
      logger.log(`[${requestId}] - ${req.method} ${req.url} - Starting`);
      res.on('finish', () => {
        logger.log(`[${requestId}] - ${req.method} ${req.url} - Completed`);
      });
      next();
    });

    app.use(express.json({
      limit: '50mb',
      strict: false,
      type: ['application/json', 'text/plain']
    }));

    // Error handler for JSON parsing
    app.use((err, req, res, next) => {
      if (err instanceof SyntaxError && err.status === 400 && 'body' in err) {
        logger.warn('Received malformed JSON:', err.message);
        return res.status(400).json({
          error: 'Invalid JSON format',
          details: err.message
        });
      }
      if (err && err.type === 'entity.too.large') {
        logger.warn('Received oversized JSON payload:', err.message);
        return res.status(413).json({
          error: 'Request payload too large',
          details: 'JSON body exceeds 50MB limit'
        });
      }
      next(err);
    });

    // Reference existing routes from test/server.test.js
    // Spawn isolated session for Flow Builder - using same approach as re-runs
    app.post('/spawn-session', async (req, res) => {
      try {
        const { url, clientId, testId } = req.body;

        if (!url || !clientId || !testId) {
          return res.status(400).json({
            success: false,
            error: 'URL, clientId, and testId are required'
          });
        }

        // Find an available port
        const newPort = await findAvailablePort(argv.port + 1000);
        logger.log(`Allocated port ${newPort} for Flow Builder session`);

        // Generate session ID in same format as regular sessions
        const sessionId = new Date().toISOString().replace(/[:.]/g, '-');

        // For Flow Builder, we don't need persistent logs, but we'll create minimal structure
        const logsDir = path.join(os.tmpdir(), 'rabbitize-flow-builder', sessionId);
        await fsPromises.mkdir(logsDir, { recursive: true });

        const stdoutPath = path.join(logsDir, 'stdout.log');
        const stderrPath = path.join(logsDir, 'stderr.log');

        // Build the CLI command for a live interactive session
        const args = [
          path.join(__dirname, 'index.js'),
          '--client-id', clientId,
          '--test-id', testId,
          '--session-id', sessionId,
          '--port', String(newPort),
          '--hostname', argv.hostname || 'unknown',
          '--exit-on-end', 'true', // Exit when session ends
          // Flow Builder specific settings
          '--show-overlay', 'true',
          '--clip-segments', 'false',
          '--process-video', 'false',
          '--live-screenshots', 'true',
          '--stability-detection', 'false'
        ];

        logger.log(`Starting Flow Builder session for ${clientId}/${testId} on port ${newPort}`);

        // Open log files for writing
        const stdoutStream = fs.createWriteStream(stdoutPath);
        const stderrStream = fs.createWriteStream(stderrPath);

        // Spawn the process in detached mode with piped output - EXACTLY like re-runs
        const child = execFile('node', args, {
          detached: true,
          stdio: ['ignore', 'pipe', 'pipe'],
          env: {
            ...process.env,
            FORCE_COLOR: '1',
            TERM: 'xterm-256color',
            CI: 'false',
            NO_COLOR: undefined,
            // Child sessions run on internal ports proxied through the main server.
            // They don't need auth since the proxy is already behind auth.
            RABBITIZE_PASSWORD: ''
          }
        });

        // Pipe output to files
        child.stdout.pipe(stdoutStream);
        child.stderr.pipe(stderrStream);

        // Also log to console for debugging (can remove later)
        child.stdout.on('data', (data) => {
          logger.log(`[FLOW-BUILDER ${newPort}]:`, data.toString().trim());
        });

        child.stderr.on('data', (data) => {
          logger.error(`[FLOW-BUILDER ${newPort} ERR]:`, data.toString().trim());
        });

        // Unref the child so our process can exit independently
        child.unref();

        // Store process info for tracking
        if (!global.spawnedSessions) {
          global.spawnedSessions = new Map();
        }
        global.spawnedSessions.set(sessionId, {
          pid: child.pid,
          port: newPort,
          clientId,
          testId,
          sessionId,
          startTime: Date.now(),
          process: child,
          logsDir
        });

        // Track when process exits
        child.on('exit', (code) => {
          logger.log(`[FLOW-BUILDER ${newPort}] Process exited with code ${code}`);
          global.spawnedSessions.delete(sessionId);
          // Clean up temp logs
          fsPromises.rm(logsDir, { recursive: true, force: true }).catch(() => {});
        });

        // Wait for the spawned process to be ready
        try {
          logger.log(`Waiting for Flow Builder process to be ready on port ${newPort}...`);
          await waitForPort(newPort, 15000);
          logger.log(`Flow Builder process is ready on port ${newPort}`);
        } catch (error) {
          logger.error(`Failed to start Flow Builder process on port ${newPort}:`, error);
          // Try to kill the spawned process
          try {
            process.kill(child.pid, 'SIGKILL');
          } catch (e) {}
          throw new Error(`Flow Builder process failed to start: ${error.message}`);
        }

        res.json({
          success: true,
          sessionId: sessionId,
          port: newPort,
          clientId: clientId,
          testId: testId,
          message: 'Spawned Flow Builder session successfully'
        });

      } catch (error) {
        logger.error('Failed to spawn Flow Builder session:', error);
        res.status(500).json({
          success: false,
          error: error.message
        });
      }
    });

    // Kill spawned session
    app.post('/kill-session/:sessionId', (req, res) => {
      const { sessionId } = req.params;

      if (!global.spawnedSessions || !global.spawnedSessions.has(sessionId)) {
        return res.status(404).json({
          success: false,
          error: 'Session not found'
        });
      }

      const session = global.spawnedSessions.get(sessionId);

      try {
        // Kill the process (not process group since we're on different platforms)
        process.kill(session.process.pid, 'SIGTERM');
        global.spawnedSessions.delete(sessionId);

        res.json({
          success: true,
          message: 'Session killed successfully'
        });
      } catch (error) {
        logger.error('Failed to kill session:', error);
        // Try SIGKILL if SIGTERM failed
        try {
          process.kill(session.process.pid, 'SIGKILL');
        } catch (e) {
          // Process might already be dead
        }
        res.status(500).json({
          success: false,
          error: error.message
        });
      }
    });

    app.post('/start', async (req, res) => {
      const { url, command, clientId, testId, sessionId } = req.body;
      if (!url) {
        return res.status(400).json({ error: 'URL is required' });
      }

      // Use provided clientId/testId or fall back to argv values
      const actualClientId = clientId || argv.clientId;
      const actualTestId = testId || argv.testId;

      try {
        // Create fresh session instance with timestamp
        const sessionTimestamp = sessionId || argv.sessionId || new Date().toISOString().replace(/[:.]/g, '-');

        // Create new logger with sessionTimestamp
        const sessionLogger = new SimpleLogger(actualClientId, actualTestId, sessionTimestamp);

        // Create session with the logger instance
        const session = new PlaywrightSession(sessionTimestamp, '', {
          showCommandOverlay: argv.showOverlay,
          createClipSegments: argv.clipSegments,
          firebase: sessionLogger,  // Keep the property name for compatibility
          clientId: actualClientId,
          testId: actualTestId,
          //sessionId: sessionTimestamp,
          enableLiveScreenshots: argv.liveScreenshots
        });

        // Set new session in queue manager
        queueManager.setSession(session);

        // Initialize session
        const result = await session.initialize(url);
        if (!result.success) {
          throw new Error('Failed to initialize session');
        }

        // Start the queue processor after successful initialization
        queueManager.startProcessing();

        // Track session state using the ACTUAL sessionId from the session
        const actualSessionId = session.sessionId;
        const sessionKey = `${actualClientId}/${actualTestId}/${actualSessionId}`;
        sessionStates.set(sessionKey, {
          clientId: actualClientId,
          testId: actualTestId,
          sessionId: actualSessionId,
          status: 'active',
          startTime: Date.now(),
          commandCount: 0,
          phase: 'initializing',
          initialUrl: url
        });

        // Log streaming endpoints when session starts
        const serverHost = os.hostname();
        logger.log(chalk.bold.cyan('\n📹 Live Stream Available:'));
        logger.log(chalk.cyan(`  Direct: http://${serverHost}:${argv.port}/stream/${actualClientId}/${actualTestId}/${actualSessionId}`));
        logger.log(chalk.cyan(`  Viewer: http://${serverHost}:${argv.port}/stream-viewer/${actualClientId}/${actualTestId}/${actualSessionId}`));
        logger.log(chalk.cyan(`  All Sessions: http://${serverHost}:${argv.port}/streaming`));

        // If a command was provided, queue it after initialization
        if (command) {
          if (!Array.isArray(command)) {
            throw new Error('Command must be an array');
          }
          const typedCommand = normalizeCommandTypes(command);
          queueManager.enqueue('execute', { command: typedCommand });
        }

        res.json({
          success: true,
          message: command ? 'Session started and command queued' : 'Session started successfully',
          clientId: actualClientId,
          testId: actualTestId,
          sessionId: actualSessionId
        });
      } catch (error) {
        res.status(500).json({
          success: false,
          error: error.message
        });
      }
    });

    app.post('/execute', async (req, res) => {
      try {
        const { command } = req.body;
        if (!command || !Array.isArray(command)) {
          return res.status(400).json({
            error: 'Invalid command format',
            details: 'Command must be an array'
          });
        }

        const typedCommand = normalizeCommandTypes(command);

        // Don't await, just queue and respond
        queueManager.enqueue('execute', { command: typedCommand });
        res.json({
          success: true,
          message: 'Execute command queued'
        });
      } catch (error) {
        res.status(500).json({ error: error.message });
      }
    });

    app.post('/execute-batch', async (req, res) => {
      try {
        const { commands } = req.body;
        if (!commands || !Array.isArray(commands)) {
          return res.status(400).json({
            error: 'Invalid commands format',
            details: 'Commands must be an array of command arrays'
          });
        }

        // Validate each command in the batch
        for (const command of commands) {
          if (!Array.isArray(command)) {
            return res.status(400).json({
              error: 'Invalid command format',
              details: 'Each command must be an array'
            });
          }
        }

        logger.log('Received batch of', commands.length, 'commands');

        // Queue each command in sequence
        for (const command of commands) {
          const typedCommand = normalizeCommandTypes(command);

          // Queue the command
          queueManager.enqueue('execute', { command: typedCommand });
        }

        res.json({
          success: true,
          message: `Queued ${commands.length} commands for execution`,
          queuedCommands: commands.length
        });

      } catch (error) {
        logger.error('Execute batch error:', error);
        res.status(500).json({
          success: false,
          error: error.message
        });
      }
    });

    app.post('/end', async (req, res) => {
      const { bootstrap } = req.body;

      if (bootstrap) {
        // Handle both formats for backward compatibility
        let bootstrapData = bootstrap;

        // If bootstrap is just an array, assume it's commands and use default URL
        if (Array.isArray(bootstrap)) {
          bootstrapData = {
            url: global.currentPlaywrightSession?.initialUrl || 'about:blank',
            commands: bootstrap
          };
        }

        // Validate bootstrap data
        if (!bootstrapData.url) {
          return res.status(400).json({
            success: false,
            error: 'Bootstrap URL is required'
          });
        }

        // Queue the end command first
        queueManager.enqueue('end', { quickCleanup: true });

        // Queue the new session start
        queueManager.enqueue('start', {
          url: bootstrapData.url,
          isBootstrap: true
        });

        // Queue the commands
        if (bootstrapData.commands && Array.isArray(bootstrapData.commands)) {
          for (const command of bootstrapData.commands) {
            queueManager.enqueue('execute', {
              command,
              isBootstrap: true
            });
          }
        }

        logger.log('Queued bootstrap session with', bootstrapData.commands?.length || 0, 'commands');
      } else {
        queueManager.enqueue('end', { quickCleanup: false });
      }

      res.json({
        success: true,
        message: bootstrap ? 'End and bootstrap commands queued' : 'End command queued'
      });
    });

    app.post('/feedback', async (req, res) => {
      try {
        const { client_id, test_id, session_id, payload, operator } = req.body;
        
        // Validate required fields
        if (!client_id || !test_id || !session_id) {
          return res.status(400).json({
            success: false,
            error: 'client_id, test_id, and session_id are required'
          });
        }
        
        // Validate payload exists
        if (!payload) {
          return res.status(400).json({
            success: false,
            error: 'payload is required'
          });
        }
        
        // Determine filename based on operator or use default
        let filename = 'feedback_loop.json';
        if (operator && typeof operator === 'string') {
          // Sanitize operator to be a valid filename
          const sanitizedOperator = operator.replace(/[^a-zA-Z0-9_-]/g, '_').toLowerCase();
          filename = `feedback_${sanitizedOperator}.json`;
        }
        
        // Construct path to feedback file
        const feedbackPath = path.join(
          process.cwd(), 
          'rabbitize-runs', 
          client_id, 
          test_id, 
          session_id, 
          filename
        );
        
        // Create feedback entry with timestamp
        const feedbackEntry = {
          timestamp: new Date().toISOString(),
          payload: payload
        };
        
        try {
          // Ensure directory exists
          const dir = path.dirname(feedbackPath);
          await fsPromises.mkdir(dir, { recursive: true });
          
          // Read existing feedback array or create new one
          let feedbackArray = [];
          try {
            const existingData = await fsPromises.readFile(feedbackPath, 'utf8');
            feedbackArray = JSON.parse(existingData);
            if (!Array.isArray(feedbackArray)) {
              feedbackArray = [feedbackArray]; // Convert to array if it wasn't
            }
          } catch (err) {
            // File doesn't exist or is invalid, start with empty array
            feedbackArray = [];
          }
          
          // Append new feedback
          feedbackArray.push(feedbackEntry);
          
          // Write back to file
          await fsPromises.writeFile(
            feedbackPath, 
            JSON.stringify(feedbackArray, null, 2),
            'utf8'
          );
          
          logger.log(`Feedback appended to ${filename} for ${client_id}/${test_id}/${session_id}`);
          
          res.json({
            success: true,
            message: 'Feedback recorded successfully',
            timestamp: feedbackEntry.timestamp
          });
          
        } catch (fileError) {
          logger.error('Failed to write feedback:', fileError);
          res.status(500).json({
            success: false,
            error: 'Failed to write feedback to file'
          });
        }
        
      } catch (error) {
        logger.error('Feedback endpoint error:', error);
        res.status(500).json({
          success: false,
          error: error.message
        });
      }
    });

    app.get('/status', async (req, res) => {
      const status = queueManager.getStatus();
      status.heartbeat = Date.now();
      status.hasSession = isRunning;
      status.pid = process.pid;

      // Update Firebase with status
      try {
        const statusUpdate = { ...status.currentState };
        if (statusUpdate.firebasePhase === undefined) {
          delete statusUpdate.firebasePhase;
        }
        statusUpdate.heartbeat = status.heartbeat;
        statusUpdate.hasSession = isRunning;
        statusUpdate.pid = process.pid;
        statusUpdate.options = {
          clientId: argv.clientId,
          testId: argv.testId,
          hostname: argv.hostname,
          port: argv.port,
          showOverlay: argv.showOverlay,
          clipSegments: argv.clipSegments,
          processVideo: argv.processVideo,
          exitOnEnd: argv.exitOnEnd
        };

        // Add system-meta if it exists
        if (argv.systemMeta && Object.keys(argv.systemMeta).length > 0) {
          statusUpdate.options['system-meta'] = argv.systemMeta;
        }

        // Worker status updates removed (no Firebase)
      } catch (error) {
        logger.warn('Worker status update skipped (local mode)');
      }

      res.json(status);
    });

    // mJPEG streaming endpoint
    // - Each connection is completely independent
    // - No connection pooling or limiting
    // - Unique connection IDs (cid param) prevent browser connection reuse
    // - Keepalive frames prevent timeout on idle streams
    // - Non-blocking writes handle slow clients gracefully
    app.get('/stream/:clientId/:testId/:sessionId', (req, res) => {
      const { clientId, testId, sessionId } = req.params;
      const sessionKey = `${clientId}/${testId}/${sessionId}`;

      // Log connection with unique identifier
      const connectionId = req.query.cid || `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
      logger.debug(`Stream connection opened: ${sessionKey} (cid: ${connectionId})`);

      // Set up mJPEG headers with additional headers to prevent caching/pooling
      res.writeHead(200, {
        'Content-Type': 'multipart/x-mixed-replace; boundary=frame',
        'Cache-Control': 'no-cache, no-store, must-revalidate, private',
        'Pragma': 'no-cache',
        'Expires': '0',
        'Connection': 'keep-alive',
        'X-Content-Type-Options': 'nosniff',
        'X-Connection-Id': connectionId
      });

      // Disable Nagle's algorithm for real-time streaming
      res.socket.setNoDelay(true);

      // Set socket keepalive to detect dead connections
      res.socket.setKeepAlive(true, 10000);

      // Track connection state
      let isConnected = true;
      let lastFrameTime = Date.now();

      // Create frame listener for this specific response
      const frameListener = (data) => {
        if (data.sessionKey === sessionKey && isConnected && !res.destroyed) {
          try {
            // Non-blocking write with error handling
            const frameData = Buffer.concat([
              Buffer.from(`--frame\r\n`),
              Buffer.from(`Content-Type: image/jpeg\r\n`),
              Buffer.from(`Content-Length: ${data.buffer.length}\r\n\r\n`),
              data.buffer,
              Buffer.from('\r\n')
            ]);

            // Write with callback to handle backpressure
            res.write(frameData, (err) => {
              if (err) {
                logger.debug(`Stream write error for ${connectionId}: ${err.message}`);
                cleanup();
              } else {
                lastFrameTime = Date.now();
              }
            });
          } catch (error) {
            logger.debug(`Stream error for ${connectionId}: ${error.message}`);
            cleanup();
          }
        }
      };

      // Cleanup function
      const cleanup = () => {
        if (isConnected) {
          isConnected = false;
          frameEmitter.removeListener('frame', frameListener);
          clearInterval(keepAliveInterval);
          logger.debug(`Stream connection closed: ${sessionKey} (cid: ${connectionId})`);
        }
      };

      // Send keepalive frames if no data for 30 seconds
      const keepAliveInterval = setInterval(() => {
        if (Date.now() - lastFrameTime > 30000 && isConnected) {
          try {
            // Send an empty frame as keepalive
            res.write(`--frame\r\n`);
            res.write(`Content-Type: text/plain\r\n`);
            res.write(`Content-Length: 0\r\n\r\n`);
            res.write('\r\n');
          } catch (error) {
            cleanup();
          }
        }
      }, 10000);

      // Send last frame if available
      if (global.lastFrameBuffer && global.lastFrameBuffer[sessionKey]) {
        try {
          const buffer = global.lastFrameBuffer[sessionKey];
          const initialFrame = Buffer.concat([
            Buffer.from(`--frame\r\n`),
            Buffer.from(`Content-Type: image/jpeg\r\n`),
            Buffer.from(`Content-Length: ${buffer.length}\r\n\r\n`),
            buffer,
            Buffer.from('\r\n')
          ]);

          res.write(initialFrame, (err) => {
            if (err) {
              logger.debug(`Initial frame write error for ${connectionId}: ${err.message}`);
            } else {
              lastFrameTime = Date.now();
            }
          });
        } catch (error) {
          // Ignore initial frame errors
        }
      }

      // Listen for frames
      frameEmitter.on('frame', frameListener);

      // Clean up on disconnect
      req.on('close', cleanup);
      req.on('error', cleanup);
      res.on('close', cleanup);
      res.on('error', cleanup);
      res.socket.on('error', cleanup);
    });

    // Function to scan filesystem for historical sessions
    async function scanHistoricalSessions() {
      const historicalSessions = [];
      const runsDir = path.join(process.cwd(), 'rabbitize-runs');

      try {
        if (!fs.existsSync(runsDir)) {
          return historicalSessions;
        }

        // Scan all client directories
        const clientDirs = await fsPromises.readdir(runsDir);

        for (const clientId of clientDirs) {
          const clientPath = path.join(runsDir, clientId);
          const clientStat = await fsPromises.stat(clientPath);

          if (!clientStat.isDirectory()) continue;

          // Scan all test directories
          const testDirs = await fsPromises.readdir(clientPath);

          for (const testId of testDirs) {
            const testPath = path.join(clientPath, testId);
            const testStat = await fsPromises.stat(testPath);

            if (!testStat.isDirectory()) continue;

            // Scan all session directories
            const sessionDirs = await fsPromises.readdir(testPath);

            for (const sessionId of sessionDirs) {
              const sessionPath = path.join(testPath, sessionId);
              const sessionStat = await fsPromises.stat(sessionPath);

              if (!sessionStat.isDirectory()) continue;

              // Check for status.json file first (for external processes)
              const statusPath = path.join(sessionPath, 'status.json');
              const metadataPath = path.join(sessionPath, 'session-metadata.json');

              let sessionData = null;

              // Try status.json first (most up-to-date for external processes)
              if (fs.existsSync(statusPath)) {
                try {
                  const status = JSON.parse(await fsPromises.readFile(statusPath, 'utf8'));

                  // Check if this is a stale process (no update in 5 minutes)
                  const isStale = (Date.now() - status.lastUpdate) > 5 * 60 * 1000;

                  sessionData = {
                    clientId: status.clientId || clientId,
                    testId: status.testId || testId,
                    sessionId: status.sessionId || sessionId,
                    status: isStale ? 'finished' : status.status,
                    startTime: status.startTime,
                    endTime: status.status === 'finished' ? status.lastUpdate : null,
                    duration: status.status === 'finished' ? (status.lastUpdate - status.startTime) : null,
                    commandCount: status.commandCount,
                    commandsExecuted: status.commandsExecuted,
                    totalCommands: status.totalCommands || 0,
                    phase: status.phase,
                    currentCommand: status.currentCommand,
                    pid: status.pid,
                    hostname: status.hostname,
                    videoProcessing: status.videoProcessing,
                    hasVideo: fs.existsSync(path.join(sessionPath, 'video', 'session.webm')),
                    hasScreenshots: fs.existsSync(path.join(sessionPath, 'screenshots')),
                    initialUrl: status.initialUrl || '',
                    timestamp: new Date(status.lastUpdate).toISOString(),
                    isExternal: true,
                    isStale: isStale,
                    port: status.port || null
                  };

                  // Debug logging for external sessions
                  // if (status.port) {
                  //   logger.log(`Found external session ${sessionId} on port ${status.port}`);
                  // }
                } catch (error) {
                  logger.warn('Failed to parse status.json:', error);
                }
              }

              // Fall back to metadata file if no status.json or parsing failed
              if (!sessionData && fs.existsSync(metadataPath)) {
                try {
                  const metadata = JSON.parse(await fsPromises.readFile(metadataPath, 'utf8'));
                  sessionData = metadata;
                } catch (error) {
                  logger.warn('Failed to parse session-metadata.json:', error);
                }
              }

              // If still no data, create basic info from directory
              if (!sessionData) {
                sessionData = {
                  clientId,
                  testId,
                  sessionId,
                  status: 'finished',
                  startTime: sessionStat.ctimeMs,
                  endTime: sessionStat.mtimeMs,
                  duration: sessionStat.mtimeMs - sessionStat.ctimeMs,
                  commandCount: 0,
                  phase: 'legacy',
                  hasVideo: fs.existsSync(path.join(sessionPath, 'video', 'session.webm')),
                  hasScreenshots: fs.existsSync(path.join(sessionPath, 'screenshots')),
                  initialUrl: '',
                  timestamp: new Date(sessionStat.mtime).toISOString()
                };
              }

              historicalSessions.push(sessionData);
            }
          }
        }
      } catch (error) {
        logger.error('Error scanning historical sessions:', error);
      }

      return historicalSessions;
    }

    // API endpoint for session details (zoom images, commands, etc.)
    app.get('/api/session/:clientId/:testId/:sessionId', async (req, res) => {
      const { clientId, testId, sessionId } = req.params;
      const sessionPath = path.join(process.cwd(), 'rabbitize-runs', clientId, testId, sessionId);

      try {
        const details = {
          clientId,
          testId,
          sessionId,
          zoomImages: [],
          commands: [],
          hasCommands: false,
          sessionPath: `/rabbitize-runs/${clientId}/${testId}/${sessionId}`,
          isActive: false,
          commandsExecuted: 0,
          totalCommands: 0
        };

        // Check if this is an external/active session by reading status.json
        let maxCommandIndex = Infinity; // Default to showing all images
        const statusPath = path.join(sessionPath, 'status.json');
        if (fs.existsSync(statusPath)) {
          try {
            const status = JSON.parse(await fsPromises.readFile(statusPath, 'utf8'));
            // If session is active, only show zoom images up to current command
            if (status.status === 'active') {
              maxCommandIndex = status.commandsExecuted || 0;
              details.isActive = true;
              details.commandsExecuted = status.commandsExecuted || 0;
              details.totalCommands = status.totalCommands || status.commandCount || 0;
            }
          } catch (error) {
            logger.warn('Failed to read status.json for zoom limit:', error);
          }
        }

        // Check for zoom images
        const screenshotsPath = path.join(sessionPath, 'screenshots');
        if (fs.existsSync(screenshotsPath)) {
          const files = await fsPromises.readdir(screenshotsPath);
          const zoomFiles = files
            .filter(f => f.endsWith('_zoom.jpg'))
            .sort((a, b) => {
              const numA = parseInt(a.split('_')[0]);
              const numB = parseInt(b.split('_')[0]);
              return numA - numB;
            })
            .filter(f => {
              // Only include zoom images up to the current command index
              const index = parseInt(f.split('_')[0]);
              return index < maxCommandIndex;
            });

          details.zoomImages = zoomFiles.map(f => ({
            filename: f,
            url: `/rabbitize-runs/${clientId}/${testId}/${sessionId}/screenshots/${f}`,
            index: parseInt(f.split('_')[0])
          }));
        }

        // Check for commands.json
        const commandsPath = path.join(sessionPath, 'commands.json');
        if (fs.existsSync(commandsPath)) {
          try {
            const commandsData = JSON.parse(await fsPromises.readFile(commandsPath, 'utf8'));
            details.commands = commandsData.map(item => item.command);
            details.hasCommands = true;

            // Extract timing data for visualization
            details.timingData = commandsData
              .slice(0, maxCommandIndex) // Only include executed commands
              .map((item, index) => ({
                index,
                command: item.command[0], // First element is command type
                duration: item.output?.timing?.duration || 0,
                start: item.output?.timing?.start || 0,
                end: item.output?.timing?.end || 0
              }));

            // Calculate total duration and gaps
            if (details.timingData.length > 0) {
              const firstStart = details.timingData[0].start;
              const lastEnd = details.timingData[details.timingData.length - 1].end;
              details.totalDuration = lastEnd - firstStart;

              // Add gap information
              details.timingData = details.timingData.map((item, index) => {
                if (index > 0) {
                  const prevEnd = details.timingData[index - 1].end;
                  item.gapBefore = item.start - prevEnd;
                } else {
                  item.gapBefore = 0;
                }
                item.relativeStart = item.start - firstStart;
                return item;
              });
            }

            // Get initial URL from metadata or first navigate command
            const metadataPath = path.join(sessionPath, 'session-metadata.json');
            if (fs.existsSync(metadataPath)) {
              const metadata = JSON.parse(await fsPromises.readFile(metadataPath, 'utf8'));
              details.initialUrl = metadata.initialUrl;
            }

            // If no URL in metadata, check if first command is navigate
            if (!details.initialUrl && commandsData.length > 0) {
              const firstCommand = commandsData[0].command;
              if (firstCommand && firstCommand[0] === ':navigate' && firstCommand[1]) {
                details.initialUrl = firstCommand[1];
              }
            }
          } catch (error) {
            logger.warn('Failed to parse commands.json:', error);
          }
        }

        res.json(details);
      } catch (error) {
        logger.error('Error getting session details:', error);
        res.status(500).json({ error: 'Failed to get session details' });
      }
    });

    // API endpoint for individual step details
    app.get('/api/session/:clientId/:testId/:sessionId/step/:stepIndex', async (req, res) => {
      const { clientId, testId, sessionId, stepIndex } = req.params;
      const sessionPath = path.join(process.cwd(), 'rabbitize-runs', clientId, testId, sessionId);
      const index = parseInt(stepIndex);

      try {
        const stepDetails = {
          index,
          screenshots: {},
          command: null,
          metrics: {},
          dom: null,
          videoClip: null
        };

        // Get command data
        const commandsPath = path.join(sessionPath, 'commands.json');
        if (fs.existsSync(commandsPath)) {
          const commands = JSON.parse(await fsPromises.readFile(commandsPath, 'utf8'));
          if (commands[index]) {
            const cmd = commands[index];
            stepDetails.command = cmd.command;
            stepDetails.timing = cmd.output?.timing;
            stepDetails.metrics = cmd.output?.metrics;
            stepDetails.success = cmd.output?.success;

            // Extract command name for screenshots
            const commandName = cmd.command[0].replace(':', '');

            // Check for screenshots
            const screenshotsPath = path.join(sessionPath, 'screenshots');
            const preScreenshot = `${index}-pre-${commandName}.jpg`;
            const postScreenshot = `${index}-post-${commandName}.jpg`;

            if (fs.existsSync(path.join(screenshotsPath, preScreenshot))) {
              stepDetails.screenshots.pre = `/rabbitize-runs/${clientId}/${testId}/${sessionId}/screenshots/${preScreenshot}`;
            }
            if (fs.existsSync(path.join(screenshotsPath, postScreenshot))) {
              stepDetails.screenshots.post = `/rabbitize-runs/${clientId}/${testId}/${sessionId}/screenshots/${postScreenshot}`;
            }

            // Get DOM snapshot
            const domPath = path.join(sessionPath, 'dom_snapshots', `dom_${index}.md`);
            if (fs.existsSync(domPath)) {
              stepDetails.dom = await fsPromises.readFile(domPath, 'utf8');
            }

            // Check for video clip
            const videoClipPath = path.join(sessionPath, 'video', 'command_videos', `command_${index}.mp4`);
            if (fs.existsSync(videoClipPath)) {
              stepDetails.videoClip = `/rabbitize-runs/${clientId}/${testId}/${sessionId}/video/command_videos/command_${index}.mp4`;
            }
          }
        }

        res.json(stepDetails);
      } catch (error) {
        logger.error('Error getting step details:', error);
        res.status(500).json({ error: 'Failed to get step details' });
      }
    });

    // API endpoint for session status data
    app.get('/api/sessions', async (req, res) => {
      const sessions = [];

      // Get active sessions from memory
      for (const [sessionKey, sessionData] of sessionStates) {
        // Get real-time command count for active session
        const realtimeCommandCount = (sessionData.status === 'active' &&
                                     global.currentPlaywrightSession &&
                                     global.currentPlaywrightSession.sessionId === sessionData.sessionId) ?
                                     global.currentPlaywrightSession.commandCounter || 0 :
                                     sessionData.commandCount;

        sessions.push({
          ...sessionData,
          commandCount: realtimeCommandCount,
          totalCommands: (sessionData.status === 'active' &&
                         global.currentPlaywrightSession &&
                         global.currentPlaywrightSession.sessionId === sessionData.sessionId) ?
                         global.currentPlaywrightSession.totalCommands || sessionData.totalCommands || 0 :
                         sessionData.totalCommands || 0,
          phase: (sessionData.status === 'active' &&
                 global.currentPlaywrightSession &&
                 global.currentPlaywrightSession.sessionId === sessionData.sessionId) ?
                 global.currentPlaywrightSession.currentPhase || sessionData.phase :
                 sessionData.phase
        });
      }

      // Get historical sessions from filesystem
      const historicalSessions = await scanHistoricalSessions();

      // Merge historical sessions (avoid duplicates)
      const sessionIds = new Set(sessions.map(s => `${s.clientId}/${s.testId}/${s.sessionId}`));

      for (const historical of historicalSessions) {
        const key = `${historical.clientId}/${historical.testId}/${historical.sessionId}`;
        if (!sessionIds.has(key)) {
          sessions.push(historical);
        }
      }

      // Sort by start time (newest first)
      sessions.sort((a, b) => b.startTime - a.startTime);
      res.json(sessions);
    });

    // API endpoint to get latest feedback data for AI monologue
    app.get('/api/session/:clientId/:testId/:sessionId/feedback', async (req, res) => {
      try {
        const { clientId, testId, sessionId } = req.params;
        const operator = req.query.operator || 'actor';
        
        // Construct path to feedback file
        const feedbackPath = path.join(
          process.cwd(),
          'rabbitize-runs',
          clientId,
          testId,
          sessionId,
          `feedback_${operator}.json`
        );
        
        // Check if file exists
        if (!fs.existsSync(feedbackPath)) {
          return res.json({
            exists: false,
            latestUser: null,
            latestModel: null
          });
        }
        
        // Read and parse feedback file
        const feedbackData = JSON.parse(await fsPromises.readFile(feedbackPath, 'utf8'));
        
        // Split into user and model messages
        const userMessages = [];
        const modelMessages = [];
        
        feedbackData.forEach(entry => {
          if (entry.payload && entry.payload.event_type) {
            if (entry.payload.event_type === 'llm_current_user_message') {
              userMessages.push(entry);
            } else if (entry.payload.event_type === 'llm_model_response_message') {
              modelMessages.push(entry);
            }
          }
        });
        
        // Get the latest from each category
        const latestUser = userMessages.length > 0 ? userMessages[userMessages.length - 1] : null;
        const latestModel = modelMessages.length > 0 ? modelMessages[modelMessages.length - 1] : null;
        
        res.json({
          exists: true,
          latestUser,
          latestModel,
          totalUserMessages: userMessages.length,
          totalModelMessages: modelMessages.length
        });
        
      } catch (error) {
        logger.error('Error fetching feedback:', error);
        res.status(500).json({ error: 'Failed to fetch feedback data' });
      }
    });

    // API endpoint to re-run a session
    app.post('/api/rerun', async (req, res) => {
      logger.log('Received re-run request:', JSON.stringify(req.body));

      // Check if body exists
      if (!req.body) {
        logger.error('No request body received');
        return res.status(400).json({
          success: false,
          error: 'No request body received'
        });
      }

      const { clientId, testId, url, commands } = req.body;

      if (!clientId || !testId || !commands || !Array.isArray(commands)) {
        logger.error('Missing required parameters:', {
          clientId,
          testId,
          hasCommands: !!commands,
          isArray: Array.isArray(commands),
          body: req.body
        });
        return res.status(400).json({
          success: false,
          error: `Missing required parameters. Got: clientId=${clientId}, testId=${testId}, commands=${commands ? commands.length : 'none'}`
        });
      }

      try {
        // Find an available port for the new instance
        const net = require('net');
        const findAvailablePort = () => {
          return new Promise((resolve, reject) => {
            const server = net.createServer();
            server.listen(0, () => {
              const port = server.address().port;
              server.close(() => resolve(port));
            });
            server.on('error', reject);
          });
        };

        const newPort = await findAvailablePort();
        logger.log(`Allocated port ${newPort} for re-run instance`);

        // Generate a timestamp-based session ID (same format as regular sessions)
        const sessionId = new Date().toISOString().replace(/[:.]/g, '-');

        // Note: We don't create directories here anymore - let the child process handle it
        // This prevents empty folders with just logs

        // Create log file paths (these will be created when the child process starts)
        const logsDir = path.join(process.cwd(), 'rabbitize-runs', clientId, testId, sessionId, 'logs');
        const stdoutPath = path.join(logsDir, 'stdout.log');
        const stderrPath = path.join(logsDir, 'stderr.log');

        // Build the CLI command
        const args = [
          path.join(__dirname, 'index.js'),
          '--client-id', clientId,
          '--test-id', testId,
          '--session-id', sessionId,
          '--port', String(newPort),
          '--exit-on-end', 'true', // Always needed for re-runs
          '--batch-url', url || '',
          '--batch-commands', JSON.stringify(commands)
        ];

        // Copy ALL settings from current process
        // Always pass boolean options to preserve parent's settings (including when false)
        args.push('--show-overlay', String(argv.showOverlay));
        //args.push('--clip-segments', String(argv.clipSegments));
        args.push('--live-screenshots', String(argv.liveScreenshots));
        args.push('--process-video', String(argv.processVideo));
        args.push('--stability-detection', String(argv.stabilityDetection));
        if (argv.stabilityWait !== undefined) {
          args.push('--stability-wait', String(argv.stabilityWait));
        }
        if (argv.stabilitySensitivity !== undefined) {
          args.push('--stability-sensitivity', String(argv.stabilitySensitivity));
        }
        if (argv.stabilityTimeout !== undefined) {
          args.push('--stability-timeout', String(argv.stabilityTimeout));
        }
        if (argv.stabilityInterval !== undefined) {
          args.push('--stability-interval', String(argv.stabilityInterval));
        }

        logger.log(`Starting re-run for ${clientId}/${testId} with ${commands.length} commands`);

        // Log the EXACT command that will be executed
        const fullCommand = `node ${args.join(' ')}`;
        logger.log(`EXACT SPAWN COMMAND: ${fullCommand}`);

        // Also write the exact command to a file for debugging
        const commandLogPath = path.join(process.cwd(), 'rabbitize-runs', clientId, testId, sessionId, 'spawn-command.txt');

        // Create logs directory just before writing (to avoid empty folders if spawn fails)
        await fsPromises.mkdir(logsDir, { recursive: true });

        // Write the spawn command
        await fsPromises.writeFile(commandLogPath, fullCommand + '\n');

        // Open log files for writing
        const stdoutStream = fs.createWriteStream(stdoutPath);
        const stderrStream = fs.createWriteStream(stderrPath);

        // Spawn the process in detached mode with piped output
        const child = execFile('node', args, {
          detached: true,
          stdio: ['ignore', 'pipe', 'pipe'],
          env: {
            ...process.env,
            // Force color output for common tools
            FORCE_COLOR: '1',
            TERM: 'xterm-256color',
            CI: 'false', // Some tools disable colors in CI
            // Remove NO_COLOR if it exists
            NO_COLOR: undefined
          }
        });

        // Pipe output to files
        child.stdout.pipe(stdoutStream);
        child.stderr.pipe(stderrStream);

        // Unref the child so our process can exit independently
        child.unref();

        // Store process info for tracking
        const processInfo = {
          pid: child.pid,
          port: newPort,
          clientId,
          testId,
          sessionId,
          startTime: Date.now(),
          status: 'running',
          logsDir
        };

        // Update process tracking file
        const trackingPath = path.join(process.cwd(), 'rabbitize-runs', 'process-tracking.json');
        let tracking = { processes: [] };
        try {
          if (fs.existsSync(trackingPath)) {
            tracking = JSON.parse(await fsPromises.readFile(trackingPath, 'utf8'));
          }
        } catch (e) {
          logger.warn('Could not read process tracking file:', e);
        }

        // Add new process and clean up old entries
        tracking.processes = tracking.processes.filter(p => {
          // Remove entries older than 24 hours or with dead PIDs
          if (Date.now() - p.startTime > 24 * 60 * 60 * 1000) return false;
          try {
            process.kill(p.pid, 0); // Check if process exists
            return true;
          } catch (e) {
            return false;
          }
        });
        tracking.processes.push(processInfo);

        // Save tracking file
        await fsPromises.writeFile(trackingPath, JSON.stringify(tracking, null, 2));

        // Log the PID for tracking
        logger.log(`Re-run process started with PID: ${child.pid}`);

        res.json({
          success: true,
          pid: child.pid,
          port: newPort,
          sessionId,
          message: `Re-run started for ${clientId}/${testId} on port ${newPort}`
        });

      } catch (error) {
        logger.error('Failed to start re-run:', error);
        res.status(500).json({
          success: false,
          error: error.message
        });
      }
    });

    // API endpoint to get process tracking info
    app.get('/api/processes', async (req, res) => {
      try {
        const trackingPath = path.join(process.cwd(), 'rabbitize-runs', 'process-tracking.json');
        let tracking = { processes: [] };

        if (fs.existsSync(trackingPath)) {
          tracking = JSON.parse(await fsPromises.readFile(trackingPath, 'utf8'));

          // Update status and filter out dead processes
          tracking.processes = tracking.processes.filter(p => {
            try {
              process.kill(p.pid, 0); // Check if process exists
              return true;
            } catch (e) {
              p.status = 'terminated';
              return true; // Keep for display but mark as terminated
            }
          });

          // Check if processes have completed via status.json
          for (const proc of tracking.processes) {
            if (proc.status === 'running') {
              const statusPath = path.join(process.cwd(), 'rabbitize-runs', proc.clientId, proc.testId, proc.sessionId, 'status.json');
              if (fs.existsSync(statusPath)) {
                try {
                  const status = JSON.parse(await fsPromises.readFile(statusPath, 'utf8'));
                  if (status.status === 'finished' || status.phase === 'completed') {
                    proc.status = 'completed';
                  }
                } catch (e) {
                  // Ignore errors reading status
                }
              }
            }
          }
        }

        res.json(tracking);
      } catch (error) {
        logger.error('Error getting process tracking:', error);
        res.status(500).json({ error: 'Failed to get process tracking' });
      }
    });

    // API endpoint to get process logs
    app.get('/api/process/:pid/logs', async (req, res) => {
      try {
        const { pid } = req.params;
        const trackingPath = path.join(process.cwd(), 'rabbitize-runs', 'process-tracking.json');

        if (!fs.existsSync(trackingPath)) {
          return res.status(404).json({ error: 'Process tracking not found' });
        }

        const tracking = JSON.parse(await fsPromises.readFile(trackingPath, 'utf8'));
        const proc = tracking.processes.find(p => p.pid === parseInt(pid));

        if (!proc) {
          return res.status(404).json({ error: 'Process not found' });
        }

        const logs = {
          stdout: '',
          stderr: ''
        };

        const stdoutPath = path.join(proc.logsDir, 'stdout.log');
        const stderrPath = path.join(proc.logsDir, 'stderr.log');

        if (fs.existsSync(stdoutPath)) {
          logs.stdout = await fsPromises.readFile(stdoutPath, 'utf8');
        }
        if (fs.existsSync(stderrPath)) {
          logs.stderr = await fsPromises.readFile(stderrPath, 'utf8');
        }

        res.json(logs);
      } catch (error) {
        logger.error('Error getting process logs:', error);
        res.status(500).json({ error: 'Failed to get process logs' });
      }
    });

    // API endpoint to terminate a process
    app.post('/api/process/:pid/terminate', async (req, res) => {
      try {
        const { pid } = req.params;
        const pidNum = parseInt(pid);

        // Try to terminate the process
        try {
          process.kill(pidNum, 'SIGTERM');

          // Give it a moment to terminate gracefully
          setTimeout(() => {
            try {
              process.kill(pidNum, 0); // Check if still running
              process.kill(pidNum, 'SIGKILL'); // Force kill if still running
            } catch (e) {
              // Process already terminated
            }
          }, 2000);

          res.json({ success: true, message: `Process ${pid} terminated` });
        } catch (error) {
          if (error.code === 'ESRCH') {
            res.json({ success: true, message: `Process ${pid} not found (already terminated)` });
          } else {
            throw error;
          }
        }
      } catch (error) {
        logger.error('Error terminating process:', error);
        res.status(500).json({ error: 'Failed to terminate process' });
      }
    });

    // API endpoint to scan for orphaned instances
    app.get('/api/scan-orphans', async (req, res) => {
      try {
        const orphans = [];
        const trackingPath = path.join(process.cwd(), 'rabbitize-runs', 'process-tracking.json');
        let knownPorts = new Set();

        // Get known ports from tracking
        if (fs.existsSync(trackingPath)) {
          const tracking = JSON.parse(await fsPromises.readFile(trackingPath, 'utf8'));
          tracking.processes.forEach(p => knownPorts.add(p.port));
        }

        // Also check recent status files for ports
        const runsDir = path.join(process.cwd(), 'rabbitize-runs');
        if (fs.existsSync(runsDir)) {
          const clients = await fsPromises.readdir(runsDir);

          for (const client of clients) {
            if (client === 'process-tracking.json') continue;
            const clientPath = path.join(runsDir, client);
            const stat = await fsPromises.stat(clientPath);
            if (!stat.isDirectory()) continue;

            const tests = await fsPromises.readdir(clientPath);
            for (const test of tests) {
              const testPath = path.join(clientPath, test);
              const testStat = await fsPromises.stat(testPath);
              if (!testStat.isDirectory()) continue;

              const sessions = await fsPromises.readdir(testPath);
              for (const session of sessions) {
                const statusPath = path.join(testPath, session, 'status.json');
                if (fs.existsSync(statusPath)) {
                  try {
                    const status = JSON.parse(await fsPromises.readFile(statusPath, 'utf8'));
                    if (status.port && status.status === 'active') {
                      // Check if this port is actually in use
                      const net = require('net');
                      const isPortInUse = await new Promise(resolve => {
                        const tester = net.createServer()
                          .once('error', () => resolve(true))
                          .once('listening', () => {
                            tester.close();
                            resolve(false);
                          })
                          .listen(status.port);
                      });

                      if (isPortInUse && !knownPorts.has(status.port)) {
                        orphans.push({
                          port: status.port,
                          clientId: client,
                          testId: test,
                          sessionId: session,
                          lastUpdate: status.lastUpdate || 'unknown'
                        });
                      }
                    }
                  } catch (e) {
                    // Ignore parsing errors
                  }
                }
              }
            }
          }
        }

        res.json({ orphans });
      } catch (error) {
        logger.error('Error scanning for orphans:', error);
        res.status(500).json({ error: 'Failed to scan for orphans' });
      }
    });

    // Export all test definitions as JSON
    app.get('/api/export-tests', async (req, res) => {
      try {
        const runsDir = path.join(process.cwd(), 'rabbitize-runs');
        const exportData = {
          exportDate: new Date().toISOString(),
          version: '1.0',
          tests: {}
        };

        if (!fs.existsSync(runsDir)) {
          return res.json(exportData);
        }

        const clients = await fsPromises.readdir(runsDir);

        for (const clientId of clients) {
          if (clientId === 'process-tracking.json') continue;
          const clientPath = path.join(runsDir, clientId);
          const clientStat = await fsPromises.stat(clientPath);
          if (!clientStat.isDirectory()) continue;

          exportData.tests[clientId] = {};
          const tests = await fsPromises.readdir(clientPath);

          for (const testId of tests) {
            const testPath = path.join(clientPath, testId);
            const testStat = await fsPromises.stat(testPath);
            if (!testStat.isDirectory()) continue;

            // Get all sessions for this test, sorted by date (newest first)
            const sessions = await fsPromises.readdir(testPath);
            const sessionData = [];

            for (const sessionId of sessions) {
              const sessionPath = path.join(testPath, sessionId);
              const sessionStat = await fsPromises.stat(sessionPath);
              if (!sessionStat.isDirectory()) continue;

              const commandsPath = path.join(sessionPath, 'commands.json');
              const metadataPath = path.join(sessionPath, 'session-metadata.json');

              if (fs.existsSync(commandsPath)) {
                try {
                  const commands = JSON.parse(await fsPromises.readFile(commandsPath, 'utf8'));
                  let metadata = {};
                  if (fs.existsSync(metadataPath)) {
                    metadata = JSON.parse(await fsPromises.readFile(metadataPath, 'utf8'));
                  }
                  sessionData.push({
                    sessionId,
                    commands,
                    url: metadata.initialUrl || '',
                    startTime: metadata.startTime || sessionStat.ctimeMs
                  });
                } catch (e) {
                  // Skip invalid files
                }
              }
            }

            // Sort by startTime descending and take the most recent
            sessionData.sort((a, b) => b.startTime - a.startTime);

            if (sessionData.length > 0) {
              const latest = sessionData[0];
              exportData.tests[clientId][testId] = {
                commands: latest.commands,
                url: latest.url,
                lastSessionId: latest.sessionId,
                lastRun: new Date(latest.startTime).toISOString(),
                totalRuns: sessionData.length
              };
            }
          }

          // Remove empty clients
          if (Object.keys(exportData.tests[clientId]).length === 0) {
            delete exportData.tests[clientId];
          }
        }

        // Set filename for download
        const filename = `rabbitize-tests-${new Date().toISOString().split('T')[0]}.json`;
        res.setHeader('Content-Disposition', `attachment; filename="${filename}"`);
        res.setHeader('Content-Type', 'application/json');
        res.json(exportData);

      } catch (error) {
        logger.error('Error exporting tests:', error);
        res.status(500).json({ error: 'Failed to export tests' });
      }
    });

    // Import test definitions from JSON
    app.post('/api/import-tests', async (req, res) => {
      try {
        const importData = req.body;

        if (!importData || !importData.tests) {
          return res.status(400).json({ error: 'Invalid import data format' });
        }

        const runsDir = path.join(process.cwd(), 'rabbitize-runs');
        await fsPromises.mkdir(runsDir, { recursive: true });

        let imported = 0;
        let skipped = 0;

        for (const [clientId, tests] of Object.entries(importData.tests)) {
          if (!tests || typeof tests !== 'object') {
            skipped++;
            continue;
          }

          for (const [testId, testData] of Object.entries(tests)) {
            if (!testData.commands || !Array.isArray(testData.commands)) {
              skipped++;
              continue;
            }

            // Create a new session for this imported test
            const sessionId = `imported-${new Date().toISOString().replace(/[:.]/g, '-')}`;
            const sessionPath = path.join(runsDir, clientId, testId, sessionId);

            await fsPromises.mkdir(sessionPath, { recursive: true });

            // Write commands.json
            await fsPromises.writeFile(
              path.join(sessionPath, 'commands.json'),
              JSON.stringify(testData.commands, null, 2)
            );

            // Write session-metadata.json with all required fields for display
            const now = Date.now();
            const metadata = {
              clientId,
              testId,
              sessionId,
              status: 'imported',
              phase: 'imported',
              startTime: now,
              endTime: now,
              duration: 0,
              initialUrl: testData.url || '',
              commandCount: testData.commands.length,
              totalCommands: testData.commands.length,
              importedFrom: testData.lastSessionId || 'unknown',
              importedAt: new Date().toISOString(),
              originalLastRun: testData.lastRun || null,
              hasVideo: false,
              hasScreenshots: false
            };
            await fsPromises.writeFile(
              path.join(sessionPath, 'session-metadata.json'),
              JSON.stringify(metadata, null, 2)
            );

            imported++;
          }
        }

        res.json({
          success: true,
          imported,
          skipped,
          message: `Imported ${imported} test definition(s), skipped ${skipped}`
        });

      } catch (error) {
        logger.error('Error importing tests:', error);
        res.status(500).json({ error: 'Failed to import tests: ' + error.message });
      }
    });

    // Root redirect to streaming dashboard
    app.get('/', (req, res) => {
      res.redirect('/streaming');
    });

    // Streaming dashboard - shows all active sessions
    app.get('/streaming', async (req, res) => {

      // Read the template
      const templatePath = path.join(__dirname, '..', 'resources', 'streaming', 'dashboard.html');
      let html = await fsPromises.readFile(templatePath, 'utf8');

      // For initial load, we'll start with empty content that will be populated by JavaScript
      const sessionsContent = '<div id="sessions-container">Loading...</div>';

      // Replace placeholder
      html = html.replace('{{SESSIONS_CONTENT}}', sessionsContent);

      res.type('html').send(html);
    });

    // Flow Builder - interactive automation builder
    app.get('/flow-builder', async (req, res) => {
      try {
        // Read the template
        const templatePath = path.join(__dirname, '..', 'resources', 'streaming', 'flow-builder.html');

        // Log for debugging
        logger.log('Flow Builder requested, looking for file at:', templatePath);

        // Check if file exists
        if (!fs.existsSync(templatePath)) {
          logger.error('Flow Builder template not found at:', templatePath);
          return res.status(404).send('Flow Builder template not found');
        }

        let html = await fsPromises.readFile(templatePath, 'utf8');

        // Generate a memorable test ID for this flow builder session
        const generateFlowTestId = () => {
          const verbs = [
            'dancing', 'flying', 'running', 'jumping', 'spinning', 'gliding', 'racing', 'floating',
            'bouncing', 'sliding', 'rolling', 'drifting', 'soaring', 'diving', 'climbing', 'surfing'
          ];
          const nouns = [
            'rabbit', 'fox', 'wolf', 'eagle', 'tiger', 'lion', 'bear', 'shark', 'falcon', 'panther',
            'dolphin', 'hawk', 'lynx', 'otter', 'raven', 'cobra', 'phoenix', 'dragon', 'unicorn', 'griffin'
          ];

          const verb = verbs[Math.floor(Math.random() * verbs.length)];
          const noun = nouns[Math.floor(Math.random() * nouns.length)];
          const num = Math.floor(Math.random() * 99) + 1; // 1-99

          return `${verb}-${noun}-${num}`;
        };

        const flowTestId = generateFlowTestId();
        // const flowTestId = `flow-${Date.now()}`;

        // Replace placeholders
        html = html.replace(/{{FLOW_TEST_ID}}/g, flowTestId);
        html = html.replace(/{{PORT}}/g, argv.port);

        res.type('html').send(html);
      } catch (error) {
        logger.error('Error serving flow builder:', error);
        logger.error('Error details:', error.message, error.stack);
        res.status(500).send('Flow Builder not available: ' + error.message);
      }
    });

    // Single client view page
    app.get('/single-client/:clientId', async (req, res) => {
      const { clientId } = req.params;

      // Read the template
      const templatePath = path.join(__dirname, '..', 'resources', 'streaming', 'single-client.html');
      let html = await fsPromises.readFile(templatePath, 'utf8');

      // Replace placeholders
      html = html.replace(/{{CLIENT_ID}}/g, clientId);

      res.type('html').send(html);
    });

    // Single test view page
    app.get('/single-test/:clientId/:testId', async (req, res) => {
      const { clientId, testId } = req.params;

      // Read the template
      const templatePath = path.join(__dirname, '..', 'resources', 'streaming', 'single-test.html');
      let html = await fsPromises.readFile(templatePath, 'utf8');

      // Replace placeholders
      html = html.replace(/{{CLIENT_ID}}/g, clientId);
      html = html.replace(/{{TEST_ID}}/g, testId);

      res.type('html').send(html);
    });

    // Single session view page
    app.get('/single-session/:clientId/:testId/:sessionId', async (req, res) => {
      const { clientId, testId, sessionId } = req.params;

      // Read the template
      const templatePath = path.join(__dirname, '..', 'resources', 'streaming', 'single-session.html');
      let html = await fsPromises.readFile(templatePath, 'utf8');

      // Replace placeholders
      html = html.replace(/{{CLIENT_ID}}/g, clientId);
      html = html.replace(/{{TEST_ID}}/g, testId);
      html = html.replace(/{{SESSION_ID}}/g, sessionId);

      res.type('html').send(html);
    });

    // Visual regression comparison page
    app.get('/compare/:clientId/:testId', async (req, res) => {
      const { clientId, testId } = req.params;

      const templatePath = path.join(__dirname, '..', 'resources', 'streaming', 'compare.html');
      let html = await fsPromises.readFile(templatePath, 'utf8');

      html = html.replace(/{{CLIENT_ID}}/g, clientId);
      html = html.replace(/{{TEST_ID}}/g, testId);

      res.type('html').send(html);
    });

    const VISUAL_WARN_THRESHOLD = 1;
    const VISUAL_FAIL_THRESHOLD = 5;
    const STRICT_MINOR_THRESHOLD = 0.01;

    function parseBooleanQuery(value, defaultValue = true) {
      if (value === undefined || value === null || value === '') {
        return defaultValue;
      }
      const normalized = String(value).toLowerCase();
      if (['1', 'true', 'yes', 'on'].includes(normalized)) return true;
      if (['0', 'false', 'no', 'off'].includes(normalized)) return false;
      return defaultValue;
    }

    function parsePositiveInteger(value, defaultValue = null) {
      if (value === undefined || value === null || value === '') {
        return defaultValue;
      }
      const parsed = Number.parseInt(value, 10);
      if (Number.isNaN(parsed) || parsed <= 0) {
        return defaultValue;
      }
      return parsed;
    }

    function sanitizeSessionId(value) {
      if (!value) return null;
      const cleaned = String(value).trim();
      return cleaned.length > 0 ? cleaned : null;
    }

    function getCommandAtIndex(commands, index) {
      if (!Array.isArray(commands) || !commands[index]) {
        return null;
      }

      const raw = commands[index];
      if (Array.isArray(raw)) {
        return raw;
      }
      if (raw && Array.isArray(raw.command)) {
        return raw.command;
      }
      if (raw && raw.command !== undefined) {
        return raw.command;
      }
      return raw;
    }

    function formatCommandForDisplay(command) {
      if (command === null || command === undefined) {
        return null;
      }
      if (typeof command === 'string') {
        return command;
      }
      try {
        return JSON.stringify(command);
      } catch (error) {
        return String(command);
      }
    }

    function toSessionResponse(session) {
      return {
        sessionId: session.sessionId,
        startTime: session.startTime,
        commandCount: session.commandCount,
        hasScreenshots: session.hasScreenshots
      };
    }

    async function collectComparisonSessions(testPath) {
      const sessionDirs = await fsPromises.readdir(testPath);
      const sessions = [];

      for (const sessionId of sessionDirs) {
        const sessionPath = path.join(testPath, sessionId);
        const stat = await fsPromises.stat(sessionPath);
        if (!stat.isDirectory()) continue;

        const metadataPath = path.join(sessionPath, 'session-metadata.json');
        const statusPath = path.join(sessionPath, 'status.json');
        const commandsPath = path.join(sessionPath, 'commands.json');
        const screenshotsPath = path.join(sessionPath, 'screenshots');

        const sessionInfo = {
          sessionId,
          startTime: stat.ctimeMs,
          commandCount: 0,
          commands: [],
          hasScreenshots: fs.existsSync(screenshotsPath)
        };

        if (fs.existsSync(metadataPath)) {
          try {
            const metadata = JSON.parse(await fsPromises.readFile(metadataPath, 'utf8'));
            sessionInfo.startTime = metadata.startTime || sessionInfo.startTime;
            sessionInfo.commandCount = metadata.commandCount || sessionInfo.commandCount;
          } catch (error) {}
        }

        if (fs.existsSync(statusPath)) {
          try {
            const status = JSON.parse(await fsPromises.readFile(statusPath, 'utf8'));
            sessionInfo.startTime = status.startTime || sessionInfo.startTime;
            sessionInfo.commandCount = status.commandCount || sessionInfo.commandCount;
          } catch (error) {}
        }

        if (fs.existsSync(commandsPath)) {
          try {
            const commands = JSON.parse(await fsPromises.readFile(commandsPath, 'utf8'));
            if (Array.isArray(commands)) {
              sessionInfo.commands = commands;
              sessionInfo.commandCount = commands.length;
            }
          } catch (error) {}
        }

        sessions.push(sessionInfo);
      }

      sessions.sort((a, b) => b.startTime - a.startTime);
      return sessions;
    }

    function resolveComparisonPair(sessions, baselineSessionId, latestSessionId) {
      if (sessions.length < 2) {
        return { error: 'Need at least 2 sessions for comparison' };
      }

      let latest = sessions[0];
      let baseline = sessions[1];

      const requestedLatestId = sanitizeSessionId(latestSessionId);
      const requestedBaselineId = sanitizeSessionId(baselineSessionId);

      if (requestedLatestId) {
        latest = sessions.find(session => session.sessionId === requestedLatestId);
        if (!latest) {
          return { error: `Requested latest session not found: ${requestedLatestId}` };
        }
      }

      if (requestedBaselineId) {
        baseline = sessions.find(session => session.sessionId === requestedBaselineId);
        if (!baseline) {
          return { error: `Requested baseline session not found: ${requestedBaselineId}` };
        }
      }

      if (!requestedBaselineId) {
        baseline = sessions.find(session => session.sessionId !== latest.sessionId) || null;
      }
      if (!requestedLatestId) {
        latest = sessions.find(session => session.sessionId !== baseline.sessionId) || null;
      }

      if (!baseline || !latest) {
        return { error: 'Unable to resolve comparison pair from available sessions' };
      }

      if (baseline.sessionId === latest.sessionId) {
        return { error: 'Baseline and latest sessions must be different' };
      }

      return { baseline, latest };
    }

    function getStepStatus(stepData) {
      if (stepData.error) return 'error';
      if (stepData.missingScreenshots) return 'fail';
      if (stepData.diffPercent >= VISUAL_FAIL_THRESHOLD) return 'fail';
      if (stepData.diffPercent >= VISUAL_WARN_THRESHOLD || stepData.hasDomChange) return 'warn';
      if (stepData.strictDiffPercent >= STRICT_MINOR_THRESHOLD) return 'info';
      return 'pass';
    }

    async function compareSessionPair({ clientId, testId, testPath, baseline, latest, includeSteps = true }) {
      const maxSteps = Math.max(baseline.commandCount, latest.commandCount);
      const steps = [];

      let significantChangedSteps = 0;
      let visualChangedSteps = 0;
      let minorChangedSteps = 0;
      let domChangedSteps = 0;
      let missingSteps = 0;
      let erroredSteps = 0;
      let maxDiffPercent = 0;
      let maxStrictDiffPercent = 0;
      let avgDiffSum = 0;
      let avgStrictDiffSum = 0;
      let comparedImageSteps = 0;

      for (let i = 0; i < maxSteps; i++) {
        const stepData = {
          index: i,
          command: null,
          diffPercent: 0,
          strictDiffPercent: 0,
          meanDeltaPercent: 0,
          hasDomChange: false,
          baselineScreenshot: null,
          latestScreenshot: null,
          missingScreenshots: false,
          imageCompared: false,
          hasAnyChange: false,
          stepStatus: 'pass',
          error: null
        };

        const baselineCommand = getCommandAtIndex(baseline.commands, i);
        const latestCommand = getCommandAtIndex(latest.commands, i);
        stepData.command = formatCommandForDisplay(baselineCommand || latestCommand);

        const baselineScreenshotsPath = path.join(testPath, baseline.sessionId, 'screenshots');
        const latestScreenshotsPath = path.join(testPath, latest.sessionId, 'screenshots');

        const baselineCrop = `${i}.jpg`;
        const latestCrop = `${i}.jpg`;

        const baselineCropPath = path.join(baselineScreenshotsPath, baselineCrop);
        const latestCropPath = path.join(latestScreenshotsPath, latestCrop);

        if (fs.existsSync(baselineCropPath)) {
          stepData.baselineScreenshot = baselineCrop;
        }
        if (fs.existsSync(latestCropPath)) {
          stepData.latestScreenshot = latestCrop;
        }

        if (stepData.baselineScreenshot && stepData.latestScreenshot) {
          const cacheKey = `${clientId}/${testId}/${baseline.sessionId}/${latest.sessionId}/${i}`;
          const diffResult = await imageCompare.getCachedDiff(cacheKey, baselineCropPath, latestCropPath);

          if (diffResult.error) {
            stepData.error = diffResult.error;
            stepData.diffPercent = -1;
            stepData.strictDiffPercent = -1;
            erroredSteps++;
          } else {
            stepData.diffPercent = diffResult.diffPercent;
            stepData.strictDiffPercent = diffResult.strictDiffPercent ?? diffResult.diffPercent;
            stepData.meanDeltaPercent = diffResult.meanDeltaPercent ?? 0;
            stepData.imageCompared = true;

            comparedImageSteps++;
            avgDiffSum += stepData.diffPercent;
            avgStrictDiffSum += stepData.strictDiffPercent;

            maxDiffPercent = Math.max(maxDiffPercent, stepData.diffPercent);
            maxStrictDiffPercent = Math.max(maxStrictDiffPercent, stepData.strictDiffPercent);

            if (stepData.diffPercent >= VISUAL_WARN_THRESHOLD) {
              visualChangedSteps++;
            } else if (stepData.strictDiffPercent >= STRICT_MINOR_THRESHOLD) {
              minorChangedSteps++;
            }
          }
        } else {
          stepData.missingScreenshots = true;
          stepData.diffPercent = 100;
          stepData.strictDiffPercent = 100;
          stepData.meanDeltaPercent = 100;
          missingSteps++;
          visualChangedSteps++;
          maxDiffPercent = Math.max(maxDiffPercent, stepData.diffPercent);
          maxStrictDiffPercent = Math.max(maxStrictDiffPercent, stepData.strictDiffPercent);
        }

        const baselineDomPath = path.join(testPath, baseline.sessionId, 'dom_snapshots', `dom_${i}.md`);
        const latestDomPath = path.join(testPath, latest.sessionId, 'dom_snapshots', `dom_${i}.md`);

        if (fs.existsSync(baselineDomPath) && fs.existsSync(latestDomPath)) {
          try {
            const baselineDom = await fsPromises.readFile(baselineDomPath, 'utf8');
            const latestDom = await fsPromises.readFile(latestDomPath, 'utf8');
            stepData.hasDomChange = baselineDom !== latestDom;
            if (stepData.hasDomChange) {
              domChangedSteps++;
            }
          } catch (error) {}
        }

        stepData.stepStatus = getStepStatus(stepData);
        stepData.hasAnyChange = stepData.stepStatus !== 'pass';

        if (stepData.stepStatus === 'warn' || stepData.stepStatus === 'fail' || stepData.stepStatus === 'error') {
          significantChangedSteps++;
        }

        if (includeSteps) {
          steps.push(stepData);
        }
      }

      let overallStatus = 'pass';
      if (erroredSteps > 0 || missingSteps > 0 || maxDiffPercent >= VISUAL_FAIL_THRESHOLD) {
        overallStatus = 'fail';
      } else if (significantChangedSteps > 0) {
        overallStatus = 'warn';
      } else if (minorChangedSteps > 0) {
        overallStatus = 'info';
      }

      return {
        baseline: toSessionResponse(baseline),
        latest: toSessionResponse(latest),
        steps,
        summary: {
          totalSteps: maxSteps,
          changedSteps: significantChangedSteps,
          significantChangedSteps,
          visualChangedSteps,
          minorChangedSteps,
          domChangedSteps,
          missingSteps,
          erroredSteps,
          comparedImageSteps,
          maxDiffPercent,
          maxStrictDiffPercent,
          avgDiffPercent: comparedImageSteps > 0 ? avgDiffSum / comparedImageSteps : 0,
          avgStrictDiffPercent: comparedImageSteps > 0 ? avgStrictDiffSum / comparedImageSteps : 0,
          overallStatus
        }
      };
    }

    async function buildTimelineSummaries({ clientId, testId, testPath, sessions, timelineLimit = null }) {
      const chronological = [...sessions].sort((a, b) => a.startTime - b.startTime);
      const allPairs = [];

      for (let i = 1; i < chronological.length; i++) {
        allPairs.push({
          baseline: chronological[i - 1],
          latest: chronological[i]
        });
      }

      const pairsToCompare = timelineLimit ? allPairs.slice(-timelineLimit) : allPairs;
      const comparisons = [];

      for (const pair of pairsToCompare) {
        const pairComparison = await compareSessionPair({
          clientId,
          testId,
          testPath,
          baseline: pair.baseline,
          latest: pair.latest,
          includeSteps: false
        });

        comparisons.push({
          baselineSessionId: pair.baseline.sessionId,
          latestSessionId: pair.latest.sessionId,
          baselineStartTime: pair.baseline.startTime,
          latestStartTime: pair.latest.startTime,
          baselineCommandCount: pair.baseline.commandCount,
          latestCommandCount: pair.latest.commandCount,
          summary: pairComparison.summary
        });
      }

      comparisons.sort((a, b) => b.latestStartTime - a.latestStartTime);

      return {
        totalPairs: allPairs.length,
        returnedPairs: comparisons.length,
        truncated: timelineLimit !== null && allPairs.length > pairsToCompare.length,
        comparisons
      };
    }

    // API endpoint for visual regression comparison data
    app.get('/api/compare/:clientId/:testId', async (req, res) => {
      const { clientId, testId } = req.params;
      const testPath = path.join(process.cwd(), 'rabbitize-runs', clientId, testId);
      const baselineSessionId = sanitizeSessionId(req.query.baselineSessionId);
      const latestSessionId = sanitizeSessionId(req.query.latestSessionId);
      const includeSteps = parseBooleanQuery(req.query.includeSteps, true);
      const includeTimeline = parseBooleanQuery(req.query.includeTimeline, true);
      const timelineLimit = parsePositiveInteger(req.query.timelineLimit, null);

      try {
        if (!fs.existsSync(testPath)) {
          return res.status(404).json({ error: 'Test not found', sessionCount: 0 });
        }

        const sessions = await collectComparisonSessions(testPath);

        if (sessions.length < 2) {
          return res.json({
            error: 'Need at least 2 sessions for comparison',
            sessionCount: sessions.length,
            sessions: sessions.map(toSessionResponse)
          });
        }

        const pair = resolveComparisonPair(sessions, baselineSessionId, latestSessionId);
        if (pair.error) {
          return res.status(400).json({
            error: pair.error,
            sessionCount: sessions.length,
            sessions: sessions.map(toSessionResponse)
          });
        }

        const pairComparison = await compareSessionPair({
          clientId,
          testId,
          testPath,
          baseline: pair.baseline,
          latest: pair.latest,
          includeSteps
        });

        let timeline = null;
        if (includeTimeline) {
          timeline = await buildTimelineSummaries({
            clientId,
            testId,
            testPath,
            sessions,
            timelineLimit
          });
        }

        res.json({
          sessionCount: sessions.length,
          sessions: sessions.map(toSessionResponse),
          pair: {
            baselineSessionId: pair.baseline.sessionId,
            latestSessionId: pair.latest.sessionId
          },
          baseline: pairComparison.baseline,
          latest: pairComparison.latest,
          steps: pairComparison.steps,
          summary: pairComparison.summary,
          timeline
        });
      } catch (error) {
        logger.error('Error generating comparison:', error);
        res.status(500).json({ error: 'Failed to generate comparison' });
      }
    });

    // API endpoint for diff image
    app.get('/api/compare/:clientId/:testId/diff/:stepIndex', async (req, res) => {
      const { clientId, testId, stepIndex } = req.params;
      const testPath = path.join(process.cwd(), 'rabbitize-runs', clientId, testId);
      const baselineSessionId = sanitizeSessionId(req.query.baselineSessionId);
      const latestSessionId = sanitizeSessionId(req.query.latestSessionId);
      const index = Number.parseInt(stepIndex, 10);

      if (!Number.isInteger(index) || index < 0) {
        return res.status(400).json({ error: 'Invalid step index' });
      }

      try {
        if (!fs.existsSync(testPath)) {
          return res.status(404).json({ error: 'Test not found' });
        }

        const sessions = await collectComparisonSessions(testPath);
        const pair = resolveComparisonPair(sessions, baselineSessionId, latestSessionId);
        if (pair.error) {
          return res.status(400).json({ error: pair.error });
        }

        const baselineCropPath = path.join(testPath, pair.baseline.sessionId, 'screenshots', `${index}.jpg`);
        const latestCropPath = path.join(testPath, pair.latest.sessionId, 'screenshots', `${index}.jpg`);

        if (!fs.existsSync(baselineCropPath) || !fs.existsSync(latestCropPath)) {
          return res.status(404).json({ error: 'Screenshots not found for this step' });
        }

        const cacheKey = `${clientId}/${testId}/${pair.baseline.sessionId}/${pair.latest.sessionId}/${index}`;
        const diffResult = await imageCompare.getCachedDiff(cacheKey, baselineCropPath, latestCropPath);

        if (diffResult.error) {
          return res.status(500).json({ error: diffResult.error });
        }

        res.set('Content-Type', 'image/png');
        res.set('Cache-Control', 'public, max-age=300');
        res.send(diffResult.diffImageBuffer);
      } catch (error) {
        logger.error('Error generating diff image:', error);
        res.status(500).json({ error: 'Failed to generate diff image' });
      }
    });

    // API endpoint for DOM diff
    app.get('/api/compare/:clientId/:testId/dom-diff/:stepIndex', async (req, res) => {
      const { clientId, testId, stepIndex } = req.params;
      const testPath = path.join(process.cwd(), 'rabbitize-runs', clientId, testId);
      const baselineSessionId = sanitizeSessionId(req.query.baselineSessionId);
      const latestSessionId = sanitizeSessionId(req.query.latestSessionId);
      const index = Number.parseInt(stepIndex, 10);

      if (!Number.isInteger(index) || index < 0) {
        return res.status(400).send('<div class="dom-diff-empty">Invalid step index</div>');
      }

      try {
        if (!fs.existsSync(testPath)) {
          return res.status(404).send('<div class="dom-diff-empty">Test not found</div>');
        }

        const sessions = await collectComparisonSessions(testPath);
        const pair = resolveComparisonPair(sessions, baselineSessionId, latestSessionId);
        if (pair.error) {
          return res.status(400).send(`<div class="dom-diff-empty">${pair.error}</div>`);
        }

        const baselineDomPath = path.join(testPath, pair.baseline.sessionId, 'dom_snapshots', `dom_${index}.md`);
        const latestDomPath = path.join(testPath, pair.latest.sessionId, 'dom_snapshots', `dom_${index}.md`);

        let baselineDom = '';
        let latestDom = '';

        if (fs.existsSync(baselineDomPath)) {
          baselineDom = await fsPromises.readFile(baselineDomPath, 'utf8');
        }
        if (fs.existsSync(latestDomPath)) {
          latestDom = await fsPromises.readFile(latestDomPath, 'utf8');
        }

        if (!baselineDom && !latestDom) {
          return res.send('<div class="dom-diff-empty">No DOM snapshots available for this step</div>');
        }

        const diff = imageCompare.generateTextDiff(baselineDom, latestDom);
        const html = imageCompare.diffToHtml(diff);

        res.type('html').send(html);
      } catch (error) {
        logger.error('Error generating DOM diff:', error);
        res.status(500).send('<div class="dom-diff-empty">Error generating DOM diff</div>');
      }
    });

    // Test endpoint for viewing the stream
    app.get('/stream-viewer/:clientId/:testId/:sessionId', async (req, res) => {
      const { clientId, testId, sessionId } = req.params;

      // Check if session is finished (in memory or on disk)
      const sessionKey = `${clientId}/${testId}/${sessionId}`;
      const sessionState = sessionStates.get(sessionKey);
      let isFinished = sessionState && sessionState.status === 'finished';
      let sessionMetadata = sessionState;

      // If not in memory, check filesystem
      if (!sessionState) {
        const metadataPath = path.join(process.cwd(), 'rabbitize-runs', clientId, testId, sessionId, 'session-metadata.json');
        if (fs.existsSync(metadataPath)) {
          try {
            sessionMetadata = JSON.parse(await fsPromises.readFile(metadataPath, 'utf8'));
            isFinished = true;
          } catch (error) {
            logger.warn('Failed to read session metadata:', error);
          }
        }
      }

      if (isFinished) {
        // Serve video player page for finished sessions
        const videoPath = `/rabbitize-runs/${clientId}/${testId}/${sessionId}/video/session.webm`;

        const html = `
<!DOCTYPE html>
<html>
<head>
    <title>RABBITIZE /// VIDEO - ${clientId}/${testId}/${sessionId}</title>
    <link rel="stylesheet" href="/resources/streaming/cyberpunk.css">
    <style>
        .video-container {
            text-align: center;
            background: #000;
            padding: 20px;
            border: 1px solid #0ff;
            box-shadow: 0 0 30px rgba(0, 255, 255, 0.2);
            position: relative;
        }

        video {
            max-width: 100%;
            height: auto;
            border: 1px solid #0ff;
            box-shadow: 0 0 20px rgba(0, 255, 255, 0.3);
        }

        .video-error {
            color: #ff0066;
            text-align: center;
            padding: 40px;
            display: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 class="glitch" data-text="RABBITIZE /// SESSION VIDEO">RABBITIZE /// SESSION VIDEO</h1>
            <div class="subtitle">RECORDED SESSION PLAYBACK</div>
        </div>

        <div class="video-container">
            <video id="session-video" controls autoplay>
                <source src="${videoPath}" type="video/webm">
                Your browser does not support the video tag.
            </video>
        </div>

        <div class="info">
            ${sessionMetadata?.initialUrl ? `<p>URL: <code>${sessionMetadata.initialUrl}</code></p>` : ''}
            <p>CLIENT: <code>${clientId}</code> | TEST: <code>${testId}</code> | SESSION: <code>${sessionId}</code></p>
            <p>STATUS: <code>FINISHED</code> | DURATION: <code>${Math.floor((sessionMetadata?.duration || 0) / 1000)}s</code> | COMMANDS: <code>${sessionMetadata?.commandCount || 0}</code></p>
        </div>

        <div id="video-error" class="video-error">
            <p>[ VIDEO NOT FOUND ]</p>
            <p>The session video may still be processing or was not recorded</p>
        </div>
    </div>

    <script>
        const video = document.getElementById('session-video');
        const errorDiv = document.getElementById('video-error');

        video.onerror = function() {
            video.style.display = 'none';
            errorDiv.style.display = 'block';
        };
    </script>
</body>
</html>
        `;

        res.type('html').send(html);
      } else {
        // Serve live stream viewer for active sessions
        const templatePath = path.join(__dirname, '..', 'resources', 'streaming', 'viewer.html');
        let html = await fsPromises.readFile(templatePath, 'utf8');

        // Check if this is an external session with a different port
        let streamPort = argv.port; // Default to current process port
        let streamHost = req.get('host') ? req.get('host').split(':')[0] : os.hostname();

        // Check session state for external port info
        if (sessionState && sessionState.isExternal && sessionState.port) {
          streamPort = sessionState.port;
        } else {
          // Check status.json for external processes
          const statusPath = path.join(process.cwd(), 'rabbitize-runs', clientId, testId, sessionId, 'status.json');
          if (fs.existsSync(statusPath)) {
            try {
              const status = JSON.parse(await fsPromises.readFile(statusPath, 'utf8'));
              if (status.port) {
                streamPort = status.port;
              }
            } catch (error) {
              logger.warn('Failed to read status.json for port info:', error);
            }
          }
        }

        // Replace placeholders
        html = html
          .replace(/{{CLIENT_ID}}/g, clientId)
          .replace(/{{TEST_ID}}/g, testId)
          .replace(/{{SESSION_ID}}/g, sessionId)
          .replace(/{{STREAM_URL}}/g, `http://${streamHost}:${streamPort}/stream/${clientId}/${testId}/${sessionId}`);

        res.type('html').send(html);
      }
    });


    // Periodic status updates removed - no longer needed without Firebase
    // Status is available via GET /status endpoint
    function startStatusUpdates() {
      // No-op - kept for compatibility if called
    }

    // Don't clean up sessions from memory - we want to track them

    // Catch-all error handler
    app.use((err, req, res, next) => {
      logger.error('Unhandled error:', err);
      res.status(500).json({
        error: 'Internal server error',
        details: err.message
      });
    });

  // Start the server
  server = app.listen(argv.port, () => {
    logger.log(chalk.bold.white(`🐰 Rabbitize session ${sessionTimestamp} running on port ${argv.port} 🐰`));
    logger.log(chalk.bold.white('Server address:'), JSON.stringify(server.address(), null, 2));
    const hostname = require('os').hostname();
    logger.log(chalk.bold.grey(`Running on host: ${hostname}`));
  });

    // Start periodic status updates
    startStatusUpdates();

    // Store server instance globally for access in QueueManager
    global.server = server;

    // Set up callback to update session state when sessions end
    queueManager.setOnSessionEndCallback((session) => {
      const sessionKey = `${session.clientId}/${session.testId}/${session.sessionId}`;
      const sessionState = sessionStates.get(sessionKey);
      if (sessionState) {
        sessionState.status = 'finished';
        sessionState.endTime = Date.now();
        sessionState.duration = sessionState.endTime - sessionState.startTime;
      }
    });

    // Set up callback to update command count
    queueManager.setOnCommandExecutedCallback((session) => {
      const sessionKey = `${session.clientId}/${session.testId}/${session.sessionId}`;
      const sessionState = sessionStates.get(sessionKey);
      if (sessionState) {
        sessionState.commandCount = session.commandCounter || 0;
      } else {
        logger.debug(`Session state not found for key: ${sessionKey}`);
        logger.debug(`Available keys: ${Array.from(sessionStates.keys()).join(', ')}`);
      }
    });

    // Set up callback for new sessions (bootstrap mode)
    queueManager.setOnSessionStartCallback((session) => {
      const sessionKey = `${session.clientId}/${session.testId}/${session.sessionId}`;
      if (!sessionStates.has(sessionKey)) {
        sessionStates.set(sessionKey, {
          clientId: session.clientId,
          testId: session.testId,
          sessionId: session.sessionId,
          status: 'active',
          startTime: Date.now(),
          commandCount: 0,
          phase: 'initializing',
          initialUrl: session.initialUrl || ''
        });
      }
    });

    // Set up global phase change callback
    global.onPhaseChange = (session, phase) => {
      const sessionKey = `${session.clientId}/${session.testId}/${session.sessionId}`;
      const sessionState = sessionStates.get(sessionKey);
      if (sessionState) {
        sessionState.phase = phase;
      }
    };

    // Handle process signals
    // const forceClose = () => {
    //   logger.log(chalk.red('\n ☠︎︎  Force closing server ☠︎︎'));
    //   server.close(() => {
    //     logger.log('Server closed');
    //     process.exit(0);
    //   });

    //   setTimeout(() => {
    //     //logger.log('Force exit');
    //     logger.log(chalk.red('\n ☠︎︎ Force exit ☠︎︎'))
    //     process.exit(1);
    //   }, 3000);
    // };

    const forceClose = async () => {
      logger.log(chalk.red('\n ☠︎︎  Force closing server ☠︎︎'));

      // Set running state to false
      await updateRunningState(false);

      server.close(() => {
        logger.log('Server closed');
        process.exit(0);
      });

      setTimeout(() => {
        logger.log(chalk.red('\n ☠︎︎ Force exit ☠︎︎'))
        process.exit(1);
      }, 3000);
    };

    process.on('SIGTERM', forceClose);
    process.on('SIGINT', forceClose);

    // Add keep-alive timeout
    server.keepAliveTimeout = 60000;
    server.headersTimeout = 65000;

    // Handle uncaught exceptions
    process.on('uncaughtException', (err) => {
      logger.error('Uncaught exception:', err);
    });

    process.on('unhandledRejection', (err) => {
      logger.error('Unhandled rejection:', err);
    });

    let batchJson = null;
    if (argv.batchCommands || process.env.BATCH_COMMANDS) {
      const batchCommands = argv.batchCommands || process.env.BATCH_COMMANDS;
      try {
        if (batchCommands.startsWith('Firebase:') || batchCommands.startsWith('Firestore:')) {
          // Firebase/Firestore batch loading has been disabled
          logger.error('Firebase/Firestore batch loading is no longer supported.');
          logger.error('Please provide batch commands as a JSON file or JSON string.');
          process.exit(1);
        } else if (batchCommands.startsWith('{') || batchCommands.startsWith('[')) {
          batchJson = JSON.parse(batchCommands);
        } else {
          // Treat as file path
          batchJson = JSON.parse(fs.readFileSync(batchCommands, 'utf8'));
        }
      } catch (error) {
        logger.error('Failed to parse batch commands:', error);
        process.exit(1);
      }
    }

    // Create session with batch JSON if available
    let session;
    try {
      // Add debug logging before creating PlaywrightSession
      console.log('\n[DEBUG] Creating PlaywrightSession:');
      // console.log('argv.showOverlay:', argv.showOverlay);
      const sessionOptions = {
        showCommandOverlay: argv.showOverlay,  // Explicitly map showOverlay to showCommandOverlay
        createClipSegments: argv.clipSegments,
        firebase: new SimpleLogger(argv.clientId, argv.testId, sessionTimestamp),  // Keep property name for compatibility
        clientId: argv.clientId,
        testId: argv.testId,
        batchJson,
        enableLiveScreenshots: argv.liveScreenshots
      };
      // Log only the safe properties
      console.log('sessionOptions:', {
        showCommandOverlay: sessionOptions.showCommandOverlay,
        createClipSegments: sessionOptions.createClipSegments,
        clientId: sessionOptions.clientId,
        testId: sessionOptions.testId,
        enableLiveScreenshots: sessionOptions.enableLiveScreenshots
      });

      session = new PlaywrightSession(sessionTimestamp, '', sessionOptions);

      // Set the session in the queue manager
      queueManager.setSession(session);

      logger.log('PlaywrightSession created successfully');

      // Handle batch mode
      if (batchJson) {
        // Temporarily close the server during batch processing
        await new Promise(resolve => server.close(resolve));
        logger.log('Server temporarily closed for batch processing');

        let batchUrl = argv.batchUrl || process.env.BATCH_URL;
        let commands;

        if (Array.isArray(batchJson)) {
          commands = batchJson;
          if (!batchUrl) {
            logger.error('Batch URL is required (via --batch-url)');
            process.exit(1);
          }
        } else {
          commands = batchJson.commands;
          batchUrl = batchJson.url || batchUrl;

          // Only check for batch URL if we're not getting data from Firebase
          if (!batchUrl && !argv.batchCommands?.startsWith('Firebase:')) {
            logger.error('Batch URL is required (either in JSON file or via --batch-url)');
            process.exit(1);
          }
        }

        const initResult = await session.initialize(batchUrl);
        if (!initResult.success) {
          logger.error('Failed to initialize session:', initResult.error);
          process.exit(1);
        }

        // Track session state for batch mode
        const actualSessionId = session.sessionId;
        const sessionKey = `${argv.clientId}/${argv.testId}/${actualSessionId}`;
        sessionStates.set(sessionKey, {
          clientId: argv.clientId,
          testId: argv.testId,
          sessionId: actualSessionId,
          status: 'active',
          startTime: Date.now(),
          commandCount: 0,
          totalCommands: commands.length,  // Store the actual total number of commands
          phase: 'initializing',
          initialUrl: batchUrl
        });
        logger.log(`Session state initialized for batch mode: ${sessionKey}`);

        queueManager.startProcessing();

        for (const command of commands) {
          await queueManager.enqueue('execute', { command });
        }
        await queueManager.enqueue('end');

        // If exit-on-end is true, set up exit after queue processing
        if (argv.exitOnEnd) {
          queueManager.setOnQueueEmptyCallback(() => {
            logger.log('Batch processing complete, exiting as requested (--exit-on-end)');
            setTimeout(() => {
              process.exit(0);
            }, 1000); // Give a second for final cleanup
          });
        }

        // Restart the server after batch processing
        server = app.listen(argv.port, () => {
          logger.log('Server restarted and ready for interactive sessions');
          //logger.log('Server address:', server.address());
        });
      }

    } catch (error) {
      logger.error('Failed to create PlaywrightSession:', error);
      process.exit(1);
    }

    // Update the reset-ids endpoint
    app.post('/reset', async (req, res) => {
      const {
          clientId,
          testId,
          // Optional configuration
          showOverlay,
          clipSegments,
          processVideo,
          exitOnEnd,
          meta
      } = req.body;

      if (!clientId || !testId) {
          return res.status(400).json({
              success: false,
              error: 'Client ID and Test ID are required'
          });
      }

      const session = global.currentPlaywrightSession;
      if (!session) {
          return res.status(400).json({
              success: false,
              error: 'No active session'
          });
      }

      try {
          // Reset the session with new IDs and optional configuration
          const resetResult = await session.resetWithNewIds(clientId, testId, {
              showOverlay,
              clipSegments,
              processVideo,
              exitOnEnd,
              meta
          });

          if (!resetResult.success) {
              throw new Error(resetResult.error || 'Reset failed');
          }

          res.json({
              success: true,
              message: 'Session reset successfully',
              sessionId: resetResult.sessionId
          });
      } catch (error) {
          res.status(500).json({
              success: false,
              error: error.message
          });
      }
    });

    // If URL is provided, auto-start a session
    if (argv.url) {
      const session = new PlaywrightSession(sessionTimestamp, '', {
        showCommandOverlay: argv.showOverlay,
        createClipSegments: argv.clipSegments,
        firebase: new SimpleLogger(argv.clientId, argv.testId, sessionTimestamp),  // Keep property name for compatibility
        clientId: argv.clientId,
        testId: argv.testId,
        enableLiveScreenshots: argv.liveScreenshots
      });

      // Set the session in the queue manager
      queueManager.setSession(session);

      logger.log(chalk.green(`Auto-starting session with URL: ${argv.url}`));

      const result = await session.initialize(argv.url);
      if (!result.success) {
        throw new Error('Failed to initialize session');
      }

      // Track session state using the ACTUAL sessionId from the session
      const actualSessionId = session.sessionId;
      const sessionKey = `${argv.clientId}/${argv.testId}/${actualSessionId}`;
      sessionStates.set(sessionKey, {
        clientId: argv.clientId,
        testId: argv.testId,
        sessionId: actualSessionId,
        status: 'active',
        startTime: Date.now(),
        commandCount: 0,
        phase: 'initializing',
        initialUrl: argv.url
      });

      // Start the queue processor after successful initialization
      queueManager.startProcessing();

      // If commands were provided, queue them
      if (argv.commands) {
        try {
          const commands = JSON.parse(argv.commands);
          if (!Array.isArray(commands)) {
            throw new Error('Commands must be a JSON array');
          }

          logger.log(chalk.green(`Queueing ${commands.length} commands for execution`));
          for (const command of commands) {
            queueManager.enqueue('execute', { command });
          }
        } catch (error) {
          logger.error('Failed to parse or queue commands:', error);
          throw error;
        }
      }
    }

    return app;
  // } catch (error) {
  //   console.error('Failed to start server:', error);
  //   process.exit(1);
  // }
}

// Helper function to find an available port
async function findAvailablePort(startPort) {
  return new Promise((resolve, reject) => {
    const tryPort = (port) => {
      const server = net.createServer();

      server.once('error', (err) => {
        if (err.code === 'EADDRINUSE') {
          tryPort(port + 1);
        } else {
          reject(err);
        }
      });

      server.once('listening', () => {
        server.close(() => {
          resolve(port);
        });
      });

      server.listen(port);
    };

    tryPort(startPort);
  });
}

// Helper function to wait for a port to be ready
async function waitForPort(port, timeout = 10000, host = os.hostname()) {
  const startTime = Date.now();
  const http = require('http');

  while (Date.now() - startTime < timeout) {
    try {
      // Try to make an HTTP request to /status endpoint
      const response = await new Promise((resolve, reject) => {
        const req = http.get(`http://${host}:${port}/status`, { timeout: 1000 }, (res) => {
          resolve(res);
        });

        req.on('error', reject);
        req.on('timeout', () => {
          req.destroy();
          reject(new Error('Request timeout'));
        });
      });

      // If we get any response, the server is ready
      return true;
    } catch (error) {
      // Server not ready yet, wait a bit
      await new Promise(resolve => setTimeout(resolve, 200));
    }
  }

  throw new Error(`Timeout waiting for port ${port} to be ready`);
}

// Start the application
main().catch(error => {
  console.error('Application failed:', error);
  process.exit(1);
});
