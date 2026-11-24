import { record } from './facts';
import type { CloseoutData, DetailData, Envelope, GlobalData, Health, ProjectData, SkillDocumentData, TaskData, TaskNote, WorkflowData } from './types';

export class WorkbenchApiError extends Error {
  constructor(public readonly status: number, public readonly code: string | undefined, message: string) { super(message); }
}

async function request(path: string, options: RequestInit): Promise<unknown> {
  const response = await fetch(path, { cache: 'no-store', ...options });
  let value: unknown;
  try { value = await response.json(); }
  catch { throw new Error(`接口未返回 JSON（HTTP ${response.status}），请使用根目录 npm run dev 启动两端`); }
  const payload = record(value), error = record(payload.error);
  if (!response.ok) {
    const code = typeof error.code === 'string' ? error.code : undefined;
    const fallback = options.method === 'PUT' ? '保存失败' : '读取失败';
    throw new WorkbenchApiError(response.status, code, `${code ?? response.status}：${error.message ?? fallback}`);
  }
  if (payload.schema !== 'tp-spec.workbench/v1') throw new Error('接口与页面展示契约不匹配，请检查活动源码和启动目录');
  return value;
}
const get = (path: string, signal?: AbortSignal) => request(path, { method: 'GET', signal });

export async function getGlobalEnvelope<T>(
  path: string, values: Record<string, string | number | undefined>, signal?: AbortSignal,
): Promise<Envelope<T> & { context: null }> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined) query.set(key, String(value));
  }
  const value = await get(`${path}?${query}`, signal);
  const payload = record(value), read = record(payload.read);
  if (payload.context !== null) throw new Error('全局接口返回了项目上下文，已拒绝显示');
  if (typeof read.started_at !== 'string' || typeof read.completed_at !== 'string') {
    throw new Error('接口响应缺少读取信息，已拒绝显示');
  }
  if (!payload.data || typeof payload.data !== 'object' || Array.isArray(payload.data)) {
    throw new Error('接口响应缺少数据，保留上次成功结果');
  }
  return value as Envelope<T> & { context: null };
}

/** Reject mismatched identities before any response can become page state. */
export function validateEnvelope<T>(value: unknown, key?: string, taskId?: string): Envelope<T> {
  const payload = record(value), read = record(payload.read), context = record(payload.context), data = record(payload.data);
  if (!Object.keys(data).length || typeof read.started_at !== 'string' || typeof read.completed_at !== 'string'
      || !['complete', 'partial'].includes(String(read.completeness))) throw new Error('接口响应缺少数据或读取信息，保留上次成功结果');
  if (key !== undefined && context.context_key !== key) throw new Error('接口返回其他项目/工作区上下文，已拒绝显示');
  if (key === undefined && payload.context !== null) throw new Error('全局接口返回了任务上下文，已拒绝显示');
  if (taskId !== undefined && (data.task_id ?? record(data.task).task_id) !== taskId) throw new Error('接口返回其他 Task，已拒绝显示');
  return value as Envelope<T>;
}
const projectPath = (key: string) => `/api/projects/${encodeURIComponent(key)}`;
const taskNotePath = (key: string, id: string) => `${projectPath(key)}/tasks/${encodeURIComponent(id)}/note`;
function validateTaskNote(value: unknown, key: string, id: string): TaskNote {
  const payload = record(value);
  if (payload.context_key !== key || payload.task_id !== id || typeof payload.note !== 'string'
      || typeof payload.revision !== 'string' || !payload.revision) throw new Error('任务备注响应的身份或格式不匹配');
  return { context_key: key, task_id: id, note: payload.note, revision: payload.revision };
}

export const api = {
  skillDocument: async (id: string, signal?: AbortSignal, path = '', allowDisabled = false): Promise<SkillDocumentData> => {
    const query = new URLSearchParams({ path });
    if (allowDisabled) query.set('allow_disabled', '1');
    const value = record(await get(`/api/skill-documents/${encodeURIComponent(id)}?${query}`, signal));
    const expectedSource = id.startsWith('external:local:') ? 'external' : 'builtin';
    if (value.id !== id || value.source_kind !== expectedSource
        || typeof value.content !== 'string' || typeof value.path !== 'string' || !value.path
        || typeof value.source_root !== 'string' || !value.source_root
        || typeof value.entry_path !== 'string' || !value.entry_path
        || typeof value.content_sha256 !== 'string' || !/^[a-f0-9]{64}$/i.test(value.content_sha256)
        || !['name', 'entry_sha256', 'upstream', 'version'].every(key => typeof value[key] === 'string')
        || !(value.status === 'available' && value.enabled === true
          || allowDisabled && value.status === 'disabled' && value.enabled === false)) {
      throw new Error('设定文档响应的身份、来源或状态不匹配');
    }
    return value as unknown as SkillDocumentData;
  },
  health: async (signal?: AbortSignal) => {
    const value = await get('/api/health', signal);
    const health = record(value);
    if (health.ready !== true || (health.runtime_read_only ?? health.read_only) !== true) throw new Error('工作台服务未就绪');
    return value as Health;
  },
  global: async (signal?: AbortSignal) => {
    const result = validateEnvelope<GlobalData>(await get('/api/global', signal));
    if (!Array.isArray(result.data.contexts) || result.data.contexts.some(c => !c || typeof c.context_key !== 'string')) throw new Error('项目索引响应格式错误');
    return result;
  },
  project: async (key: string, signal?: AbortSignal, includeNotes = false) => {
    const result = validateEnvelope<ProjectData>(await get(projectPath(key) + (includeNotes ? '?notes=1' : ''), signal), key);
    if (!Array.isArray(result.data.task_index) || result.data.task_index.some(row => !row || typeof row.task_id !== 'string' || typeof row.title !== 'string' || typeof row.state !== 'string')) throw new Error('任务索引响应格式错误');
    return result;
  },
  task: async (key: string, id: string, signal?: AbortSignal) =>
    validateEnvelope<TaskData>(await get(`${projectPath(key)}/tasks/${encodeURIComponent(id)}`, signal), key, id),
  taskRoute: async (key: string, id: string, signal?: AbortSignal) =>
    validateEnvelope<{ task_id: string; workflow: WorkflowData }>(await get(`${projectPath(key)}/tasks/${encodeURIComponent(id)}/route`, signal), key, id),
  taskNote: async (key: string, id: string, signal?: AbortSignal) =>
    validateTaskNote(await get(taskNotePath(key, id), signal), key, id),
  saveTaskNote: async (key: string, id: string, note: string, revision: string) =>
    validateTaskNote(await request(taskNotePath(key, id), {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-Workbench-Request': 'task-note' },
      body: JSON.stringify({ note, revision }),
    }), key, id),
  details: async (key: string, id: string, signal?: AbortSignal) =>
    validateEnvelope<DetailData>(await get(`${projectPath(key)}/tasks/${encodeURIComponent(id)}/details`, signal), key, id),
  closeout: async (key: string, id: string, signal?: AbortSignal) =>
    validateEnvelope<CloseoutData>(await get(`${projectPath(key)}/tasks/${encodeURIComponent(id)}/closeout`, signal), key, id),
};
