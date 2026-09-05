#!/usr/bin/env node
// Keep ownership of the processes we start, including their descendants.
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

const root = fileURLToPath(new URL('..', import.meta.url));
const [project, rawPort] = process.argv.slice(2);
const port = Number(rawPort);
const children = [];
let stopping = false;

function signalGroup(child, signal) {
  if (!child.pid) return;
  try {
    // detached creates a new process group on the macOS/Linux hosts dev.sh uses.
    process.kill(-child.pid, signal);
  } catch (error) {
    if (error.code !== 'ESRCH') console.error(`清理子进程失败: ${error.message}`);
  }
}

async function shutdown(code) {
  if (stopping) return;
  stopping = true;
  for (const child of children) signalGroup(child, 'SIGTERM');
  await Promise.race([
    Promise.all(children.map((child) => child.closed)),
    delay(2000),
  ]);
  // A descendant can outlive the direct child or ignore SIGTERM.
  for (const child of children) signalGroup(child, 'SIGKILL');
  process.exit(code);
}

process.on('SIGINT', () => void shutdown(130));
process.on('SIGTERM', () => void shutdown(143));

function start(command, args, name) {
  const child = spawn(command, args, { stdio: 'inherit', detached: true });
  child.closed = new Promise((resolve) => child.once('close', resolve));
  children.push(child);
  child.once('error', (error) => {
    console.error(`${name} 启动失败: ${error.message}`);
    void shutdown(1);
  });
  child.once('exit', (code, signal) => {
    if (stopping) return;
    if (name === 'Studio') console.error(`Studio 已退出 (${signal ?? code})`);
    void shutdown(name === 'Studio' ? code || 1 : code ?? 1);
  });
  return child;
}

async function checkPort() {
  const server = createServer();
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen({ host: '127.0.0.1', port, exclusive: true }, resolve);
  });
  await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
}

try {
  if (!project || !/^\d+$/.test(rawPort ?? '') || port < 1 || port > 65535) {
    throw new Error('需要项目路径和有效 STUDIO_PORT (1–65535)');
  }
  try {
    await checkPort();
  } catch (error) {
    throw new Error(`Studio 端口 ${port} 无法使用，请检查已有服务或设置 STUDIO_PORT: ${error.message}`);
  }
  if (!stopping) {
    console.log(`==> 启动 OpenWrite Studio: http://127.0.0.1:${port} (legacy default project: ${project})`);
    const studio = start(`${root}/.venv/bin/openwrite`, [
      'studio', '--project', project, '--port', String(port), '--no-open',
    ], 'Studio');
    const deadline = Date.now() + 30_000;
    let ready = false;
    while (!stopping && Date.now() < deadline) {
      try {
        const response = await fetch(`http://127.0.0.1:${port}/api/health`, {
          signal: AbortSignal.timeout(2000),
        });
        await response.body?.cancel();
        if (response.ok && studio.exitCode === null && studio.signalCode === null) {
          ready = true;
          break;
        }
      } catch { /* Retry only while our own Studio process is alive. */ }
      await delay(500);
    }
    if (!stopping) {
      if (!ready) throw new Error('Studio 在 30 秒内未通过健康检查，停止启动');
      console.log('==> 启动 dsh web: http://127.0.0.1:3080');
      start(`${root}/node_modules/.bin/dsh`, ['web'], 'dsh');
    }
  }
} catch (error) {
  console.error(error.message);
  await shutdown(1);
}
