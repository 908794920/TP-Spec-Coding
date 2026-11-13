import type { TaskIndexRow } from '../types';
import { timestampRaw } from '../facts';

export type TaskFilter = 'in_progress' | 'other' | 'all';

export const taskFilters: { key: TaskFilter; label: string }[] = [
    { key: 'in_progress', label: '在途' },
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
    if (filter === 'in_progress')
        return isInProgress(row);
    if (filter === 'other')
        return !isInProgress(row);
    return true;
}

export function filterProjectTasks(rows: TaskIndexRow[], query: string, filter: TaskFilter): TaskIndexRow[] {
    const needle = query.trim().toLocaleLowerCase();
    return rows.filter(row => {
        if (!matchesTaskFilter(row, filter))
            return false;
        return !needle || `${row.task_id}\n${row.title}\n${row.owner ?? ''}`.toLocaleLowerCase().includes(needle);
    }).sort((a, b) => {
        const noteOrder = Number(!!b.note?.trim()) - Number(!!a.note?.trim());
        const time = (row: TaskIndexRow) => Date.parse(timestampRaw(row.updated_at)) || 0;
        return noteOrder || time(b) - time(a);
    });
}

export function countProjectTasks(rows: TaskIndexRow[]): Record<TaskFilter, number> {
    return taskFilters.reduce((counts, item) => {
        counts[item.key] = rows.filter(row => matchesTaskFilter(row, item.key)).length;
        return counts;
    }, {} as Record<TaskFilter, number>);
}
