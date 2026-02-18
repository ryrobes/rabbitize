// src/utils/imageCompare.js
// Image comparison utility using pixelmatch for visual regression testing

const sharp = require('sharp');

// Cache for generated diff images (cleared on process restart)
const diffCache = new Map();
const CACHE_MAX_SIZE = 100;
const CACHE_TTL = 10 * 60 * 1000; // 10 minutes

// Lazy-loaded pixelmatch (ESM module)
let pixelmatch = null;
async function getPixelmatch() {
  if (!pixelmatch) {
    const module = await import('pixelmatch');
    pixelmatch = module.default;
  }
  return pixelmatch;
}

/**
 * Compare two images and generate a diff
 * @param {string} img1Path - Path to the baseline image
 * @param {string} img2Path - Path to the latest image
 * @param {object} options - Comparison options
 * @returns {object} - { diffPercent, diffImageBuffer, width, height, error? }
 */
async function compareImages(img1Path, img2Path, options = {}) {
  const {
    threshold = 0.1,      // Per-pixel color difference threshold (0-1)
    alpha = 0.1,          // Blending factor for unchanged pixels
    diffColor = [255, 0, 0],        // Red for differences
    diffColorAlt = [0, 255, 0],     // Green for anti-aliasing diffs
    includeAA = false     // Whether to include anti-aliasing differences
  } = options;

  try {
    // Load pixelmatch dynamically (ESM module)
    const pm = await getPixelmatch();

    // Load both images and get their metadata
    const [img1Meta, img2Meta] = await Promise.all([
      sharp(img1Path).metadata(),
      sharp(img2Path).metadata()
    ]);

    // Determine target dimensions (use the larger of the two)
    const targetWidth = Math.max(img1Meta.width, img2Meta.width);
    const targetHeight = Math.max(img1Meta.height, img2Meta.height);

    // Resize both images to the same dimensions and convert to raw RGBA
    const [img1Buffer, img2Buffer] = await Promise.all([
      sharp(img1Path)
        .resize(targetWidth, targetHeight, {
          fit: 'contain',
          background: { r: 0, g: 0, b: 0, alpha: 1 }
        })
        .ensureAlpha()
        .raw()
        .toBuffer(),
      sharp(img2Path)
        .resize(targetWidth, targetHeight, {
          fit: 'contain',
          background: { r: 0, g: 0, b: 0, alpha: 1 }
        })
        .ensureAlpha()
        .raw()
        .toBuffer()
    ]);

    // Create output buffer for diff image
    const diffBuffer = new Uint8Array(targetWidth * targetHeight * 4);

    // Run pixelmatch comparison
    const numDiffPixels = pm(
      img1Buffer,
      img2Buffer,
      diffBuffer,
      targetWidth,
      targetHeight,
      {
        threshold,
        alpha,
        diffColor,
        diffColorAlt,
        includeAA
      }
    );

    // Calculate percentage difference
    const totalPixels = targetWidth * targetHeight;
    const diffPercent = (numDiffPixels / totalPixels) * 100;

    // Convert raw diff buffer to PNG using sharp
    const diffImageBuffer = await sharp(Buffer.from(diffBuffer), {
      raw: {
        width: targetWidth,
        height: targetHeight,
        channels: 4
      }
    })
      .png()
      .toBuffer();

    return {
      diffPercent,
      diffImageBuffer,
      width: targetWidth,
      height: targetHeight,
      numDiffPixels,
      totalPixels
    };
  } catch (error) {
    return {
      error: error.message,
      diffPercent: -1,
      diffImageBuffer: null,
      width: 0,
      height: 0
    };
  }
}

/**
 * Get diff image from cache or generate it
 * @param {string} cacheKey - Unique key for this comparison
 * @param {string} img1Path - Path to baseline image
 * @param {string} img2Path - Path to latest image
 * @returns {object} - Comparison result
 */
async function getCachedDiff(cacheKey, img1Path, img2Path) {
  // Check cache
  const cached = diffCache.get(cacheKey);
  if (cached && (Date.now() - cached.timestamp) < CACHE_TTL) {
    return cached.result;
  }

  // Generate new diff
  const result = await compareImages(img1Path, img2Path);

  // Add to cache (with LRU eviction)
  if (diffCache.size >= CACHE_MAX_SIZE) {
    // Remove oldest entry
    const oldestKey = diffCache.keys().next().value;
    diffCache.delete(oldestKey);
  }

  diffCache.set(cacheKey, {
    result,
    timestamp: Date.now()
  });

  return result;
}

