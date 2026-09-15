import type { FactRecord, TaskIndexRow } from './types';
export function record(value: unknown): FactRecord {
    return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as FactRecord : {};
}
export function records(value: unknown): FactRecord[] {
    return Array.isArray(value) ? value.filter(v => v !== null && typeof v === 'object' && !Array.isArray(v)) : [];
}
export function text(value: unknown): string {
    return typeof value === 'string' ? value : typeof value === 'number' || typeof value === 'boolean' ? String(value) : '';
}
export function valueText(value: unknown): string {
    if (value === null || value === undefined || value === '')
        return '未记录';
    if (typeof value === 'boolean')
        return value ? '是' : '否';
    return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
}
export function stageLabel(step: unknown): string {
    const row = record(step), display = record(row.stage_display);
    const id = text(row.stage);
    if (!id)
        return '';
    return display.configured === true && text(display.label) ? text(display.label) : `${id}（展示名称未配置）`;
}
const states: Record<string, Record<string, string>> = {
    task: { NEW: '新建', ACTIVE: '活跃', BLOCKED: '阻塞', COMPLETED: '已结单', CANCELLED: '已取消' },
    work_item: { PENDING: '待处理', ACTIVE: '已认领', COMPLETED: '工作项已完成' },
};
export function stateLabel(kind: string, state: unknown): string {
    const raw = text(state);
    if (!raw)
        return '未记录';
    const label = states[kind]?.[raw];
    return label ? `${label} · ${raw}` : `${raw}（未识别）`;
}
export function stateTone(kind: string, state: unknown): string {
    const raw = text(state);
    if (!states[kind]?.[raw])
        return 'unknown';
    return raw === 'BLOCKED' ? 'blocked' : raw === 'COMPLETED' ? 'completed' : raw === 'ACTIVE' ? 'active' : 'neutral';
}
export function filterTasks(rows: TaskIndexRow[], query: string, state: string): TaskIndexRow[] {
    const q = query.trim().toLocaleLowerCase();
    return rows.filter(row => (!state || row.state === state) && (!q ||
        `${row.task_id}\n${row.title}\n${row.owner ?? ''}`.toLocaleLowerCase().includes(q)));
}
