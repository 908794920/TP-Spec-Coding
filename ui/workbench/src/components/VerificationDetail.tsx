import { record, records, text, valueText } from '../facts';
import type { DetailData } from '../types';
import { CopyText, Fields } from './Facts';
const applicability: Record<string, string> = {
  current: '本次读取确认适用', stale: '历史结果已失效', not_confirmed: '当前适用性未确认',
  not_recorded: '未记录', per_ac: '仅按下方 AC 逐项解释',
};
export function Outcome({ title, value }: { title: string; value: unknown }) {
  const channel = record(value), event = record(channel.recorded), detail = record(event.detail);
  const scope = record(channel.history_scope);
  return <section className="detail-section"><h4>{title}</h4>
    <p><strong>{applicability[text(channel.applicability)] ?? `${valueText(channel.applicability)}（未识别）`}</strong></p>
    {channel.recorded ? <>
      <Fields value={{ recorded_decision: event.decision, result_status: event.result_status, scope: channel.scope ?? detail.verification_scope,
        delivery_status: detail.delivery_status, ledger_trusted: channel.ledger_trusted, reasons: channel.reasons,
        source: channel.source, event_id: event.event_id, created_at: event.created_at }}
        labels={{ recorded_decision: '记录的结论', result_status: '记录的执行状态', scope: '验证范围', delivery_status: '记录的交付状态', ledger_trusted: '通过既有账本读取', reasons: '适用性说明', source: '判定来源', event_id: '事件 ID', created_at: '记录时间' }}/>
      <details><summary>最新记录的绑定与原始明细</summary><Fields value={detail}/><p className="muted">历史摘要（不作为 PASS 判断）：{valueText(event.summary)}</p></details>
    </> : <p className="muted">未取得结构化结果；不使用摘要或其他角色的结论补齐。</p>}
    {records(channel.history).length > 0 && <details><summary>历史记录 · {valueText(scope.returned)} / {valueText(scope.total)}</summary>
      <p className="muted">最多最近 {valueText(scope.limit)} 条；历史结果不代表当前仍有效。</p>
      {records(channel.history).map((row, i) => <details key={`${text(row.event_id)}:${i}`}><summary>#{text(row.event_id)} · {text(row.created_at)} · {text(row.decision)}</summary><Fields value={row}/></details>)}
    </details>}
  </section>;
}
export function VerificationDetail({ data }: { data: DetailData }) {
  const acceptance = record(data.acceptance), owner = record(data.owner_acceptance), effective = record(owner.effective);
  return <>
    <Outcome title="自动化验证 · Verification" value={data.verification}/>
    <Outcome title="代码审查 · Review" value={data.review}/>
    <section className="detail-section"><h4>人工验收与处置</h4>
      <p className="muted">实际 accept、延期 defer、豁免 waive 分开记录；人验不证明机器测试已执行，也不代表用户已接收所有交付。</p>
      <Fields value={{ evaluation: owner.evaluation, source: owner.source, accepted_acs: effective.accepted_acs,
        visual_acs: effective.visual_acs, subject_digest: effective.subject_digest, change_set_id: effective.change_set_id, reasons: owner.reasons }}
        labels={{ evaluation: '本次判定', source: '来源', accepted_acs: '当前有效实际人验 AC', visual_acs: '当前有效视觉 AC', subject_digest: '受验主体', change_set_id: '受验产品', reasons: '未确认原因' }}/>
      {Object.entries(record(effective.by_ac)).map(([ac, value]) => <details key={ac}><summary>{ac} · {valueText(record(value).mode)}</summary><Fields value={value}/></details>)}
      <Outcome title="Owner 原始决定与历史" value={owner}/>
    </section>
    <section className="detail-section"><h4>验收矩阵（工件声明）</h4>
      <p className="muted">以下逐行展示 acceptance.md，不将文件中的 PASS 自动认定为可信验收。未取得与当前不适用分别保留；最终问题通过只读结单预检查看。</p>
      <CopyText value={acceptance.source} label="复制工件路径"/>
      <Fields value={{ read_status: acceptance.status, issues: acceptance.issues, pending: acceptance.pending }}/>
      {records(acceptance.rows).map((row, i) => <details key={`${text(row.ac)}:${text(row.line)}:${i}`}>
        <summary>{text(row.ac)} · 声明 {valueText(row.declared_verdict)}</summary>
        <Fields value={row} labels={{ condition: '验收条件', requirement_source: '需求来源', risk: '风险', method: '验证方式', witness: '见证等级', declared_verdict: '原始声明结论', line: '来源行' }}/>
        <CopyText value={row.evidence} label="复制证据引用"/>
      </details>)}
      <details><summary>页面/视觉声明、延期/豁免、数据库操作</summary><Fields value={{ page_verification: acceptance.page_verification,
        deferred: acceptance.deferred, waived: acceptance.waived, database_operations: acceptance.database_operations,
        no_acceptance_required: acceptance.no_acceptance_required }}/></details>
    </section>
  </>;
}
