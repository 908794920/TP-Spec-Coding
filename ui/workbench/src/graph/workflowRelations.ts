import { record, records, stageLabel, text } from '../facts';
import { roleLabel, statusNames, strings } from '../components/executionView';
import type { FactRecord, TaskData } from '../types';

export interface StageRole {
    id: string;
    label: string;
    planned: boolean;
    events: FactRecord[];
    participations: FactRecord[];
}
export interface WorkflowStage {
    id: string;
    key: string;
    title: string;
    status: string;
    current: boolean;
    next: boolean;
    explicit: boolean;
    activityOnly?: boolean;
    record: FactRecord;
    roles: StageRole[];
    events: FactRecord[];
}
export interface WorkflowRelations {
    stages: WorkflowStage[];
    activityStages: WorkflowStage[];
    unassigned: FactRecord[];
    truncated: boolean;
    returned: number;
    total: number | null;
    explicit: boolean;
}
const eventId = (event: FactRecord) => text(event.source_event_id ?? event.event_id ?? event.id);
const newest = (a: FactRecord, b: FactRecord) =>
    (Date.parse(text(b.created_at)) || 0) - (Date.parse(text(a.created_at)) || 0) || Number(eventId(b)) - Number(eventId(a));
const phaseLabels: Record<string, string> = {
    intake: '受理', requirement: '需求', product: '产品设计', architecture: '架构设计', architecture_review: '架构复审',
    discovery: '调研', planning: '实施规划', development: '开发', verification: '验证', review: '代码复审', delivery: '交付集成', other: '其他',
};
/** Completion colour reflects a recorded result, never event presence or words in a summary. */
export function stageHasCompletedWork(stage: WorkflowStage): boolean {
    if (!stage.activityOnly) return stage.record.status === 'COMPLETED'
        || (stage.record.status === '已完成' && !!text(stage.record.completion_source));
    const event = stage.events[0];
    if (!event || event.source_kind !== 'structured') return false;
    const detail = record(event.detail), operation = text(event.operation) || text(detail.operation);
    if (event.event_type === 'REVIEW_COMPLETED' || event.event_type === 'VERIFICATION_COMPLETED' || operation === 'REVIEW')
        return event.decision === 'PASS';
    return operation === 'CHECKPOINT' && event.result_status === 'COMPLETED';
}
function recordedStage(event: FactRecord): string {
    const detail = record(event.detail), operation = text(event.operation) || text(detail.operation);
    if (event.event_type === 'REVIEW_COMPLETED' || operation === 'REVIEW') {
        const kind = (text(detail.review_kind) || (event.actor === 'tp-code-reviewer' ? 'CODE' : '')).toUpperCase();
        return kind === 'ARCHITECTURE' ? 'architecture_review' : ['CODE', 'IMPLEMENTATION', 'ULTRA_REVIEW'].includes(kind) ? 'review' : kind === 'VERIFICATION' ? 'verification' : '';
    }
    if (event.event_type === 'VERIFICATION_COMPLETED') return 'verification';
    return text(detail.stage) || text(detail.source_stage) || (operation === 'CHECKPOINT' ? text(detail.phase) || text(event.to_stage) : '');
}

