import { explainValue, record, records, text } from '../facts';
import type { FactRecord } from '../types';
export interface ExecutionEvent extends FactRecord {
    event_id?: number; step_id?: string; participation_id?: string; actor?: string; action?: string; expected_next_actor?: string;
}
export interface Participation extends FactRecord {
    participation_id?: string; step_id?: string; role?: string; started_at?: string; ended_at?: string | null;
    status?: string; history?: ExecutionEvent[];
}
export interface ExecutionStep extends FactRecord {
    id?: string; title?: string; status?: string; roles?: string[]; depends_on?: string[];
}
export type EventScope = 'participation' | 'role' | 'step';
export const strings = (value: unknown): string[] => Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
export const statusNames: Record<string, string> = {
    PLANNED: '计划', ACTIVE: '进行中', WAITING: '等待', COMPLETED: '已完成',
    HANDED_OFF: '已交接', PAUSED: '已暂停（参与已结束）', WAITING_HUMAN: '等待人工（参与已结束）',
    WAITING_AGENT: '等待角色（参与已结束）', BLOCKED: '受阻（参与已结束）', INTERRUPTED: '已中断', CANCELLED: '已取消',
};
export const actions: Record<string, string> = {
    start: '开始', wait: '等待', resume: '恢复', complete: '步骤完成', completed: '参与完成', handed_off: '交接',
    paused: '暂停', waiting_human: '等待人工', waiting_agent: '等待角色', blocked: '受阻', interrupted: '中断', cancelled: '取消',
};
export function roleLabel(value: unknown): string {
    const raw = text(value), label = explainValue('actor', raw);
    return label ? label.split('（')[0] : raw || '角色未记录';
}
export function newestEvents(value: unknown): ExecutionEvent[] {
    return (records(value) as ExecutionEvent[]).slice().sort((a, b) => Number(b.event_id || 0) - Number(a.event_id || 0));
}
export function stepRoles(step: ExecutionStep, participants: Participation[]): string[] {
    return Array.from(new Set([...strings(step.roles), ...participants.map(p => text(p.role))]));
}
export function groupParticipations(participants: Participation[]) {
    // 事件顺序优先于时间文本；不同执行者、Work 或轮次保留独立身份。
    const sorted = participants.slice().sort((a, b) => {
        const last = (p: Participation) => Number(newestEvents(p.history)[0]?.event_id || 0);
        return last(b) - last(a);
    });
    const active = sorted.filter(p => !p.ended_at), ended = sorted.filter(p => !!p.ended_at);
    return { visible: [...active, ...ended.slice(0, 1)], history: ended.slice(1) };
}
export function filterEvents(timeline: ExecutionEvent[], selected: Participation, scope: EventScope): ExecutionEvent[] {
    const source = scope === 'participation' ? newestEvents(selected.history) : newestEvents(timeline);
    return source.filter(event => event.step_id === selected.step_id && (scope === 'step' ||
        (scope === 'role' ? !!event.participation_id && event.actor === selected.role : event.participation_id === selected.participation_id)));
}
export function latestHandoff(timeline: ExecutionEvent[], stepId: string): ExecutionEvent | undefined {
    return newestEvents(timeline).find(event => event.step_id === stepId && event.action === 'handed_off' && !!event.expected_next_actor);
}
export function participationLabel(p: Participation, terminal: boolean): string {
    const status = statusNames[text(p.status)] || text(p.status) || '状态未记录';
    return terminal && !p.ended_at ? `历史未结束 · ${status}` : status;
}
export function currentDescription(facts: FactRecord, terminal: boolean): string {
    if (terminal) return '任务已结束，无当前执行步骤';
    if (facts.status === 'NOT_RECORDED' || !facts.status) return '执行计划尚未登记';
    const current = record(facts.current_step), steps = records(facts.steps);
    if (current.id) return `${text(current.title)} · ${statusNames[text(current.status)] || text(current.status)}`;
    if (facts.status === 'INVALID') return '执行事实异常，当前步骤无法确认';
    if (steps.length && steps.every(step => step.status === 'COMPLETED')) return '计划步骤已结束，Task 尚未正式结单';
    return steps.some(step => step.status === 'COMPLETED') ? '当前步骤已结束，下一步尚未开始' : '计划已登记，尚未开始';
}