/**
 * Clear the diff cache
 */
function clearCache() {
  diffCache.clear();
}

/**
 * Generate a simple line-by-line diff between two text contents
 * @param {string} text1 - Baseline text
 * @param {string} text2 - Latest text
 * @returns {object} - { lines: [{type, content}...], hasChanges }
 */
function generateTextDiff(text1, text2) {
  const lines1 = text1.split('\n');
  const lines2 = text2.split('\n');
  const result = [];
  let hasChanges = false;

  // Simple LCS-based diff algorithm
  const maxLen = Math.max(lines1.length, lines2.length);
  let i = 0, j = 0;

  while (i < lines1.length || j < lines2.length) {
    if (i >= lines1.length) {
      // Remaining lines in text2 are additions
      result.push({ type: 'added', content: lines2[j], lineNum: j + 1 });
      hasChanges = true;
      j++;
    } else if (j >= lines2.length) {
      // Remaining lines in text1 are removals
      result.push({ type: 'removed', content: lines1[i], lineNum: i + 1 });
      hasChanges = true;
      i++;
    } else if (lines1[i] === lines2[j]) {
      // Lines match
      result.push({ type: 'unchanged', content: lines1[i], lineNum: i + 1 });
      i++;
      j++;
    } else {
      // Lines differ - look ahead to find matches
      let foundMatch = false;

      // Look for line1[i] in upcoming lines2
      for (let k = j + 1; k < Math.min(j + 5, lines2.length); k++) {
        if (lines1[i] === lines2[k]) {
          // Add lines2[j..k-1] as additions
          for (let l = j; l < k; l++) {
            result.push({ type: 'added', content: lines2[l], lineNum: l + 1 });
          }
          j = k;
          hasChanges = true;
          foundMatch = true;
          break;
        }
      }

      if (!foundMatch) {
        // Look for line2[j] in upcoming lines1
        for (let k = i + 1; k < Math.min(i + 5, lines1.length); k++) {
          if (lines2[j] === lines1[k]) {
            // Add lines1[i..k-1] as removals
            for (let l = i; l < k; l++) {
              result.push({ type: 'removed', content: lines1[l], lineNum: l + 1 });
            }
            i = k;
            hasChanges = true;
            foundMatch = true;
            break;
          }
        }
      }

      if (!foundMatch) {
        // No nearby match found, treat as a change
        result.push({ type: 'removed', content: lines1[i], lineNum: i + 1 });
        result.push({ type: 'added', content: lines2[j], lineNum: j + 1 });
        hasChanges = true;
        i++;
        j++;
      }
    }
  }

  return { lines: result, hasChanges };
}

/**
 * Convert diff result to HTML
 * @param {object} diff - Result from generateTextDiff
 * @returns {string} - HTML string
 */
function diffToHtml(diff) {
  if (!diff.hasChanges) {
    return '<div class="dom-diff-empty">No changes detected</div>';
  }

  const lines = diff.lines.map(line => {
    const escapedContent = escapeHtml(line.content);
    switch (line.type) {
      case 'added':
        return `<div class="dom-diff-line dom-diff-added"><span class="dom-diff-symbol">+</span>${escapedContent}</div>`;
      case 'removed':
        return `<div class="dom-diff-line dom-diff-removed"><span class="dom-diff-symbol">-</span>${escapedContent}</div>`;
      default:
        return `<div class="dom-diff-line dom-diff-unchanged"><span class="dom-diff-symbol"> </span>${escapedContent}</div>`;
    }
  });

  return `<div class="dom-diff-container">${lines.join('\n')}</div>`;
}

/**
 * Escape HTML special characters
 * @param {string} text - Text to escape
 * @returns {string} - Escaped text
 */
function escapeHtml(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

/**
 * Determine status based on diff percentage
 * @param {number} diffPercent - Percentage of pixels that differ
 * @returns {string} - 'pass', 'warn', or 'fail'
 */
function getStatusFromDiff(diffPercent) {
  if (diffPercent < 0) return 'error';
  if (diffPercent < 1) return 'pass';
  if (diffPercent < 5) return 'warn';
  return 'fail';
}

module.exports = {
  compareImages,
  getCachedDiff,
  clearCache,
  generateTextDiff,
  diffToHtml,
  getStatusFromDiff
};
