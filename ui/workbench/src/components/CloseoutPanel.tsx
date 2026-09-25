import { Alert, Button, Typography } from 'antd';
import { record, records, stateLabel, valueText } from '../facts';
import type { CloseoutData, Envelope, ReadState } from '../types';
import { Disclosure, Fields, Problems, ReadStatus, Section } from './Facts';

export function CloseoutPanel({ read, requested, onRequest, taskRevision }: {
  read: ReadState<Envelope<CloseoutData>>; requested: boolean; onRequest: () => void; taskRevision?: string;
}) {
  const data = read.data?.data, route = record(data?.route);
  const mismatch = !!read.data && read.data.read.task_revision !== taskRevision;
  const historical = mismatch || read.loading || !!read.error;
  const checks = records(data?.checks);
  return <Section title="只读结单预检">
    <p className="muted">读取 Runtime 的缺口、未知项、处理依赖与责任方，不执行验证、修复、清理或结单。检查通过不是业务验收。</p>
    <Button onClick={onRequest} disabled={read.loading}>{requested ? '重新读取预检' : '读取结单预检'}</Button>
    {!requested && <p className="muted">未取得结单预检结果。</p>}
    <ReadStatus {...read}/>
    {data && <>
      {historical && <Alert type="warning" showIcon title="以下是上次预检，不作为当前就绪结论"
        description={mismatch ? '预检与任务的账本观察版本不同，请刷新任务并重新读取预检。' : '刷新尚未完成或读取失败；保留上次结果与原读取时间。'}/>}
      <Problems items={data.problems}/>
      <p className="muted">{stateLabel('task', data.state)}</p>
      {data.already_terminal === true
        ? <Alert type="info" showIcon title={`已记录终态：${stateLabel('task', data.state)}`} description="只读返回原终态，不重复结单、不追补新义务，也未重新验证历史交付。"/>
        : !historical && (data.ready === true
          ? <Alert type="info" showIcon title="本次预检允许 Complete（尚未执行结单）"/>
          : data.ready === false
            ? <Alert type="warning" showIcon title="本次预检不允许 Complete；先处理已知缺口和未知项"/>
            : <p className="muted">预检就绪结论未确认。</p>)}
      {checks.length > 0 && <>
        <Typography.Title level={5}>逐项检查 · {checks.length}</Typography.Title>
        {checks.map((check, i) => <Disclosure key={`${valueText(check.id)}:${i}`}
          label={`${valueText(check.id)} · ${valueText(check.status)}`}>
          <Fields value={check} labels={{ id: '检查项', status: '本次判定', required: '当前必需',
            responsibility: '该项责任方', depends_on: '处理依赖', issues: '缺口或未知原因', facts: '依据及适用性' }}/>
        </Disclosure>)}
        <Disclosure label="处理顺序与下一责任" open>
          <Fields value={{ next_actions: data.next_actions, unknowns: data.unknowns }}
            labels={{ next_actions: 'Runtime 返回的处理依赖（不自动执行）', unknowns: '尚未确定的必需检查' }}/>
        </Disclosure>
      </>}
      <Disclosure label={`返回的 blockers · ${Array.isArray(data.blockers) ? data.blockers.length : '格式未确认'}`} open={!checks.length}>
        {Array.isArray(data.blockers) && <ol className="blocker-list">{data.blockers.map((row, i) => <li key={i}><pre>{valueText(row)}</pre></li>)}</ol>}
      </Disclosure>
      <Disclosure label="验收原始问题（可能与检查项重复）"><Fields value={{ acceptance_issues: data.acceptance_issues }}/></Disclosure>
      <Fields value={{ source: data.source, coverage_note: data.coverage_note,
        effective_level: data.effective_level, included_stages: data.included_stages,
        responsibility: route.next_responsibility ?? route.role_id, waiting: record(route.context).waiting,
        blocker: route.blocker, reason_codes: route.reason_codes }} labels={{ source: '来源', coverage_note: '覆盖边界',
          effective_level: '统一有效等级', included_stages: '本任务适用步骤',
          responsibility: '路由责任方（不套给每条问题）', waiting: '结构化等待/恢复条件', blocker: '路由阻塞', reason_codes: '原因代码' }}/>
      <Disclosure label="完整预检响应"><Fields value={data}/></Disclosure>
    </>}
  </Section>;
}
