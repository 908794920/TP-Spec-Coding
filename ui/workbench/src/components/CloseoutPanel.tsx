import { Alert, Button } from 'antd';
import { record, stateLabel, text, valueText } from '../facts';
import type { CloseoutCondition, CloseoutData, Envelope, FactRecord, ReadState } from '../types';
import { responsibilityLabel } from './ExecutionWorkflow';
import { Disclosure, Fields, Problems, ReadStatus, Section } from './Facts';
import { QuickWorkflowSummary } from './QuickWorkflowSummary';

const statusLabels: Record<string, string> = {
  CURRENT_GAP: '待处理', OWNER_PENDING: '待用户确认', REGISTRATION_PENDING: '待登记',
  NOT_YET_DUE: '后续到期', BLOCKED_BY_UPSTREAM: '等待上游',
  REUSABLE: '可复用', OWNER_DEFERRED: '已正式延期', UNKNOWN: '待核实',
};

const openParticipations = 'EXECUTION_PARTICIPATIONS_OPEN: ';

function issueKey(issue: string) {
  return issue.trim().replace(/^[A-Za-z]+Error:\s*/, '');
}

function issueLabel(issue: string) {
  const key = issueKey(issue);
  if (key.startsWith(openParticipations)) return '尚有未结束的参与：' + key.slice(openParticipations.length);
  if (key.startsWith('EXECUTION_STEPS_PENDING: ')) return key.replace('EXECUTION_STEPS_PENDING: ', '尚未完成的执行步骤：');
  if (issue === 'step is WAITING; resume along its existing condition before completing') return '按已登记的条件恢复步骤后才能完成。';
  if (issue.endsWith('DELIVERY_REQUIRES_CURRENT_VERIFICATION_PASS')) return '当前主体尚无可用的验证通过记录。';
  if (issue.includes('CHANGE_SET_REQUIRED: no explicit development product binding')) return '尚未登记开发结果对应的产品主体。';
  return issue.replace(/^(?:[A-Za-z]+Error:\s*)?(?:[A-Z][A-Z0-9_]+:\s*)?/, '');
}

const conditionTitles: Record<string, string> = {
  verify_step: '验证步骤', review: '代码审查', delivery: '交付', work: '子工作', execution: '执行步骤',
  route: '流程路由', stage_records: '阶段记录',
};

function includeUnlistedChecks(data: CloseoutData, currentStep: FactRecord, groups: CloseoutCondition[],
  bound: CloseoutCondition[], unbound: CloseoutCondition[]) {
  const seen = new Set(groups.flatMap(row => row.issues.map(issueKey)));
  const participationIds = new Set(Array.isArray(currentStep.participation_ids) ? currentStep.participation_ids : []);
  function add(rows: CloseoutCondition[], condition: CloseoutCondition) {
    if (!condition.issues.length) return;
    const index = rows.findIndex(row => row.node === condition.node);
    if (index === -1) rows.push(condition);
    else rows[index] = { ...rows[index], issues: [...rows[index].issues, ...condition.issues] };
  }
  for (const check of data.checks ?? []) {
    if (!check.required || check.status !== 'PENDING' ||
        data.downstream_closeout_pending?.some(row => row.node === check.id)) continue;
    const stepIssues: string[] = [], taskIssues: string[] = [];
    for (const issue of check.issues) {
      if (typeof issue !== 'string' || !issue.trim()) continue;
      const key = issueKey(issue);
      if (seen.has(key)) continue;
      seen.add(key);
      if (currentStep.id && key.startsWith(openParticipations)) {
        const ids = key.slice(openParticipations.length).split(',').map(id => id.trim());
        const atStep = ids.filter(id => participationIds.has(id));
        const elsewhere = ids.filter(id => !participationIds.has(id));
        if (atStep.length) stepIssues.push(openParticipations + atStep.join(', '));
        if (elsewhere.length) taskIssues.push(openParticipations + elsewhere.join(', '));
      } else {
        const atStep = currentStep.id && check.facts.step_id === currentStep.id;
        (atStep ? stepIssues : taskIssues).push(issue);
      }
    }
    const condition = { node: check.id, status: 'CURRENT_GAP', responsibility: check.responsibility };
    add(bound, { ...condition, issues: stepIssues });
    add(unbound, { ...condition, issues: taskIssues });
  }
}

