#FROM mcr.microsoft.com/playwright:v1.49.1-jammy
FROM eclipse-temurin:21-jre-jammy

RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs

RUN apt-get update && apt-get install -y \
    # General dependencies
    wget \
    gnupg \
    libgconf-2-4 \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libx11-6 \
    libxcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libxshmfence1 \
    xdg-utils \
    # WebKit specific
    libwoff1 \
    libharfbuzz-icu0 \
    gstreamer1.0-libav \
    libvpx7 \
    # Video processing dependencies
    ffmpeg \
    # Clean up
    && rm -rf /var/lib/apt/lists/*

# -----------------------------------------------------------
# 2. Set workdir and copy ONLY package.json/package-lock.json
#    for installing npm modules. This allows Docker to cache
#    the "npm install" layer unless these files change.
# -----------------------------------------------------------
WORKDIR /app
COPY package*.json ./

# -----------------------------------------------------------
# 3. Install node modules
# -----------------------------------------------------------
RUN npm install

# -----------------------------------------------------------
# 4. Install Playwright browsers AFTER npm install
#    (still referencing the same node_modules folder)
# -----------------------------------------------------------
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN npx playwright install chromium
RUN npx playwright install-deps chromium

# -----------------------------------------------------------
# 5. Copy the rest of your application code
#    (changes here won't force the "npm install" step to re-run)
# -----------------------------------------------------------
COPY . .

# -----------------------------------------------------------
# 6. Environment variables and ENTRYPOINT
# -----------------------------------------------------------
ENV FIREBASE_DATABASE_URL="https://rabbitize-default-rtdb.firebaseio.com"
ENV NODE_ENV=production
ENV UV_THREADPOOL_SIZE=2

# Set RABBITIZE_PASSWORD at deploy time to enable login protection.
# Example: docker run -e RABBITIZE_PASSWORD=mysecret -p 3037:3037 rabbitize
# Leave unset (default) to run without auth (local dev).
ENV RABBITIZE_PASSWORD=""

EXPOSE 3037

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD node -e "require('http').get('http://localhost:3037/status', r => process.exit(r.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))"

ENTRYPOINT ["node", "src/index.js"]

