import type { Problem, ReadInfo } from './types';

export type WikiDays = 7 | 30 | 90;
export type WikiCollectionStatus = 'available' | 'not_collected' | 'partial' | string;
export type WikiMetricValue = number | null;

export interface WikiEnvelope<T> {
    schema: 'tp-spec.workbench/v1';
    context: null;
    read: ReadInfo;
    data: T;
}

export interface WikiProjectOption {
    key: string;
    id?: string | null;
    name: string;
}

export interface WikiCollection {
    status?: WikiCollectionStatus;
    started_at?: string | null;
    retention_days?: number | null;
    accessible_projects?: number | null;
    total_projects?: number | null;
    note?: string | null;
    missing_projects?: string[];
    unresolved_contexts?: number;
}

export interface WikiMetrics {
    searches?: WikiMetricValue;
    hits?: WikiMetricValue;
    hit_rate?: WikiMetricValue;
    reads?: WikiMetricValue;
    adopted_tasks?: WikiMetricValue;
    adopted_documents?: WikiMetricValue;
    failures?: WikiMetricValue;
}

export interface WikiTrendRow {
    date: string;
    searches?: WikiMetricValue;
    hits?: WikiMetricValue;
    adopted_tasks?: WikiMetricValue;
}

export interface WikiProjectUsageRow {
    key: string;
    name: string;
    searches?: WikiMetricValue;
    hits?: WikiMetricValue;
    hit_rate?: WikiMetricValue;
    reads?: WikiMetricValue;
    adopted_tasks?: WikiMetricValue;
    last_used?: string | null;
}

export interface WikiAttentionRow {
    kind: 'zero' | 'stale' | 'unadopted' | string;
    title: string;
    count?: WikiMetricValue;
    project_key?: string | null;
    document_key?: string | null;
    query?: string | null;
}

export interface WikiDocumentMetadata {
    key: string;
    id?: string | null;
    project_key?: string | null;
    project_name?: string | null;
    repo_id?: string | null;
    path?: string | null;
    title?: string | null;
    snippet?: string | null;
    type?: string | null;
    status?: string | null;
    updated_at?: string | null;
    content_hash?: string | null;
    reads?: WikiMetricValue;
    adopted_tasks?: WikiMetricValue;
    last_used?: string | null;
}

export interface WikiPopularDocument extends WikiDocumentMetadata {
    reads?: WikiMetricValue;
    adopted_tasks?: WikiMetricValue;
    last_used?: string | null;
}

export interface WikiMaintenanceRepository {
    project_key?: string | null;
    project_name?: string | null;
    repo_id?: string | null;
    document_count?: WikiMetricValue;
    updated_at?: string | null;
    status?: string | null;
    report?: Record<string, unknown> | null;
}

export interface WikiMaintenance {
    document_count?: WikiMetricValue;
    repo_count?: WikiMetricValue;
    updated_at?: string | null;
    repositories?: WikiMaintenanceRepository[];
}

export interface WikiIndex {
    source_id?: string | null;
    status?: string | null;
    indexed_at?: string | null;
}

export interface WikiOverviewData {
    adoption_collection?: WikiCollection;
    recent_activity?: Record<'search' | 'read' | 'adopted', { at: string | null; status: WikiCollectionStatus }>;
    projects?: WikiProjectOption[];
    selected_project?: string | null;
    days?: WikiDays | number | null;
    collection?: WikiCollection;
    metrics?: WikiMetrics;
    trend?: WikiTrendRow[];
    project_usage?: WikiProjectUsageRow[];
    attention?: WikiAttentionRow[];
    popular?: WikiPopularDocument[];
    maintenance?: WikiMaintenance;
    indexes?: WikiIndex[];
    problems?: Problem[];
}

export interface WikiRepositoryOption {
    id: string;
    name: string;
}

export interface WikiDocumentsData {
    items?: WikiDocumentMetadata[];
    total?: number | null;
    page?: number | null;
    page_size?: number | null;
    repositories?: WikiRepositoryOption[];
    types?: string[];
    problems?: Problem[];
    indexes?: WikiIndex[];
}

export interface WikiUsageRow {
    task_id?: string | null;
    actor_role?: string | null;
    stage?: string | null;
    created_at?: string | null;
    evidence?: string[];
    receipt_id?: string | null;
}

export interface WikiDocumentLink {
    href: string;
    key: string;
    title: string;
}

export interface WikiDocumentData {
    document?: WikiDocumentMetadata;
    content?: string | null;
    usage?: WikiUsageRow[];
    links?: WikiDocumentLink[];
    problems?: Problem[];
}

export type WikiRecordStatus = 'all' | 'hit' | 'zero' | 'failed';

export interface WikiRecordResult {
    id?: string | null;
    key?: string | null;
    title?: string | null;
    content_hash?: string | null;
    current_hash?: string | null;
    version_status?: string | null;
}

export interface WikiRecord {
    key: string;
    receipt_id?: string | null;
    operation?: string | null;
    status?: string | null;
    created_at?: string | null;
    project_name?: string | null;
    project_key?: string | null;
    task_id?: string | null;
    actor_role?: string | null;
    query?: string | null;
    result_count?: WikiMetricValue;
    elapsed_ms?: WikiMetricValue;
    error?: string | null;
    results?: WikiRecordResult[];
}

export interface WikiRecordsData {
    items?: WikiRecord[];
    total?: number | null;
    page?: number | null;
    page_size?: number | null;
    collection?: WikiCollection;
    problems?: Problem[];
}
