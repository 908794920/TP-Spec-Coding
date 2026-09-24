import type { Envelope, Problem } from './types';

export type KnowledgeDays = 7 | 30 | 90;
export type KnowledgePurpose = 'development' | 'delivery_convergence' | 'maintenance' | 'unknown' | 'all';
export type KnowledgeRecordStatus = 'all' | 'hit' | 'zero' | 'failed';
export type KnowledgeEnvelope<T> = Envelope<T>;
export type KnowledgeNumber = number | null;
export interface KnowledgeProject { key: string; id: string; name: string; shared: boolean; source_id: string; status: string }
export interface KnowledgeSourceState {
    source_id?: string; database_id?: string; project_key?: string; name?: string; status: string;
    retention_days?: number; started_at?: string | null; coverage_start?: string | null;
    earliest_retained_at?: string | null; latest_retained_at?: string | null; enabled?: boolean; note?: string;
}
export interface KnowledgeCollection {
    status: string; available_projects: string[]; missing_projects: string[]; sources: KnowledgeSourceState[];
    unresolved_contexts?: string[]; started_at: string | null; recent_at: string | null;
    window_complete?: boolean; unmapped_assets?: number; note: string;
}
export interface KnowledgeDocument {
    key: string; document_key: string; id: string | null; canonical_id: string; source_id: string;
    title: string; path: string; project: string; project_key: string; project_name: string;
    layer: 'canonical' | 'source'; kind: string; version: string; version_kind: string;
    updated_at: string | null; status: string | null; metadata_available: boolean; metadata_only: boolean;
    source_refs: string[]; evidence_refs: unknown[]; superseded: unknown; replaced_by: unknown; relations: unknown[];
    origin: Record<string, unknown> | null; conversion: string | null; availability?: string;
    indexed_version?: string; version_status?: string; snippet?: string; heading_path?: string;
    line_start?: number; line_end?: number; reads: KnowledgeNumber; adopted_tasks: KnowledgeNumber; last_used: string | null;
}
export interface KnowledgeMetrics {
    searches: KnowledgeNumber; hits: KnowledgeNumber; hit_rate: KnowledgeNumber; reads: KnowledgeNumber;
    failures: KnowledgeNumber; adopted_tasks: KnowledgeNumber; adopted_documents: KnowledgeNumber;
    canonical_searches: KnowledgeNumber; source_searches: KnowledgeNumber; fallback_reasons: Record<string, number>;
    last_used: string | null;
}
export interface KnowledgeOverview {
    projects: KnowledgeProject[]; days: KnowledgeDays; purpose: KnowledgePurpose; selected_project: string; statistics_note: string;
    collection: KnowledgeCollection; adoption_collection: KnowledgeCollection; metrics: KnowledgeMetrics;
    recent_activity: Record<'search' | 'read' | 'adopted', { at: string | null; status: string }>;
    trend: { date: string; searches: KnowledgeNumber; hits: KnowledgeNumber; adopted_tasks: KnowledgeNumber }[];
    project_usage: (KnowledgeProject & KnowledgeMetrics)[]; popular: KnowledgeDocument[];
    attention: { kind: string; title: string; document_key?: string; query_hash?: string; project_key?: string; count?: number }[];
    maintenance: { canonical_documents: KnowledgeNumber; source_documents: KnowledgeNumber; registered_sources: KnowledgeNumber;
        status: string; sources: { source_id: string; status: string; indexed_at?: string | null;
            reports: { name: string; status: unknown; at: string | null; file_updated_at: string | null; note: string }[] }[] };
    unidentified_searches: number;
    history: { scope: string; count: KnowledgeNumber; count_kind: string; earliest_at: string | null; note: string };
    problems: Problem[];
}
export interface KnowledgeDocuments {
    items: KnowledgeDocument[]; total: KnowledgeNumber; page: number; page_size: number; status: string;
    kinds: string[]; maintenance_states: string[]; projects: KnowledgeProject[]; problems: Problem[]; note: string;
}
export interface KnowledgeUsage {
    task_id?: string | null; actor_role?: string | null; stage: string; created_at: string | null;
    purpose?: KnowledgePurpose; project_name?: string; receipt_id?: string | null; read_mode?: string; evidence?: unknown[];
}
export interface KnowledgeDocumentData {
    document: KnowledgeDocument; content: string; read_mode: string; note: string | null;
    outline: { level: number; title: string; line: number }[];
    links: { href: string; key: string; title: string }[];
    references: { kind: string; ref: unknown; key?: string | null; title?: string }[];
    usage: KnowledgeUsage[]; collection: KnowledgeCollection; adoption_collection: KnowledgeCollection; problems: Problem[];
}
export interface KnowledgeRecordResult {
    key?: string | null; document_key?: string; id?: string | null; path?: string; title?: string; project?: string; layer?: string;
    version?: string | null; version_kind?: string; current_version?: string | null; version_status?: string;
    content_hash?: string; line_start?: number; line_end?: number;
}
export interface KnowledgeRecord {
    key: string; receipt_id: string | null; request_id?: string | null; task_id: string | null; actor_role: string | null;
    purpose: KnowledgePurpose; caller: string; created_at: string; project_key: string; project_name: string;
    requested_projects: string[]; returned_projects: string[]; request_scope: string | null; query_hash: string;
    historical: boolean; document_count: KnowledgeNumber; candidate_count: number; count_kind: string | null;
    status: string; layer: string; has_canonical: boolean | number | null; has_source: boolean | number | null;
    fallback_reason: string | null; error_code: string | null; elapsed_ms: KnowledgeNumber;
    results?: KnowledgeRecordResult[] | null;
}
export interface KnowledgeRecords {
    items: KnowledgeRecord[]; total: KnowledgeNumber; page: number; page_size: number;
    collection: KnowledgeCollection; projects: KnowledgeProject[]; problems: Problem[];
}
export interface KnowledgeScope { project: string; days: KnowledgeDays; purpose: KnowledgePurpose }
export interface KnowledgeRecordQuery extends KnowledgeScope {
    page: number; status: KnowledgeRecordStatus; task?: string; hash?: string; date?: string; receipt?: string;
}
