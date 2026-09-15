#!/usr/bin/env node
// One foreground launcher owns Vite and one Python child. No install, tests or Runtime writes.
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { existsSync, realpathSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';

const root = realpathSync(join(dirname(fileURLToPath(import.meta.url)), '..'));
const args = process.argv.slice(2);
const options = { port: 5173, apiPort: 0 };
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--help' || args[i] === '-h') {
    console.log('npm run dev -- [--port 5173] [--api-port 0]\nTP_SPEC_PYTHON: Python executable (a path, not a shell command). Ctrl+C stops both services.');
    process.exit(0);
  }
  const name = args[i] === '--port' ? 'port' : args[i] === '--api-port' ? 'apiPort' : '';
  const value = args[++i];
  if (!name || !/^\d+$/.test(value ?? '') || Number(value) > 65535 || (name === 'port' && Number(value) === 0)) {
    console.error('参数无效；使用 npm run dev -- --help 查看启动选项。');
    process.exit(1);
  }
  options[name] = Number(value);
}
const [major, minor] = process.versions.node.split('.').map(Number);
if (!(major === 20 && minor >= 19 || major === 22 && minor >= 12 || major > 22)) {
  console.error(`当前 Node.js ${process.versions.node} 不满足依赖要求，请使用 20.19+ 或 22.12+。`);
  process.exit(1);
}
function pythonExecutable() {
  if (process.env.TP_SPEC_PYTHON) return process.env.TP_SPEC_PYTHON;
  for (const base of [process.env.VIRTUAL_ENV, join(root, '.venv')].filter(Boolean)) {
    const file = process.platform === 'win32' ? join(base, 'Scripts', 'python.exe') : join(base, 'bin', 'python');
    if (existsSync(file)) return file;
  }
  return process.platform === 'win32' ? 'python' : 'python3';
}
let child, vite, lines;
let closing = false;
let shutdownPromise;
const startupAbort = new AbortController();

async function stopPython() {
  if (!child?.pid) return;
  const pid = child.pid;
  if (process.platform === 'win32') {
    if (child.exitCode !== null || child.signalCode !== null) return;
    // Only this launcher's own PID tree. Never kill by executable name or by port.
    await new Promise(resolve => {
      const killer = spawn('taskkill', ['/PID', String(pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
      killer.once('error', () => { child.kill(); resolve(); });
      killer.once('exit', resolve);
    });
  } else {
    try { process.kill(-pid, 'SIGTERM'); } catch (error) { if (error.code !== 'ESRCH') throw error; }
    // A resolver can have a short-lived subprocess. Kill only our private group if needed.
    await new Promise(resolve => {
      let timer;
      const done = () => { clearTimeout(timer); resolve(); };
      if (child.exitCode !== null || child.signalCode !== null) return done();
      child.once('exit', done);
      timer = setTimeout(() => {
        child.removeListener('exit', done);
        try { process.kill(-pid, 'SIGKILL'); } catch (error) { if (error.code !== 'ESRCH') console.error(error.message); }
        done();
      }, 2000);
    });
  }
}
function shutdown(code = 0) {
  if (shutdownPromise) return shutdownPromise;
  closing = true;
  startupAbort.abort();
  process.exitCode = code;
  shutdownPromise = (async () => {
    try { await vite?.close(); }
    catch (error) { console.error(`前端关闭失败：${error.message}`); process.exitCode = 1; }
    finally { await stopPython(); lines?.close(); }
  })();
  return shutdownPromise;
}
process.on('SIGINT', () => { void shutdown(0); });
process.on('SIGTERM', () => { void shutdown(0); });

async function start() {
  let createServer;
  try { ({ createServer } = await import('vite')); }
  catch { throw new Error('前端依赖未安装或不可加载。请在项目根目录执行 npm ci；启动器不会自动安装或运行测试。'); }
  if (closing) return;
  const instance = randomUUID();
  child = spawn(pythonExecutable(), ['-B', '-u', '-m', 'cli.workbench.server', '--port', String(options.apiPort)], {
    cwd: root, shell: false, windowsHide: true, detached: process.platform !== 'win32',
    stdio: ['ignore', 'pipe', 'inherit'],
    env: { ...process.env, TP_SPEC_BASE_ROOT: root, TP_SPEC_WORKBENCH_INSTANCE: instance, PYTHONIOENCODING: 'utf-8' },
  });
  lines = createInterface({ input: child.stdout });
  const ready = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => finish(new Error('Python API 未在启动窗口内就绪；请检查上述错误、依赖与端口。')), 15000);
    const onError = error => finish(new Error(`Python 启动失败：${error.message}；可用 TP_SPEC_PYTHON 指定解释器路径。`));
    const onExit = (code, signal) => finish(new Error(`Python API 在就绪前退出（${signal ?? code}）。`));
    const onAbort = () => finish(new Error('启动已取消'));
    const onLine = line => {
      let value;
      try { value = JSON.parse(line); } catch { console.log(`[Python] ${line}`); return; }
      if (value.event !== 'workbench-ready') return;
      if (value.instance_id !== instance || value.pid !== child.pid || !Number.isInteger(value.port) || value.port < 1 || value.port > 65535 ||
          realpathSync(value.source_root) !== root) return finish(new Error('Python 就绪身份与本次启动不一致，拒绝连接其他副本。'));
      finish(null, value);
    };
    function finish(error, value) {
      clearTimeout(timer);
      child.removeListener('error', onError);
      child.removeListener('exit', onExit);
      lines.removeListener('line', onLine);
      startupAbort.signal.removeEventListener('abort', onAbort);
      error ? reject(error) : resolve(value);
    }
    child.once('error', onError); child.once('exit', onExit); lines.on('line', onLine);
    startupAbort.signal.addEventListener('abort', onAbort, { once: true });
  });
  if (closing) return;
  child.on('error', error => { if (!closing) { console.error(error.message); void shutdown(1); } });
  child.on('exit', (code, signal) => {
    if (!closing) { console.error(`Python API 已退出（${signal ?? code}），关闭前端。`); void shutdown(1); }
  });
  const target = `http://127.0.0.1:${ready.port}`;
  const response = await fetch(`${target}/api/health`, { signal: AbortSignal.any([startupAbort.signal, AbortSignal.timeout(5000)]) });
  const health = await response.json();
  if (!response.ok || health.instance_id !== instance || realpathSync(health.source_root) !== root || !health.read_only)
    throw new Error('Python 健康检查未确认本次只读实例。');
  if (closing) return;
  vite = await createServer({ configFile: join(root, 'ui', 'workbench', 'vite.config.ts'),
    server: { host: '127.0.0.1', port: options.port, strictPort: true, proxy: { '/api': { target } } } });
  if (closing) { await vite.close(); return; }
  vite.httpServer?.once('error', error => { if (!closing) { console.error(`前端服务错误：${error.message}`); void shutdown(1); } });
  await vite.listen();
  if (closing) { await vite.close(); return; }
  console.log(`TP-Spec 工作台：http://127.0.0.1:${options.port}\n源码：${root}\nPython API：${target}（PID ${child.pid}）\nCtrl+C 关闭本次两端服务。`);
}
start().catch(async error => {
  if (!closing) { console.error(`工作台启动失败：${error.message}`); await shutdown(1); }
});
