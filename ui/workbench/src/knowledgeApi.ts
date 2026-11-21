import { getGlobalEnvelope } from './api';
import type { KnowledgeDocumentData, KnowledgeDocuments, KnowledgeOverview, KnowledgeRecords, KnowledgeScope, KnowledgeRecordQuery } from './knowledgeTypes';

export const knowledgeApi = {
    overview: (scope: KnowledgeScope, signal?: AbortSignal) =>
        getGlobalEnvelope<KnowledgeOverview>('/api/knowledge/overview', { ...scope }, signal),
    documents: (query: KnowledgeScope & { q?: string; page: number; layer?: string; kind?: string; maintenance?: string; adopted?: boolean }, signal?: AbortSignal) =>
        getGlobalEnvelope<KnowledgeDocuments>('/api/knowledge/documents', { ...query, adopted: query.adopted ? 1 : undefined }, signal),
    document: (id: string, scope: KnowledgeScope, signal?: AbortSignal) =>
        getGlobalEnvelope<KnowledgeDocumentData>('/api/knowledge/document', { ...scope, id, project: '' }, signal),
    records: (query: KnowledgeRecordQuery, signal?: AbortSignal) =>
        getGlobalEnvelope<KnowledgeRecords>('/api/knowledge/records', { ...query }, signal),
};
