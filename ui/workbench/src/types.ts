export type Fact = string | number | boolean | null | Fact[] | {
    [key: string]: Fact;
};
export type FactRecord = Record<string, unknown>;
export type WorkflowMode = 'standard' | 'quick';
export interface ModeSource {
    kind: 'task_create' | 'task_mode_selected';
    event_id: number;
    user_source: { kind: 'user_instruction'; reference: string; statement: string } | null;
    digest: string;
}
export interface QuickStatus {
    delivery_status: 'READY' | 'BLOCKED' | 'NOT_RECORDED' | 'READY_STALE';
    recorded_delivery_status: 'READY' | 'BLOCKED' | null;
    delivery_current: boolean;
    awaiting_completion: boolean;
    verification_scope: 'full' | 'technical' | null;
    verification_decision: 'PASS' | 'FAIL' | 'NEEDS_FIX' | 'NOT_RECORDED' | 'PASS_STALE' | 'INVALID';
    verification_current: boolean;
    verification_event_id: number | null;
    delivery_event_id: number | null;
    checks: string[];
    unverified_items: string[];
}
export interface WorkflowData extends FactRecord {
    workflow_mode?: WorkflowMode;
    mode_source?: ModeSource | null;
    applicable_obligations?: FactRecord;
    quick_status?: QuickStatus | null;
}
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
    workflow_mode?: WorkflowMode;
    mode_source?: ModeSource | null;
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
    workflow: WorkflowData;
}
export interface ReadState<T> {
    data?: T;
    error?: string;
    loading: boolean;
}

export interface DetailData extends WorkflowData {
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
export interface CloseoutCheck extends FactRecord {
    id: string;
    status: string;
    required: boolean;
    responsibility: string | null;
    depends_on: string[];
    issues: unknown[];
    facts: FactRecord;
}
export interface CloseoutData extends WorkflowData {
    task_id: string;
    state: string;
    ready: boolean;
    blockers: unknown[];
    acceptance_issues: unknown[];
    route: FactRecord | null;
    checks?: CloseoutCheck[];
    unknowns?: string[];
    next_actions?: FactRecord[];
    already_terminal?: boolean;
    problems?: Problem[];
}

/** Source-relative document returned by the existing read-only workbench endpoint. */
export interface SkillDocumentData {
    id: string;
    name: string;
    path: string;
    content: string;
    source_kind: 'builtin' | 'external';
    source_root: string;
    status: 'available' | 'disabled';
    enabled: boolean;
    entry_path: string;
    content_sha256: string;
    entry_sha256: string;
    upstream: string;
    version: string;
}
