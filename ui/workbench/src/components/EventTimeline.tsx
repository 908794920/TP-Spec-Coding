import { Table, Typography } from 'antd';
import { explainValue, records, text, record, timestampRaw, timestampText, valueText } from '../facts';
import type { FactRecord } from '../types';
import { CopyText, Disclosure, Fields } from './Facts';
type EventRow = FactRecord & { __rowKey: string };
export function EventTimeline({ events, scope, workItemId }: { events: unknown; scope: unknown; workItemId?: string }) {
  const all = records(events), meta = record(scope);
  const rows = workItemId ? all.filter(row => text(row.work_item_id) === workItemId) : all;
  const truncated = typeof meta.total === 'number' && meta.total > all.length;
  /* Keys are precomputed so `rowKey` never needs the deprecated index parameter. */
  const data: EventRow[] = rows.map((row, i) => ({ ...row, __rowKey: `${text(row.id)}:${i}` }));
  return <Disclosure className="event-timeline" label={`${workItemId ? `WorkItem ${workItemId} 的已绑定事件` : 'Task 事件时间线'} · 已取得 ${rows.length} 条`}>
    <p className="muted">本响应包含 Task 最近 {all.length}{typeof meta.total === 'number' ? ` / ${meta.total}` : ''} 条事件{typeof meta.limit === 'number' ? `，上限 ${meta.limit} 条` : ''}。{truncated ? '历史已截断，未加载完整历史。' : ''}{workItemId ? '仅按正式 work_item_id 筛选，不按摘要或 ID 名称猜测。' : ''}事件记录不代表当前证据仍然有效。</p>
    {rows.length ? <div className="table-scroll" tabIndex={0} role="region" aria-label="已取得的历史事件"><Table<EventRow> size="small" rowKey="__rowKey" dataSource={data} pagination={false} scroll={{ x: 550 }} columns={[
        { title: '时间 / ID', render: (_, row) => <><time dateTime={timestampRaw(row.created_at) || undefined} title={timestampRaw(row.created_at) || undefined}>{timestampText(row.created_at)}</time><CopyText value={row.source_event_id ?? row.id} label="复制事件 ID"/></> },
        { title: '类型 / 角色', render: (_, row) => <>{explainValue('event_type', row.event_type) || valueText(row.event_type)}<br /><Typography.Text type="secondary">{explainValue('actor', row.actor) || valueText(row.actor)}</Typography.Text></> },
        { title: '结构化结果与来源', render: (_, row) => <><Fields value={{ decision: row.decision, result_status: row.result_status, operation: row.operation }}/>
          <p>历史摘要：{valueText(row.summary)}</p><Disclosure label="来源与原始明细"><Fields value={{ source_event_id: row.source_event_id, work_item_id: row.work_item_id, source_kind: row.source_kind, detail: row.detail }}/><CopyText value={row.evidence_path} label="复制证据引用"/></Disclosure></> },
    ]}/></div> : <p>{workItemId ? '本次已取得事件中没有该 WorkItem 的明确绑定记录；不代表它没有其他历史。' : '尚未取得事件记录。'}</p>}
  </Disclosure>;
}
