import { useId, useMemo, useState } from 'react';
import { Button, Input, Pagination, Table, Tag, Typography } from 'antd';
import { RightOutlined, SearchOutlined } from '@ant-design/icons';
import { explainValue, stateLabel, stateTone, text, timestampRaw, timestampText } from '../facts';
import type { TaskIndexRow } from '../types';
import { countProjectTasks, filterProjectTasks, taskFilters, type TaskFilter } from './projectTaskView';
import { TaskNoteDialog } from './TaskNoteDialog';

/* 沿用现有 CSS 色调契约：未知或不可用状态不使用成功色。 */
const toneColor: Record<string, string | undefined> = { blocked: 'error', completed: 'success', active: 'processing', unknown: 'warning' };
const PAGE_SIZE = 10;

function chineseState(row: TaskIndexRow): string {
    const state = text(row.state).trim().toUpperCase();
    return stateLabel('task', state).split(' · ')[0];
}

function RecordedResponsibility({ row }: { row: TaskIndexRow }) {
    const phaseRaw = text(row.phase);
    const ownerRaw = text(row.owner);
    const phaseText = (explainValue('phase', phaseRaw) || phaseRaw || '未记录').split('（')[0];
    const ownerText = (explainValue('owner', ownerRaw) || ownerRaw || '责任角色未记录').split('（')[0];
    return <><span title={phaseRaw || undefined}>{phaseText}</span><Typography.Text type="secondary" title={ownerRaw || undefined}>{ownerText}</Typography.Text></>;
}

function NoteCell({ taskId, note, onEdit }: {
    taskId: string;
    note: TaskIndexRow['note'];
    onEdit: () => void;
}) {
    const unavailable = note === null;
    const label = unavailable ? '备注暂不可读，点击重试' : note?.trim() || '添加备注';
    return <Button type="link" size="small" className={`link task-index-note${unavailable ? ' is-unavailable' : ''}`}
      aria-label={`任务 ${taskId} 备注：${label}`}
      onClick={event => { event.stopPropagation(); onEdit(); }}><span>{label}</span></Button>;
}

export function TaskIndex({ contextKey, rows, available = true, notesWritable, onSelect, onNoteSaved }: {
    contextKey: string;
    rows: TaskIndexRow[];
    available?: boolean;
    notesWritable: boolean;
    onSelect: (id: string) => void;
    onNoteSaved: () => void;
}) {
    const [query, setQuery] = useState(''), [filter, setFilter] = useState<TaskFilter>('in_progress'), [page, setPage] = useState(1);
    const [noteTask, setNoteTask] = useState<TaskIndexRow>();
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
        : filter === 'other' ? '当前没有其他任务；可切换到其他筛选查看。'
        : '没有匹配项；可清空搜索或筛选。';
    function chooseFilter(next: TaskFilter) {
        setFilter(next);
        setPage(1);
    }
    return <div className="task-index">
    <div className="task-index-controls">
      <div className="task-index-filter-bar" role="group" aria-label="任务状态筛选">
        {taskFilters.map(item => <button type="button" key={item.key} className={`task-filter-pill${filter === item.key ? ' is-active' : ''}`} aria-pressed={filter === item.key} onClick={() => chooseFilter(item.key)}>
          <span>{item.label}</span><span className="task-filter-count">{available ? counts[item.key] : '—'}</span>
        </button>)}
      </div>
      <div className="task-index-query"><Input id={`${id}-query`} type="search" allowClear prefix={<SearchOutlined/>} aria-label="搜索任务" value={query} onChange={e => { setQuery(e.target.value); setPage(1); }} placeholder="搜索任务名称、备注、阶段或责任人…"/></div>
    </div>
    <Table<TaskIndexRow> className="task-index-table" size="small" rowKey="task_id" dataSource={visible} pagination={false}
      locale={{ emptyText }} onRow={row => ({ onClick: () => onSelect(row.task_id) })} columns={[
            { title: '任务名称', render: (_, row) => <div className="task-index-title-cell">
              <Button type="link" className="link task-index-title" onClick={event => { event.stopPropagation(); onSelect(row.task_id); }}>{row.title || '未记录'}</Button>
              {row.workflow_mode === 'quick' && <Tag>快速开发</Tag>}{row.domain === 'video' && <Tag>视频制作</Tag>}
              <small><code>{row.task_id || '任务 ID 未记录'}</code></small>
              <div className="task-index-mobile-responsibility"><RecordedResponsibility row={row}/></div>
            </div> },
            { title: '状态', className: 'task-index-status-column', dataIndex: 'state', render: (_, row) => { const state = text(row.state).trim().toUpperCase(); return <div className="task-index-status"><Tag variant="filled" color={toneColor[stateTone('task', state)]}>{chineseState(row)}</Tag>{row.retired === true && <Tag>已退休</Tag>}</div>; } },
            { title: '阶段 / 责任人', className: 'task-index-responsibility-column', render: (_, row) => <div className="task-index-stage-owner"><RecordedResponsibility row={row}/></div> },
            { title: '备注', className: 'task-index-note-column', hidden: !notesWritable, render: (_, row) => row.task_id
                ? <NoteCell taskId={row.task_id} note={row.note}
                    onEdit={() => setNoteTask(row)}/> : '—' },
            { title: '更新时间', className: 'task-index-date-column', dataIndex: 'updated_at', render: (_, row) => { const raw = timestampRaw(row.updated_at), display = timestampText(row.updated_at); return <span className="task-date-cell"><time dateTime={raw || undefined} title={text(row.updated_at) || '未记录'}>{raw ? display.slice(5, 16) : display}</time><RightOutlined className="task-row-chevron"/></span>; } },
    ]}/>
    <div className="task-index-footer">
      <p className="muted result-count" role="status">{available ? `匹配 ${filtered.length} / ${rows.length} 项` : '任务数据不可用，未计算匹配数量。'}</p>
      {available && filtered.length > 0 && <Pagination size="small" current={currentPage} pageSize={PAGE_SIZE} total={filtered.length}
        showSizeChanger={false} showTotal={(_total, range) => `第 ${range[0]}-${range[1]} 条`} onChange={setPage}/>}
    </div>
    {noteTask && <TaskNoteDialog contextKey={contextKey} task={noteTask} onClosed={() => setNoteTask(undefined)}
      onSaved={onNoteSaved}/>}
  </div>;
}
