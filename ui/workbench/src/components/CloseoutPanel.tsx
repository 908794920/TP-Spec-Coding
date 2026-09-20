import { Alert, Button, Typography } from 'antd';
import { record, stateLabel, valueText } from '../facts';
import type { CloseoutData, Envelope, ReadState } from '../types';
import { Disclosure, Fields, Problems, ReadStatus, Section } from './Facts';
export function CloseoutPanel({ read, requested, onRequest, taskRevision }: {
  read: ReadState<Envelope<CloseoutData>>; requested: boolean; onRequest: () => void; taskRevision?: string;
}) {
  const data = read.data?.data, route = record(data?.route);
  const mismatch = !!read.data && read.data.read.task_revision !== taskRevision;
  return <Section title="只读结单预检">
    <p className="muted">仅调用现有预检，不执行 Verify、Review、Delivery 或 Complete。显示返回的所有条目，不自行补算门禁。</p>
    <Button onClick={onRequest} disabled={read.loading}>{requested ? '重新读取预检' : '读取结单预检'}</Button>
    {!requested && <p className="muted">未取得结单预检结果。</p>}
    <ReadStatus {...read}/>
    {data && <>
      {mismatch && <p className="warning" role="status">预检与画布的账本读取版本不同，请重新读取页面；以下只对应预检标明的读取时间。</p>}
      <Problems items={data.problems}/>
      <p className="muted">{stateLabel('task', data.state)}</p>
      {/* The tri-state deliberately never uses the success type: "允许 Complete" is not a completion
          claim, and an unconfirmed verdict stays a plain neutral line rather than a coloured box. */}
      {data.ready === true ? <Alert type="info" showIcon title="本次预检允许 Complete（尚未执行结单）"/>
          : data.ready === false ? <Alert type="warning" showIcon title="本次预检不允许 Complete"/>
              : <p className="muted">预检就绪结论未确认。</p>}
      <Typography.Title level={5}>返回的 blockers · {Array.isArray(data.blockers) ? data.blockers.length : '格式未确认'}</Typography.Title>
      {Array.isArray(data.blockers) && <ol className="blocker-list">{data.blockers.map((row, i) => <li key={i}><pre>{valueText(row)}</pre></li>)}</ol>}
      <Disclosure label="验收问题（预检原字段，可能与 blockers 重复）" open><Fields value={{ acceptance_issues: data.acceptance_issues }}/></Disclosure>
      <Fields value={{ source: data.source, coverage_note: data.coverage_note,
        responsibility: route.next_responsibility ?? route.role_id, waiting: record(route.context).waiting,
        blocker: route.blocker, reason_codes: route.reason_codes }} labels={{ source: '来源', coverage_note: '覆盖边界', responsibility: '路由责任方（不套给每条问题）', waiting: '结构化等待/恢复条件', blocker: '路由阻塞', reason_codes: '原因代码' }}/>
      <Disclosure label="完整预检响应"><Fields value={data}/></Disclosure>
    </>}
  </Section>;
}
