import { useId, useMemo, useState } from 'react';
import { Button, Input, Select, Table, Tag, Typography } from 'antd';
import { OPEN_FILTER, OTHER_FILTER, explainValue, filterTasks, stateLabel, stateTone, timestampRaw, timestampText } from '../facts';
import type { TaskIndexRow } from '../types';
/* Tone names follow the existing CSS contract: only Runtime-recorded states get a colour,
   unrecorded/unrecognised ones stay neutral or warning — never a success claim. */
const toneColor: Record<string, string | undefined> = { blocked: 'error', completed: 'success', active: 'processing', unknown: 'warning' };
/* View-only pagination: the API returns the whole index in one read, this only pages the rendering. */
const PAGE_SIZE = 10;
export function TaskIndex({ rows, onSelect }: {
    rows: TaskIndexRow[];
    onSelect: (id: string) => void;
}) {
    const [query, setQuery] = useState(''), [state, setState] = useState(OPEN_FILTER), [page, setPage] = useState(1);
    const id = useId();
    const filtered = useMemo(() => filterTasks(rows, query, state), [rows, query, state]);
    /* A narrower filter can leave the offset past the end of the result, so clamp what is rendered;
       the handlers reset it explicitly, otherwise clearing a search would jump back to that offset. */
    const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    /* Three fixed views. 活跃任务 (default) and 其他任务 partition every row, so nothing is unreachable. */
    const stateOptions: { value: string; label: string }[] = [
        { value: '', label: '全部状态' },
        { value: OPEN_FILTER, label: '活跃任务' },
        { value: OTHER_FILTER, label: '其他任务' },
    ];
    /* Say why the list is empty, and which view still has the rows: a default view is not a user mistake. */
    const searching = !!query.trim();
    const emptyText = !rows.length ? '当前项目没有已取得的任务。'
        : searching ? '没有匹配项；可清空搜索或筛选。'
            : state === OPEN_FILTER ? '当前没有活跃任务；可切换到「其他任务」或「全部状态」查看。'
                : state === OTHER_FILTER ? '当前没有其他任务；可切换到「活跃任务」或「全部状态」查看。'
                    : '没有匹配项；可清空搜索或筛选。';
    return <div className="task-index">
    <div className="filters"><label htmlFor={`${id}-query`}>搜索任务<Input id={`${id}-query`} type="search" allowClear value={query} onChange={e => { setQuery(e.target.value); setPage(1); }} placeholder="ID、标题或负责人"/></label>
      <label htmlFor={`${id}-state`}>正式状态<Select id={`${id}-state`} className="state-filter" value={state} onChange={value => { setState(value); setPage(1); }} options={stateOptions} popupMatchSelectWidth={220}/></label></div>
    <p className="muted result-count">匹配 {filtered.length} / {rows.length} 项{state === OPEN_FILTER ? ' · 活跃任务' : state === OTHER_FILTER ? ' · 其他任务' : ''}</p>
    <Table<TaskIndexRow> className="task-index-table" size="small" rowKey="task_id" dataSource={filtered} scroll={{ x: 620 }}
      pagination={{ pageSize: PAGE_SIZE, current: Math.min(page, pageCount), size: 'small', showSizeChanger: false, showTotal: (_total, range) => `第 ${range[0]}-${range[1]} 条`, onChange: value => setPage(value) }}
      locale={{ emptyText }} onRow={row => ({ onClick: () => onSelect(row.task_id) })} columns={[
            { title: 'Task', dataIndex: 'task_id', render: (_, row) => <Button type="link" className="link" onClick={event => { event.stopPropagation(); onSelect(row.task_id); }}>{row.task_id}</Button> },
            { title: '标题', dataIndex: 'title', render: (_, row) => row.title || '未记录' },
            { title: '正式状态', dataIndex: 'state', render: (_, row) => <><Tag variant="filled" color={toneColor[stateTone('task', row.state)]}>{stateLabel('task', row.state)}</Tag>{row.retired ? ' · 已退休' : ''}</> },
            { title: '阶段 / 负责人', render: (_, row) => <>{explainValue('phase', row.phase) || row.phase || '未记录'}<br /><Typography.Text type="secondary">{explainValue('owner', row.owner) || row.owner || '负责人未记录'}</Typography.Text></> },
            { title: '更新时间', dataIndex: 'updated_at', render: (_, row) => <time dateTime={timestampRaw(row.updated_at) || undefined} title={timestampRaw(row.updated_at) || undefined}>{timestampText(row.updated_at)}</time> },
    ]}/>
  </div>;
}
