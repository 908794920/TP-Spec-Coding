#!/usr/bin/env node
// 本地工作台依赖入口：把根 node_modules 准备到与 package-lock.json 一致。
// 边界与 workbench-manager.mjs / workbench-dev.mjs 相同：不升级 Base、不写 Runtime/Task 事实、
// 不迁移业务项目、不运行测试。启动器按设计不安装依赖，安装只由本入口显式执行。
import { execSync, spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const manifestPath = join(root, 'package.json');
const lockPath = join(root, 'package-lock.json');
const requirementsPath = join(root, 'requirements.txt');
const modulesPath = join(root, 'node_modules');
// 安装指纹放在 workbench-logs/ 而不是 node_modules/：npm ci 会清空 node_modules，
// 指纹放在里面会被任何一次依赖安装（含用户手动 npm ci）抹掉，导致下次误判为"无记录"。
const logsPath = join(root, 'workbench-logs');
const stampPath = join(logsPath, 'install-state.json');
const managedRecordPath = join(logsPath, 'manager.json');
const stampSchema = 'tp-spec.workbench-install/v1';
const npmInstallCommand = 'npm ci --no-audit --no-fund';

const options = { force: false, build: false, python: false };
for (const arg of process.argv.slice(2)) {
  if (arg === '--help' || arg === '-h') { usage(); process.exit(0); }
  else if (arg === '--force') options.force = true;
  else if (arg === '--build') options.build = true;
  else if (arg === '--python') options.python = true;
  else { console.error(`未知参数：${arg}`); usage(); process.exit(2); }
}

function usage() {
  console.log([
    '用法（Windows 上可双击 ui\\install.cmd）：',
    '  node ui/workbench-install.mjs [--force] [--build] [--python]',
    '',
    '  --force   即使已记录同一锁文件也重装',
    '  --build   安装后额外执行 npm run build（产出 ui/workbench/dist/）',
    '  --python  额外执行 python -m pip install -r requirements.txt',
    '',
    '首次加载、以及依赖或锁文件变化后运行本入口；完成后用 ui\\start.cmd 启动。',
  ].join('\n'));
}

const sha256 = buffer => createHash('sha256').update(buffer).digest('hex');
const shortSha = value => (typeof value === 'string' && value.length >= 12 ? `${value.slice(0, 12)}…` : '未知');

function readJson(path) {
  return JSON.parse(readFileSync(path, 'utf8'));
}

function readStamp() {
  try { return readJson(stampPath); }
  catch { return null; }
}

function nodeSupported(version) {
  const [major, minor] = version.split('.').map(Number);
  return (major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22;
}

function pythonExecutable() {
  if (process.env.TP_SPEC_PYTHON) return process.env.TP_SPEC_PYTHON;
  for (const base of [process.env.VIRTUAL_ENV, join(root, '.venv')].filter(Boolean)) {
    const file = process.platform === 'win32' ? join(base, 'Scripts', 'python.exe') : join(base, 'bin', 'python');
    if (existsSync(file)) return file;
  }
  return process.platform === 'win32' ? 'python' : 'python3';
}

function npmVersion() {
  try { return execSync('npm --version', { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim(); }
  catch { return 'unknown'; }
}

function run(commandLine, label) {
  return new Promise((resolve, reject) => {
    const child = spawn(commandLine, { cwd: root, stdio: 'inherit', shell: true });
    child.once('error', error => reject(new Error(`${label} 无法启动：${error.message}`)));
    child.once('exit', code => (code === 0 ? resolve() : reject(new Error(`${label} 退出码 ${code ?? '未知'}`))));
  });
}

function installReason(stamp, lockSha) {
  if (!existsSync(modulesPath)) return 'FRESH';
  if (options.force) return 'FORCED';
  if (!stamp || typeof stamp.lock_sha256 !== 'string') return 'NO_RECORD';
  if (stamp.lock_sha256 !== lockSha) return 'LOCK_CHANGED';
  if (!existsSync(join(modulesPath, 'vite', 'package.json'))) return 'INCOMPLETE';
  return '';
}

function reasonText(reason, stamp, lockSha) {
  if (reason === 'FRESH') return '尚未安装（无 node_modules）';
  if (reason === 'FORCED') return '按 --force 强制重装';
  if (reason === 'NO_RECORD') return '缺少本入口的安装记录，按锁文件重装一次以确保一致（之后自动跳过）';
  if (reason === 'LOCK_CHANGED') return `package-lock.json 已变化（记录 ${shortSha(stamp?.lock_sha256)} → 现在 ${shortSha(lockSha)}）`;
  if (reason === 'INCOMPLETE') return '已有依赖缺少 vite，按锁文件重建';
  return '未识别原因';
}

function managedInstancePid() {
  try {
    const record = readJson(managedRecordPath);
    const pid = Number(record.pid);
    if (!Number.isInteger(pid) || pid <= 0) return 0;
    process.kill(pid, 0);
    return pid;
  } catch { return 0; }
}

async function verifyVite() {
  try { await import('vite'); }
  catch (error) {
    throw new Error(`前端依赖不可加载（${error.message}）；请重试 ui\\install.cmd --force，并确认 npm registry 可达`);
  }
}

function writeStamp(lockSha, manifest) {
  mkdirSync(logsPath, { recursive: true });
  writeFileSync(stampPath, `${JSON.stringify({
    schema: stampSchema,
    root,
    lock_sha256: lockSha,
    node: process.versions.node,
    npm: npmVersion(),
    engine: manifest.engines?.node ?? '',
    command: npmInstallCommand,
    installed_at: new Date().toISOString(),
  }, null, 2)}\n`, 'utf8');
}

async function main() {
  console.log(`工作台源码根：${root}`);
  if (!existsSync(manifestPath) || !existsSync(lockPath)) {
    throw new Error('缺少 package.json 或 package-lock.json；精确依赖以锁文件为准，请先确认检出完整');
  }
  const manifest = readJson(manifestPath);
  if (!nodeSupported(process.versions.node)) {
    throw new Error(`当前 Node.js ${process.versions.node} 不满足 ${manifest.engines?.node ?? '依赖要求'}；请安装 20.19+ 或 22.12+`);
  }
  const lockSha = sha256(readFileSync(lockPath));
  const stamp = readStamp();
  const reason = installReason(stamp, lockSha);
  if (reason) {
    const runningPid = options.force ? 0 : managedInstancePid();
    if (runningPid) {
      throw new Error(`受管工作台仍在运行（PID ${runningPid}）；请先运行 ui\\stop.cmd 再安装，避免在运行中替换依赖`);
    }
    console.log(`需要准备前端依赖：${reasonText(reason, stamp, lockSha)}`);
    if (existsSync(modulesPath)) console.log('  按锁文件重建 node_modules（npm ci 会先清理已安装目录）。');
    await run(npmInstallCommand, 'npm ci');
    await verifyVite();
    writeStamp(lockSha, manifest);
    console.log(`前端依赖安装完成（锁文件 ${shortSha(lockSha)}，Node ${process.versions.node}）。`);
  } else {
    await verifyVite();
    console.log('前端依赖已与 package-lock.json 一致，跳过安装。');
    console.log(`  锁文件 ${shortSha(lockSha)}   安装时间 ${stamp?.installed_at ?? '未知'}   需要重装时用 --force`);
  }
  if (options.build) {
    console.log('执行 npm run build（产出 ui/workbench/dist/）…');
    await run('npm run build', 'npm run build');
  }
  if (options.python) {
    const python = pythonExecutable();
    console.log(`执行 "${python}" -m pip install -r requirements.txt …`);
    await run(`"${python}" -m pip install -r requirements.txt`, 'pip install');
  }
  console.log('');
  console.log('下一步：ui\\start.cmd 启动工作台（默认 http://127.0.0.1:5173 ）。');
  if (!options.python && existsSync(requirementsPath)) {
    console.log('Python 依赖未改动；如需一并准备：ui\\install.cmd --python');
  }
}

main().catch(error => {
  console.error(`依赖安装失败：${error.message}`);
  process.exit(1);
});