/** Read-only relationships: explicit step bindings first; structured legacy facts never create a plan. */
export function buildWorkflowRelations(contextKey: string, data: TaskData): WorkflowRelations {
    const task = record(data.task), workflow = record(data.workflow), execution = record(workflow.execution);
    const explicit = !!text(execution.status) && execution.status !== 'NOT_RECORDED';
    const terminal = execution.terminal === true || workflow.retired === true || ['COMPLETED', 'CANCELLED'].includes(text(task.state));
    const steps = records(explicit ? execution.steps : workflow.steps);
    const currentKey = terminal ? '' : explicit ? text(record(execution.current_step).id)
        : text(record(workflow.current_step).stage) || text(task.phase);
    const nextKey = terminal ? '' : text(record(explicit ? execution.next_step : workflow.next_step)[explicit ? 'id' : 'stage']);
    const stages: WorkflowStage[] = steps.filter(step => text(step[explicit ? 'id' : 'stage'])).map(step => {
        const key = text(step[explicit ? 'id' : 'stage']);
        const planned = explicit ? strings(step.roles) : [text(step.role)].filter(Boolean);
        return { id: JSON.stringify([contextKey, text(task.task_id), explicit ? 'execution-step' : 'workflow-stage', key]), key,
            title: explicit ? text(step.title) || key : stageLabel(step),
            status: statusNames[text(step.status)] || text(step.status) || '状态未记录',
            current: key === currentKey, next: key === nextKey, explicit, record: step,
            roles: [...new Set(planned)].map(id => ({ id, label: roleLabel(id), planned: true, events: [], participations: [] })), events: [] };
    });
    const byKey = new Map(stages.map(stage => [stage.key, stage]));
    function role(stage: WorkflowStage, id: string): StageRole {
        let found = stage.roles.find(item => item.id === id);
        if (!found) {
            found = { id, label: roleLabel(id), planned: false, events: [], participations: [] };
            stage.roles.push(found);
        }
        return found;
    }
    const participants = records(execution.participations);
    if (explicit) for (const participation of participants) {
        const stage = byKey.get(text(participation.step_id));
        if (stage) role(stage, text(participation.role)).participations.push(participation);
    }
    // Prefer execution's richer event when the same Runtime event also appears in the Task timeline.
    const events = new Map<string, FactRecord>();
    for (const event of [...(explicit ? records(execution.timeline) : []), ...records(data.timeline)]) {
        const id = eventId(event);
        if (!id || !events.has(id)) events.set(id || `unidentified:${events.size}`, event);
    }
    const unassigned: FactRecord[] = [];
    for (const event of [...events.values()].sort(newest)) {
        const detail = record(event.detail);
        const stepId = text(event.step_id) || text(detail.step_id);
        let stage: WorkflowStage | undefined;
        if (explicit) {
            const participation = participants.find(item => text(item.participation_id) === text(event.participation_id) && !!text(event.participation_id));
            stage = byKey.get(stepId || text(participation?.step_id));
        } else {
            const bound = stages.filter(item => Number(item.record.completion_event_id) > 0 && text(item.record.completion_event_id) === eventId(event));
            if (bound.length === 1) stage = bound[0];
            const declaredStage = text(detail.stage) || text(detail.source_stage);
            if (!stage && declaredStage) stage = byKey.get(declaredStage);
            const phase = text(detail.phase) || text(event.to_stage);
            // The Runtime distinguishes architecture CHECKPOINTs from ARCHITECTURE reviews,
            // even though both share phase=architecture. Never infer a stage from prose or actor alone.
            if (!stage) stage = byKey.get(recordedStage(event));
            if (!stage && !declaredStage && phase) {
                const matching = stages.filter(item => text(item.record.phase) === phase);
                if (matching.length === 1) stage = matching[0];
            }
        }
        if (stage) {
            stage.events.push(event);
            role(stage, text(event.actor) || text(detail.actor_role)).events.push(event);
        } else unassigned.push(event);
    }
    // Adopting a plan must not hide earlier work. These are event groupings in a separate lane,
    // not reconstructed plan steps, participation sessions, or completion claims.
    const activityStages: WorkflowStage[] = [], remaining: FactRecord[] = [];
    for (const event of unassigned) {
        const detail = record(event.detail);
        const key = explicit && !text(event.step_id ?? detail.step_id) && !text(event.participation_id) ? recordedStage(event) : '';
        if (!key) { remaining.push(event); continue; }
        let stage = activityStages.find(item => item.key === key);
        if (!stage) {
            stage = { id: JSON.stringify([contextKey, text(task.task_id), 'recorded-phase', key]), key,
                title: phaseLabels[key] || key, status: '已有活动记录', current: false, next: false, explicit: false, activityOnly: true,
                record: { phase: key, definition_source: 'task_event', note: '按事件明确记录的阶段归组，不绑定到后续计划步骤，不推断阶段完成。' }, roles: [], events: [] };
            activityStages.push(stage);
        }
        stage.events.push(event);
        role(stage, text(event.actor) || text(detail.actor_role)).events.push(event);
    }
    activityStages.sort((a, b) => -newest(a.events[a.events.length - 1], b.events[b.events.length - 1]));
    const scope = record(data.timeline_scope), returned = records(data.timeline).length;
    return { stages, activityStages, unassigned: remaining, explicit, returned, total: typeof scope.total === 'number' ? scope.total : null,
        truncated: typeof scope.total === 'number' && scope.total > returned };
}
