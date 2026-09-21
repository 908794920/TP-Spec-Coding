// Local Windows entrypoint; source paths are resolved from this file, never machine constants.
import { fork, spawn } from 'node:child_process';
import { createServer, createConnection } from 'node:net';
import { mkdir, readFile, writeFile, unlink, open } from 'node:fs/promises';
import { realpathSync, openSync, closeSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash, randomUUID } from 'node:crypto';

const root = realpathSync(join(dirname(fileURLToPath(import.meta.url)), '..'));
const directory = join(root, 'workbench-logs');
const statePath = join(directory, 'manager.json');
const lockPath = join(directory, 'manager.lock');
const pipe = `\\\\.\\pipe\\tp-spec-workbench-${createHash('sha256').update(root.toLowerCase()).digest('hex').slice(0, 24)}`;
const action = process.argv[2];
const port = Number(process.env.TP_SPEC_WORKBENCH_PORT || 5173);
if (process.platform !== 'win32' || !['start', 'restart', 'stop', '--serve'].includes(action) || !Number.isInteger(port) || port < 1 || port > 65535) {
  console.error('Usage on Windows: node ui/workbench-manager.mjs start|restart|stop');
  process.exit(1);
}

async function request(command, state) {
  return new Promise((resolve, reject) => {
    const socket = createConnection(pipe);
    let buffer = '';
    socket.setTimeout(5000, () => socket.destroy(new Error('Manager response timed out')));
    socket.on('error', reject);
    socket.on('connect', () => socket.write(JSON.stringify({ command, token: state.token }) + '\n'));
    socket.on('data', chunk => {
      buffer += chunk;
      if (!buffer.includes('\n')) return;
      socket.end();
      try {
        const result = JSON.parse(buffer.split('\n')[0]);
        if (result.root !== root || result.token !== state.token || result.error) throw new Error(result.error || 'Instance identity mismatch');
        resolve(result);
      } catch (error) { reject(error); }
    });
    socket.on('end', () => { if (!buffer.includes('\n')) reject(new Error('Manager disconnected')); });
  });
}

async function current() {
  let state;
  try { state = JSON.parse(await readFile(statePath, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return null; throw error; }
  if (state.root !== root || typeof state.token !== 'string') throw new Error('Invalid manager record; inspect workbench-logs/manager.json');
  try { return await request('status', state); }
  catch (error) {
    if (!['ENOENT', 'ECONNREFUSED'].includes(error.code)) throw error;
    // A dead private control endpoint is stale; never kill a recycled PID or a port owner.
    try { await unlink(statePath); } catch (cleanup) { if (cleanup.code !== 'ENOENT') throw cleanup; }
    return null;
  }
}

async function serve() {
  const token = randomUUID();
  let child, ready = false, stopping = false;
  const state = { root, token, port, pid: process.pid };
  const server = createServer(socket => {
    let buffer = '';
    socket.setTimeout(5000, () => socket.destroy());
    socket.on('error', () => {});
    socket.on('data', chunk => {
      buffer += chunk;
      if (buffer.length > 4096) return socket.destroy();
      if (!buffer.includes('\n')) return;
      let message;
      try { message = JSON.parse(buffer.split('\n')[0]); } catch { return socket.destroy(); }
      if (message.token !== token) return socket.destroy();
      if (message.command === 'status') socket.end(JSON.stringify({ ...state, ready, stopping }) + '\n');
      else if (message.command === 'stop') {
        stopping = true;
        child?.send({ action: 'stop' });
        socket.end(JSON.stringify({ ...state, stopping }) + '\n');
      } else socket.destroy();
    });
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(pipe, resolve); });
  await writeFile(statePath, JSON.stringify(state), { mode: 0o600 });
  child = fork(join(root, 'scripts', 'workbench-dev.mjs'), ['--port', String(port)], {
    cwd: root, windowsHide: true, stdio: ['ignore', 'inherit', 'inherit', 'ipc'],
  });
  child.on('message', message => {
    if (message?.event === 'ready' && message.root === root && message.port === port) { state.instance = message.instance; ready = true; }
  });
  child.on('error', error => console.error(error.message));
  child.on('exit', async code => {
    try { await unlink(statePath); } catch (error) { if (error.code !== 'ENOENT') console.error(error.message); }
    server.close(() => process.exit(code || 0));
  });
}

const pause = () => new Promise(resolve => setTimeout(resolve, 200));
async function stop(state) {
  await request('stop', state);
  for (let i = 0; i < 75; i++) { if (!await current()) return; await pause(); }
  throw new Error('Shutdown has not completed. Inspect workbench-logs; no unrelated process was terminated.');
}
async function start() {
  let state = await current();
  if (!state) {
    const output = openSync(join(directory, 'workbench.log'), 'a');
    try {
      const daemon = spawn(process.execPath, [fileURLToPath(import.meta.url), '--serve'], {
        cwd: root, detached: true, windowsHide: true, stdio: ['ignore', output, output],
      });
      await new Promise((resolve, reject) => { daemon.once('spawn', resolve); daemon.once('error', reject); });
      daemon.unref();
    } finally { closeSync(output); }
  }
  for (let i = 0; i < 150; i++) {
    state = await current();
    if (state?.ready && !state.stopping) {
      const url = `http://127.0.0.1:${state.port}/`;
      const response = await fetch(`${url}api/health`, { signal: AbortSignal.timeout(5000) });
      const health = await response.json();
      if (!response.ok || health.instance_id !== state.instance || realpathSync(health.source_root) !== root || !health.read_only) throw new Error('Workbench health identity mismatch');
      console.log(`Workbench ready: ${url}`);
      // Use Windows URL association; hiding a rundll32 launcher can suppress browser activation.
      // The helper is hidden, but the requested browser window uses its normal visible mode.
      await new Promise((resolve, reject) => {
        const browser = spawn('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
          "$ErrorActionPreference = 'Stop'; Start-Process -FilePath $env:TP_SPEC_OPEN_URL"], {
          windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'],
          env: { ...process.env, TP_SPEC_OPEN_URL: url },
        });
        let errorText = '';
        browser.stderr.on('data', chunk => { errorText += chunk; });
        browser.once('error', reject);
        browser.once('exit', code => code === 0 ? resolve() : reject(new Error(
          `Workbench is running, but opening the default browser failed: ${errorText.trim() || code}. Open ${url}`)));
      });
      return;
    }
    await pause();
  }
  state = await current();
  if (state) await stop(state);
  throw new Error('Startup failed; see workbench-logs/workbench.log. Check dependencies and port ownership.');
}

await mkdir(directory, { recursive: true });
if (action === '--serve') {
  serve().catch(error => { console.error(error.message); process.exit(1); });
} else {
  let lock;
  try {
    lock = await open(lockPath, 'wx');
    if (action === 'stop' || action === 'restart') {
      const state = await current();
      if (state) { await stop(state); console.log('Workbench stopped.'); }
      else console.log('No managed workbench is running.');
    }
    if (action !== 'stop') await start();
  } catch (error) {
    console.error(error.code === 'EEXIST' ? 'Another management operation is active. If it was interrupted, remove workbench-logs/manager.lock after checking.' : error.message);
    process.exitCode = 1;
  } finally {
    if (lock) { await lock.close(); await unlink(lockPath); }
  }
}
