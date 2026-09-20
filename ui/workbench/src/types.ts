export type Fact = string | number | boolean | null | Fact[] | {
    [key: string]: Fact;
};
export type FactRecord = Record<string, unknown>;
export interface Problem {
    code: string;
    message: string;
    severity?: string;
}
export interface Context {
    context_key: string;
    project_id: string;
    name: string;
    project_root: string;
    workspace_root: string;
    db_path: string;
    registry_path: string;
    source: string;
}
export interface ReadInfo {
    task_revision?: string;
    started_at: string;
    completed_at: string;
    completeness: 'complete' | 'partial';
    consistency: string;
    note: string;
}
export interface Envelope<T> {
    schema: 'tp-spec.workbench/v1';
    context: Context | null;
    read: ReadInfo;
    data: T;
}
export interface Health {
    schema: string;
    ready: boolean;
    source_root: string;
    version: string;
    registry_path: string;
    python_executable: string;
    read_only: boolean;
}
export interface GlobalData extends FactRecord {
    contexts: Context[];
    problems: Problem[];
}
export interface TaskIndexRow {
    task_id: string;
    title: string;
    state: string;
    phase?: string;
    updated_at?: string;
    owner?: string;
    retired?: boolean;
    summary?: string;
}
export interface ProjectData extends FactRecord {
    project: FactRecord;
    task_index: TaskIndexRow[];
    problems: Problem[];
}
export interface WorkItems extends FactRecord {
    source: string;
    items: FactRecord[];
}
export interface TaskData extends FactRecord {
    task: FactRecord;
    problems?: Problem[];
    work_items: WorkItems;
    work_sessions?: FactRecord;
    workflow: FactRecord;
}
export interface ReadState<T> {
    data?: T;
    error?: string;
    loading: boolean;
}

export interface DetailData extends FactRecord {
    task: FactRecord;
    acceptance: FactRecord;
    verification: FactRecord;
    review: FactRecord;
    delivery: FactRecord;
    owner_acceptance: FactRecord;
    blockers: FactRecord;
    evidence: FactRecord[];
    problems: Problem[];
}
export interface CloseoutData extends FactRecord {
    task_id: string;
    state: string;
    ready: boolean;
    blockers: unknown[];
    acceptance_issues: unknown[];
    route: FactRecord | null;
    problems?: Problem[];
}
