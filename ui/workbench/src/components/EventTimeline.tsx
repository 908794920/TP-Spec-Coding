import { records, text, record, valueText } from '../facts';
import { CopyText, Fields } from './Facts';
export function EventTimeline({ events, scope, workItemId }: { events: unknown; scope: unknown; workItemId?: string }) {
  const all = records(events), meta = record(scope);
  const rows = workItemId ? all.filter(row => text(row.work_item_id) === workItemId) : all;
  const truncated = typeof meta.total === 'number' && meta.total > all.length;
  return <details className="event-timeline"><summary>{workItemId ? `WorkItem ${workItemId} 的已绑定事件` : 'Task 事件时间线'} · 已取得 {rows.length} 条</summary>
    <p className="muted">本响应包含 Task 最近 {all.length}{typeof meta.total === 'number' ? ` / ${meta.total}` : ''} 条事件{typeof meta.limit === 'number' ? `，上限 ${meta.limit} 条` : ''}。{truncated ? '历史已截断，未加载完整历史。' : ''}{workItemId ? '仅按正式 work_item_id 筛选，不按摘要或 ID 名称猜测。' : ''}事件记录不代表当前证据仍然有效。</p>
    {rows.length ? <div className="table-scroll" tabIndex={0} role="region" aria-label="已取得的历史事件"><table><thead><tr><th>时间 / ID</th><th>类型 / 角色</th><th>结构化结果与来源</th></tr></thead><tbody>{rows.map((row, i) => <tr key={`${text(row.id)}:${i}`}>
      <td><time>{valueText(row.created_at)}</time><CopyText value={row.source_event_id ?? row.id} label="复制事件 ID"/></td>
      <td>{valueText(row.event_type)}<br/><span className="muted">{valueText(row.actor)}</span></td>
      <td className="event-summary"><Fields value={{ decision: row.decision, result_status: row.result_status, operation: row.operation }}/>
        <p>历史摘要：{valueText(row.summary)}</p><details><summary>来源与原始明细</summary><Fields value={{ source_event_id: row.source_event_id, work_item_id: row.work_item_id, source_kind: row.source_kind, detail: row.detail }}/><CopyText value={row.evidence_path} label="复制证据引用"/></details></td>
    </tr>)}</tbody></table></div> : <p>{workItemId ? '本次已取得事件中没有该 WorkItem 的明确绑定记录；不代表它没有其他历史。' : '尚未取得事件记录。'}</p>}
  </details>;
}
