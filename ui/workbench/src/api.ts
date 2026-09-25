import { record } from './facts';
import type { CloseoutData, DetailData, Envelope, GlobalData, Health, ProjectData, TaskData } from './types';

async function get(path: string, signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(path, { method: 'GET', cache: 'no-store', signal });
  let value: unknown;
  try { value = await response.json(); }
  catch { throw new Error(`接口未返回 JSON（HTTP ${response.status}），请使用根目录 npm run dev 启动两端`); }
  const payload = record(value), error = record(payload.error);
  if (!response.ok) throw new Error(`${error.code ?? response.status}：${error.message ?? '读取失败'}`);
  if (payload.schema !== 'tp-spec.workbench/v1') throw new Error('接口与页面展示契约不匹配，请检查活动源码和启动目录');
  return value;
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
export const api = {
  skillDocument: async (id: string, signal?: AbortSignal, path = '') => {
    const value = record(await get(`/api/skill-documents/${encodeURIComponent(id)}?path=${encodeURIComponent(path)}`, signal));
    if (value.id !== id || typeof value.content !== 'string' || typeof value.path !== 'string') throw new Error('设定文档响应不匹配');
    return { content: value.content, path: value.path };
  },
  health: async (signal?: AbortSignal) => {
    const value = await get('/api/health', signal);
    if (record(value).ready !== true || record(value).read_only !== true) throw new Error('工作台只读服务未就绪');
    return value as Health;
  },
  global: async (signal?: AbortSignal) => {
    const result = validateEnvelope<GlobalData>(await get('/api/global', signal));
    if (!Array.isArray(result.data.contexts) || result.data.contexts.some(c => !c || typeof c.context_key !== 'string')) throw new Error('项目索引响应格式错误');
    return result;
  },
  project: async (key: string, signal?: AbortSignal) => {
    const result = validateEnvelope<ProjectData>(await get(projectPath(key), signal), key);
    if (!Array.isArray(result.data.task_index) || result.data.task_index.some(row => !row || typeof row.task_id !== 'string' || typeof row.title !== 'string' || typeof row.state !== 'string')) throw new Error('任务索引响应格式错误');
    return result;
  },
  task: async (key: string, id: string, signal?: AbortSignal) =>
    validateEnvelope<TaskData>(await get(`${projectPath(key)}/tasks/${encodeURIComponent(id)}`, signal), key, id),
  details: async (key: string, id: string, signal?: AbortSignal) =>
    validateEnvelope<DetailData>(await get(`${projectPath(key)}/tasks/${encodeURIComponent(id)}/details`, signal), key, id),
  closeout: async (key: string, id: string, signal?: AbortSignal) =>
    validateEnvelope<CloseoutData>(await get(`${projectPath(key)}/tasks/${encodeURIComponent(id)}/closeout`, signal), key, id),
};
