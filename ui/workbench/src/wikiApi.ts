import { record } from './facts';
import type { WikiDays, WikiDocumentData, WikiDocumentsData, WikiEnvelope, WikiOverviewData, WikiRecordStatus, WikiRecordsData } from './wikiTypes';

async function get(path: string, signal?: AbortSignal): Promise<unknown> {
    const response = await fetch(path, { method: 'GET', cache: 'no-store', signal });
    let value: unknown;
    try {
        value = await response.json();
    }
    catch {
        throw new Error(`接口未返回 JSON（HTTP ${response.status}），请使用根目录 npm run dev 启动两端`);
    }
    const payload = record(value), error = record(payload.error);
    if (!response.ok)
        throw new Error(`${error.code ?? response.status}：${error.message ?? '读取失败'}`);
    if (payload.schema !== 'tp-spec.workbench/v1')
        throw new Error('Wiki 接口与页面展示契约不匹配，请检查活动源码和启动目录');
    if (payload.context !== null)
        throw new Error('Wiki 全局接口返回了项目上下文，已拒绝显示');
    if (!payload.read || typeof record(payload.read).started_at !== 'string' || typeof record(payload.read).completed_at !== 'string')
        throw new Error('Wiki 接口响应缺少读取信息，已拒绝显示');
    if (!payload.data || typeof payload.data !== 'object' || Array.isArray(payload.data))
        throw new Error('Wiki 接口响应缺少数据，保留上次成功结果');
    return value;
}

function params(values: Record<string, string | number | undefined>): string {
    const query = new URLSearchParams();
    Object.entries(values).forEach(([key, value]) => {
        if (value !== undefined)
            query.set(key, String(value));
    });
    return query.toString();
}

function envelope<T>(value: unknown): WikiEnvelope<T> {
    return value as WikiEnvelope<T>;
}

export const wikiApi = {
    overview: async (project: string, days: WikiDays, signal?: AbortSignal) => envelope<WikiOverviewData>(await get(`/api/wiki/overview?${params({ project, days })}`, signal)),
    documents: async (query: { project: string; days: WikiDays; repo?: string; kind?: string; q?: string; page: number; adopted?: boolean }, signal?: AbortSignal) => envelope<WikiDocumentsData>(await get(`/api/wiki/documents?${params({
        project: query.project,
        days: query.days,
        repo: query.repo || undefined,
        kind: query.kind || undefined,
        q: query.q || undefined,
        page: query.page,
        adopted: query.adopted ? 1 : undefined,
    })}`, signal)),
    document: async (key: string, days: WikiDays, signal?: AbortSignal) => envelope<WikiDocumentData>(await get(`/api/wiki/document?${params({ id: key, days })}`, signal)),
    records: async (query: { project: string; days: WikiDays; status: WikiRecordStatus; date?: string; page: number; q?: string }, signal?: AbortSignal) => envelope<WikiRecordsData>(await get(`/api/wiki/records?${params({
        project: query.project,
        days: query.days,
        status: query.status,
        date: query.date || undefined,
        page: query.page,
        q: query.q || undefined,
    })}`, signal)),
};
