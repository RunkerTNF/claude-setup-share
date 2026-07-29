#!/usr/bin/env node

const { execFileSync } = require('child_process');

let input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => { input += chunk; });
process.stdin.on('end', () => {
  let data = {};
  try {
    data = JSON.parse(input);
  } catch {
    data = {};
  }

  const cwd = (data.workspace && data.workspace.current_dir) || data.cwd || '';
  const home = process.env.HOME || process.env.USERPROFILE || '';
  const displayCwd = home && cwd.startsWith(home)
    ? '~' + cwd.slice(home.length).replace(/\\/g, '/')
    : cwd.replace(/\\/g, '/');
  const model = (data.model && data.model.display_name) || '';
  const used = data.context_window && data.context_window.used_percentage;
  const usedPct = used == null ? null : Math.round(used) + '%';
  const fiveHour = data.rate_limits && data.rate_limits.five_hour;
  const fiveHourPct = fiveHour == null
    ? null
    : Math.round(fiveHour.used_percentage) + '%';

  let branch = null;
  if (cwd) {
    try {
      branch = execFileSync(
        'git',
        ['-C', cwd, 'branch', '--show-current'],
        {
          encoding: 'utf8',
          stdio: ['ignore', 'pipe', 'ignore'],
          timeout: 2000,
          env: { ...process.env, GIT_OPTIONAL_LOCKS: '0' }
        }
      ).trim() || null;
    } catch {
      branch = null;
    }
  }

  const parts = [];
  if (displayCwd) parts.push('\x1b[34m' + displayCwd + '\x1b[0m');
  if (model) parts.push('\x1b[33m' + model + '\x1b[0m');
  if (usedPct) parts.push('ctx:' + usedPct);
  if (fiveHourPct) parts.push('5h:' + fiveHourPct);
  if (branch) parts.push('\x1b[32m' + branch + '\x1b[0m');
  process.stdout.write(parts.join('  '));
});
