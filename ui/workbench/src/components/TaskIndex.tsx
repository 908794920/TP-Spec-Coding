import { useId, useMemo, useState } from 'react';
import { filterTasks, stateLabel } from '../facts';
import type { TaskIndexRow } from '../types';
export function TaskIndex({ rows, selected = '', onSelect, compact = false }: {
    rows: TaskIndexRow[];
    selected?: string;
    onSelect: (id: string) => void;
    compact?: boolean;
}) {
    const [query, setQuery] = useState(''), [state, setState] = useState('');
    const id = useId();
    const filtered = useMemo(() => filterTasks(rows, query, state), [rows, query, state]);
    const states = [...new Set(rows.map(row => row.state))].filter(Boolean).sort();
    return <div className={compact ? 'task-index compact' : 'task-index'}>
    <div className="filters"><label htmlFor={`${id}-query`}>搜索任务<input id={`${id}-query`} type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="ID、标题或负责人"/></label>
      <label htmlFor={`${id}-state`}>正式状态<select id={`${id}-state`} value={state} onChange={e => setState(e.target.value)}><option value="">全部状态</option>{states.map(s => <option key={s} value={s}>{stateLabel('task', s)}</option>)}</select></label></div>
    <p className="muted result-count">显示 {filtered.length} / {rows.length} 项{state || query ? '（已筛选）' : ''}</p>
    {compact ? <ul className="task-nav">{filtered.map(row => <li key={row.task_id}><button type="button" className={selected === row.task_id ? 'selected' : ''} onClick={() => onSelect(row.task_id)} aria-current={selected === row.task_id ? 'page' : undefined}>
      <code>{row.task_id}</code><span className="truncate" title={row.title}>{row.title || '标题未记录'}</span><small>{stateLabel('task', row.state)}{row.retired ? ' · 已退休' : ''}</small></button></li>)}</ul>
            : <div className="table-scroll" tabIndex={0} role="region" aria-label="项目任务索引"><table className="task-table"><thead><tr><th>Task</th><th>标题</th><th>正式状态</th><th>阶段 / 负责人</th><th>更新时间</th></tr></thead><tbody>{filtered.map(row => <tr key={row.task_id}>
        <td><button className="link" type="button" onClick={() => onSelect(row.task_id)}>{row.task_id}</button></td><td>{row.title || '未记录'}</td><td>{stateLabel('task', row.state)}{row.retired ? ' · 已退休' : ''}</td><td>{row.phase || '未记录'}<br /><span className="muted">{row.owner || '负责人未记录'}</span></td><td><time>{row.updated_at || '未记录'}</time></td>
      </tr>)}</tbody></table></div>}
    {!filtered.length && <p className="muted">{rows.length ? '没有匹配项；可清空搜索或筛选。' : '当前项目没有已取得的任务。'}</p>}
  </div>;
}