function Conditions({ data, currentStep }: { data: CloseoutData; currentStep: FactRecord }) {
  const nodes = new Map((data.nodes ?? []).map(node => [node.id, node]));
  const currentStepId = text(currentStep.id);
  const label = (id: string) => {
    const node = nodes.get(id);
    return (currentStepId && node?.facts.step_id === currentStepId ? text(currentStep.title) : '') ||
      conditionTitles[id] || node?.title || id;
  };
  const actions = new Map((data.next_actions ?? []).map(action => [action.check_id, action]));
  const atStep = (row: CloseoutCondition) => !!currentStepId && nodes.get(row.node)?.facts.step_id === currentStepId;
  const current = data.current_stage_blockers ?? [];
  const bound = current.filter(atStep), unbound = current.filter(row => !atStep(row));
  const downstream = data.downstream_closeout_pending ?? [];
  const other = [...nodes.values()].filter(node => ['REUSABLE', 'OWNER_DEFERRED', 'UNKNOWN'].includes(node.status));
  const unknownChecks = (data.unknowns ?? []).filter(id => nodes.get(id)?.status !== 'UNKNOWN');
  const hasGroups = Array.isArray(data.current_stage_blockers) && Array.isArray(data.downstream_closeout_pending);
  if (hasGroups) includeUnlistedChecks(data, currentStep, [...current, ...downstream, ...other.map(node => ({ ...node, node: node.id }))], bound, unbound);
  const row = (condition: CloseoutCondition) => {
    const facts = nodes.get(condition.node)?.facts;
    const action = actions.get(condition.node);
    const later = downstream.some(row => row.node === condition.node);
    const dependencies = Array.from(new Set([
      ...(text(facts?.blocked_by) ? [text(facts?.blocked_by)] : []),
      ...(Array.isArray(action?.depends_on) ? action.depends_on.map(text).filter(id =>
        id && (later || !downstream.some(row => row.node === id))) : []),
    ]));
    const issues = later ? [] : Array.from(new Set([text(facts?.wait_reason), ...condition.issues.map(issueLabel)].filter(Boolean)));
    return <li key={condition.node}>
      <strong>{label(condition.node)}</strong> · {statusLabels[condition.status] || condition.status}
      <span className="muted"> · 责任方：{responsibilityLabel(condition.responsibility)}</span>
      {dependencies.length > 0 && <div>{later ? '依赖' : '先处理'}：{dependencies.map(label).join('、')}</div>}
      {issues.map(issue => <div key={issue}>{issue}</div>)}
    </li>;
  };
  return <>
    <h5>本步缺口</h5>
    {bound.length ? <ul className="blocker-list">{bound.map(row)}</ul>
      : <p className="muted">{hasGroups ? '本次预检没有明确绑定到当前步骤的缺口。' : '本次预检未提供步骤归属，仍待核实。'}</p>}
    {unbound.length > 0 && <><h5>任务层待处理</h5><p className="muted">以下缺口未绑定到当前步骤。</p><ul className="blocker-list">{unbound.map(row)}</ul></>}
    {!hasGroups && data.blockers?.length > 0 && <><h5>任务层待处理</h5><ul className="blocker-list">
      {data.blockers.map((item, index) => <li key={index}>{valueText(item)}</li>)}
    </ul></>}
    {downstream.length > 0 && <><h5>下游条件</h5><ul className="blocker-list">{downstream.map(row)}</ul></>}
    {other.length > 0 && <><h5>其他预检结果</h5><ul className="blocker-list">{other.map(node => row({ ...node, node: node.id }))}</ul></>}
    {unknownChecks.length > 0 && <p className="warning" role="status">尚未取得确定结果：{unknownChecks.map(label).join('、')}</p>}
  </>;
}

export function CloseoutPanel({ read, requested, onRequest, taskRevision, currentStep }: {
  read: ReadState<Envelope<CloseoutData>>; requested: boolean; onRequest: () => void; taskRevision?: string; currentStep: FactRecord;
}) {
  const data = read.data?.data, route = record(data?.route);
  const readStep = record(record(record(route.context).execution).current_step);
  const mismatch = !!read.data && read.data.read.task_revision !== taskRevision;
  const historical = mismatch || read.loading || !!read.error;
  return <Section title="只读结单预检">
    <Button onClick={onRequest} disabled={read.loading}>{requested ? '重新读取预检' : '读取结单预检'}</Button>
    <ReadStatus {...read} showDetails={false}/>
    {data && <>
      {historical && <Alert type="warning" showIcon title={mismatch ? '预检已过期' : '以下为上次预检'}
        description={mismatch ? '任务记录已有变化，请重新读取预检。' : '当前结论仍待核实。'}/>}
      <Problems items={data.problems}/>
      {data.already_terminal === true
        ? <Alert type="info" showIcon title={data.retired === true ? '已退休 · 历史记录' : '任务已结束 · 历史记录'}
            description={stateLabel('task', data.state)}/>
        : <>
          {!historical && data.ready === true && <Alert type="info" showIcon title="本次预检已满足结单条件"/>}
          <Conditions data={data} currentStep={readStep.id ? readStep : mismatch ? {} : currentStep}/>
        </>}
      {(data.workflow_mode === 'quick' || route.workflow_mode === 'quick') &&
        <QuickWorkflowSummary workflow={data.quick_status ? data : route} terminal={data.already_terminal === true}/>}
      <Disclosure label="预检明细与来源">
        <Fields value={data} labels={{ current_stage_blockers: '当前缺口', downstream_closeout_pending: '下游条件',
          nodes: '判定节点及绑定', next_actions: '处理依赖', unknowns: '尚未确定的必需检查', source: '预检来源' }}/>
      </Disclosure>
    </>}
  </Section>;
}
