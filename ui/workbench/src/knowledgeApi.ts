import { record } from './facts';
import type { KnowledgeDocumentData, KnowledgeDocuments, KnowledgeEnvelope, KnowledgeOverview, KnowledgeRecords, KnowledgeScope, KnowledgeRecordQuery } from './knowledgeTypes';

async function get<T>(operation: string, values: Record<string, string | number | undefined>, signal?: AbortSignal): Promise<KnowledgeEnvelope<T>> {
    const params = new URLSearchParams();
    Object.entries(values).forEach(([key, value]) => { if (value !== undefined) params.set(key, String(value)); });
    const response = await fetch(`/api/knowledge/${operation}?${params}`, { method: 'GET', cache: 'no-store', signal });
    let value: unknown;
    try { value = await response.json(); }
    catch { throw new Error(`知识库接口未返回 JSON（HTTP ${response.status}），请检查两端启动状态`); }
    const payload = record(value), error = record(payload.error), read = record(payload.read);
    if (!response.ok) throw new Error(`${error.code ?? response.status}：${error.message ?? '知识读取失败'}`);
    if (payload.schema !== 'tp-spec.workbench/v1' || payload.context !== null)
        throw new Error('知识库全局接口契约不匹配，已拒绝显示');
    if (typeof read.started_at !== 'string' || typeof read.completed_at !== 'string' || !payload.data || typeof payload.data !== 'object' || Array.isArray(payload.data))
        throw new Error('知识库接口缺少读取信息或数据，不能作为空结果');
    return value as KnowledgeEnvelope<T>;
}
export const knowledgeApi = {
    overview: (scope: KnowledgeScope, signal?: AbortSignal) => get<KnowledgeOverview>('overview', { ...scope }, signal),
    documents: (query: KnowledgeScope & { q?: string; page: number; layer?: string; kind?: string; maintenance?: string; adopted?: boolean }, signal?: AbortSignal) =>
        get<KnowledgeDocuments>('documents', { ...query, adopted: query.adopted ? 1 : undefined }, signal),
    document: (id: string, scope: KnowledgeScope, signal?: AbortSignal) => get<KnowledgeDocumentData>('document', { ...scope, id, project: '' }, signal),
    records: (query: KnowledgeRecordQuery, signal?: AbortSignal) => get<KnowledgeRecords>('records', { ...query }, signal),
};
