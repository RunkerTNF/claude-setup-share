#!/usr/bin/env node

const { execSync } = require('child_process');

let input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => { input += chunk; });
process.stdin.on('end', () => {
  let data = {};
  try { data = JSON.parse(input); } catch (e) {}

  // Current directory
  const cwd = (data.workspace && data.workspace.current_dir) || data.cwd || '';
  const home = process.env.HOME || process.env.USERPROFILE || '';
  const displayCwd = cwd.startsWith(home)
    ? '~' + cwd.slice(home.length).replace(/\\/g, '/')
    : cwd.replace(/\\/g, '/');

  // Model
  const model = (data.model && data.model.display_name) || '';

  // Context usage percentage
  const usedPct = (data.context_window && data.context_window.used_percentage != null)
    ? Math.round(data.context_window.used_percentage) + '%'
    : null;

  // 5-hour rate limit
  const fiveHourPct = (data.rate_limits && data.rate_limits.five_hour != null)
    ? Math.round(data.rate_limits.five_hour.used_percentage) + '%'
    : null;

  // Git branch
  let branch = null;
  try {
    branch = execSync('git -C "' + cwd + '" branch --show-current 2>/dev/null', {
      stdio: ['ignore', 'pipe', 'ignore'],
      timeout: 2000,
      env: { ...process.env, GIT_OPTIONAL_LOCKS: '0' }
    }).toString().trim();
    if (!branch) branch = null;
  } catch (e) {
    branch = null;
  }

  // Assemble parts
  const parts = [];

  if (displayCwd) parts.push('\x1b[34m' + displayCwd + '\x1b[0m');
  if (model)      parts.push('\x1b[33m' + model + '\x1b[0m');
  if (usedPct)    parts.push('ctx:' + usedPct);
  if (fiveHourPct) parts.push('5h:' + fiveHourPct);
  if (branch)     parts.push('\x1b[32m' + branch + '\x1b[0m');

  process.stdout.write(parts.join('  '));
});
