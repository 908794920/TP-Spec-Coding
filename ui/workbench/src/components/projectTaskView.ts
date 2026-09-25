import type { TaskIndexRow } from '../types';

export type TaskFilter = 'in_progress' | 'blocked' | 'completed' | 'other' | 'all';

export const taskFilters: { key: TaskFilter; label: string }[] = [
    { key: 'in_progress', label: '在途' },
    { key: 'blocked', label: '阻塞' },
    { key: 'completed', label: '已完成' },
    { key: 'other', label: '其他' },
    { key: 'all', label: '全部' },
];

function stateOf(row: TaskIndexRow): string {
    return typeof row.state === 'string' ? row.state.trim().toUpperCase() : '';
}

export function isInProgress(row: TaskIndexRow): boolean {
    return row.retired !== true && ['NEW', 'ACTIVE', 'BLOCKED'].includes(stateOf(row));
}

export function matchesTaskFilter(row: TaskIndexRow, filter: TaskFilter): boolean {
    const state = stateOf(row), active = isInProgress(row);
    if (filter === 'in_progress')
        return active;
    if (filter === 'blocked')
        return row.retired !== true && state === 'BLOCKED';
    if (filter === 'completed')
        return row.retired !== true && state === 'COMPLETED';
    if (filter === 'other')
        return !active && !(row.retired !== true && state === 'COMPLETED');
    return true;
}

export function filterProjectTasks(rows: TaskIndexRow[], query: string, filter: TaskFilter): TaskIndexRow[] {
    const needle = query.trim().toLocaleLowerCase();
    return rows.filter(row => {
        if (!matchesTaskFilter(row, filter))
            return false;
        return !needle || `${row.task_id}\n${row.title}\n${row.owner ?? ''}`.toLocaleLowerCase().includes(needle);
    });
}

export function countProjectTasks(rows: TaskIndexRow[]): Record<TaskFilter, number> {
    return taskFilters.reduce((counts, item) => {
        counts[item.key] = rows.filter(row => matchesTaskFilter(row, item.key)).length;
        return counts;
    }, {} as Record<TaskFilter, number>);
}
