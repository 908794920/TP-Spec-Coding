import { useId, useMemo, useState } from 'react';
import { Button, Input, Pagination, Table, Tag, Typography } from 'antd';
import { explainValue, stateLabel, stateTone, text, timestampRaw, timestampText } from '../facts';
import type { TaskIndexRow } from '../types';
import { countProjectTasks, filterProjectTasks, taskFilters, type TaskFilter } from './projectTaskView';

/* 沿用现有 CSS 色调契约：未知或不可用状态不使用成功色。 */
const toneColor: Record<string, string | undefined> = { blocked: 'error', completed: 'success', active: 'processing', unknown: 'warning' };
const PAGE_SIZE = 10;

function chineseState(row: TaskIndexRow): string {
    const state = text(row.state).trim().toUpperCase();
    return stateLabel('task', state).split(' · ')[0];
}

function RecordedResponsibility({ row }: { row: TaskIndexRow }) {
    return <><span>{explainValue('phase', row.phase) || row.phase || '未记录'}</span><Typography.Text type="secondary">{explainValue('owner', row.owner) || row.owner || '责任角色未记录'}</Typography.Text></>;
}

export function TaskIndex({ rows, available = true, onSelect }: {
    rows: TaskIndexRow[];
    available?: boolean;
    onSelect: (id: string) => void;
}) {
    const [query, setQuery] = useState(''), [filter, setFilter] = useState<TaskFilter>('in_progress'), [page, setPage] = useState(1);
    const id = useId();
    const counts = useMemo(() => countProjectTasks(rows), [rows]);
    const filtered = useMemo(() => filterProjectTasks(available ? rows : [], query, filter), [available, rows, query, filter]);
    const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    const currentPage = Math.min(page, pageCount);
    const visible = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);
    const searching = !!query.trim();
    const emptyText = !available ? 'Runtime 任务数据不可用，未计算任务数量。'
        : !rows.length ? '当前项目没有已取得的任务。'
        : searching ? '没有匹配项；可清空搜索或筛选。'
        : filter === 'in_progress' ? '当前没有在途任务；可切换到其他筛选查看。'
        : filter === 'blocked' ? '当前没有阻塞任务；可切换到其他筛选查看。'
        : filter === 'completed' ? '当前没有已完成任务；可切换到其他筛选查看。'
        : filter === 'other' ? '当前没有其他任务；可切换到其他筛选查看。'
        : '没有匹配项；可清空搜索或筛选。';
    function chooseFilter(next: TaskFilter) {
        setFilter(next);
        setPage(1);
    }
    return <div className="task-index">
    <div className="task-index-controls">
      <div className="task-index-filter-bar" role="group" aria-label="任务状态筛选">
        {taskFilters.map(item => <Button key={item.key} size="small" type={filter === item.key ? 'primary' : 'default'} aria-pressed={filter === item.key} onClick={() => chooseFilter(item.key)}>
          {item.label} <span className="task-filter-count">{available ? counts[item.key] : '—'}</span>
        </Button>)}
      </div>
      <label className="task-index-query" htmlFor={`${id}-query`}>搜索任务<Input id={`${id}-query`} type="search" allowClear value={query} onChange={e => { setQuery(e.target.value); setPage(1); }} placeholder="ID、标题或负责人"/></label>
    </div>
    <Table<TaskIndexRow> className="task-index-table" size="small" rowKey="task_id" dataSource={visible} pagination={false}
      locale={{ emptyText }} onRow={row => ({ onClick: () => onSelect(row.task_id) })} columns={[
            { title: '任务', render: (_, row) => <div className="task-index-title-cell"><Button type="link" className="link task-index-title" onClick={event => { event.stopPropagation(); onSelect(row.task_id); }}>{row.title || '未记录'}</Button><small><code>{row.task_id || '任务 ID 未记录'}</code></small><div className="task-index-mobile-responsibility"><RecordedResponsibility row={row}/></div></div> },
            { title: '状态', dataIndex: 'state', render: (_, row) => { const state = text(row.state).trim().toUpperCase(); return <div className="task-index-status"><Tag variant="filled" color={toneColor[stateTone('task', state)]}>{chineseState(row)}</Tag>{row.retired === true && <Tag>已退休</Tag>}</div>; } },
            { title: '已记录阶段 / 责任角色', className: 'task-index-responsibility-column', render: (_, row) => <div className="task-index-stage-owner"><RecordedResponsibility row={row}/></div> },
            { title: '最近更新', className: 'task-index-date-column', dataIndex: 'updated_at', render: (_, row) => { const raw = timestampRaw(row.updated_at), display = timestampText(row.updated_at); return <time dateTime={raw || undefined} title={text(row.updated_at) || '未记录'}>{raw ? display.slice(5, 16) : display}</time>; } },
    ]}/>
    <div className="task-index-footer">
      <p className="muted result-count" role="status">{available ? `匹配 ${filtered.length} / ${rows.length} 项` : '任务数据不可用，未计算匹配数量。'}</p>
      {available && filtered.length > 0 && <Pagination size="small" current={currentPage} pageSize={PAGE_SIZE} total={filtered.length}
        showSizeChanger={false} showTotal={(_total, range) => `第 ${range[0]}-${range[1]} 条`} onChange={setPage}/>}
    </div>
  </div>;
}
