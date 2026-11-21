import { getGlobalEnvelope } from './api';
import type { WikiDays, WikiDocumentData, WikiDocumentsData, WikiOverviewData, WikiRecordStatus, WikiRecordsData } from './wikiTypes';

export const wikiApi = {
    overview: (project: string, days: WikiDays, signal?: AbortSignal) =>
        getGlobalEnvelope<WikiOverviewData>('/api/wiki/overview', { project, days }, signal),
    documents: (query: { project: string; days: WikiDays; repo?: string; kind?: string; q?: string; page: number; adopted?: boolean }, signal?: AbortSignal) =>
        getGlobalEnvelope<WikiDocumentsData>('/api/wiki/documents', {
            project: query.project,
            days: query.days,
            repo: query.repo || undefined,
            kind: query.kind || undefined,
            q: query.q || undefined,
            page: query.page,
            adopted: query.adopted ? 1 : undefined,
        }, signal),
    document: (key: string, days: WikiDays, signal?: AbortSignal) =>
        getGlobalEnvelope<WikiDocumentData>('/api/wiki/document', { id: key, days }, signal),
    records: (query: { project: string; days: WikiDays; status: WikiRecordStatus; date?: string; page: number; q?: string }, signal?: AbortSignal) =>
        getGlobalEnvelope<WikiRecordsData>('/api/wiki/records', {
            project: query.project,
            days: query.days,
            status: query.status,
            date: query.date || undefined,
            page: query.page,
            q: query.q || undefined,
        }, signal),
};
