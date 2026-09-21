import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { Alert, Button, Select, Table, Tag } from 'antd';
import { record, records, text, timestampText, explainValue } from '../facts';
import type { FactRecord } from '../types';
import type { WorkflowHandle } from './WorkflowStrip';
import { CopyText, Disclosure, Fields } from './Facts';

const statusNames: Record<string, string> = {
  PLANNED: '计划', ACTIVE: '进行中', WAITING: '等待', COMPLETED: '已完成',
  HANDED_OFF: '已交接', PAUSED: '已暂停并结束工作段', WAITING_HUMAN: '等待人工（工作段已结束）',
  WAITING_AGENT: '等待角色（工作段已结束）', BLOCKED: '受阻（工作段已结束）',
  INTERRUPTED: '已中断', CANCELLED: '已取消',
};
const actions: Record<string, string> = { start: '开始', wait: '等待', resume: '恢复', complete: '步骤完成',
  completed: '工作段完成', handed_off: '交接', paused: '暂停', waiting_human: '等待人工',
  waiting_agent: '等待角色', blocked: '受阻', interrupted: '中断', cancelled: '取消' };
const strings = (value: unknown): string[] => Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
const roleLabel = (value: unknown): string => {
  const raw = text(value);
  const label = explainValue('actor', raw);
  return label ? label.split('（')[0] : raw || '责任未记录';
};
function RecordedTime({ value }: { value: unknown }) {
  return <span title={text(value)}>{value ? timestampText(value) : '历史未记录 / 未发生'}</span>;
}

export const ExecutionWorkflow = forwardRef<WorkflowHandle, { workflow: FactRecord; task: FactRecord }>(({ workflow, task }, ref) => {
  const facts = record(workflow.execution), plan = record(facts.plan), coordinator = record(facts.coordinator);
  const steps = records(facts.steps), participations = records(facts.participations), timeline = records(facts.timeline);
  const current = record(facts.current_step), next = record(facts.next_step), terminal = facts.terminal === true;
  const heading = useRef<HTMLHeadingElement>(null), list = useRef<HTMLOListElement>(null), detail = useRef<HTMLElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const [selection, setSelection] = useState<{ stepId: string; participationId?: string; role?: string }>();
  const [roleFilter, setRoleFilter] = useState<string>(), [stepFilter, setStepFilter] = useState<string>();
  const currentId = text(current.id);
  const selectedStep = steps.find(item => item.id === selection?.stepId);
  const selected = participations.find(item => item.participation_id === selection?.participationId);
  useEffect(() => {
    if (selection && (!selectedStep || (selection.participationId && !selected))) setSelection(undefined);
  }, [selection, selectedStep, selected]);
  useImperativeHandle(ref, () => ({ locateCurrent() {
    const target = Array.from(list.current?.querySelectorAll<HTMLElement>('[data-step-id]') ?? [])
      .find(element => !!currentId && element.dataset.stepId === currentId);
    const element = target ?? heading.current;
    element?.focus();
    element?.scrollIntoView({ block: 'nearest', inline: 'center', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  } }), [currentId]);
  function open(stepId: string, participationId?: string, role?: string) {
    returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setSelection({ stepId, participationId, role });
    requestAnimationFrame(() => detail.current?.focus());
  }
  function close() { setSelection(undefined); requestAnimationFrame(() => returnFocus.current?.focus()); }
  const rows = timeline.filter(row => (!roleFilter || row.actor === roleFilter) && (!stepFilter || row.step_id === stepFilter));
  const roleOptions = Array.from(new Set(timeline.map(row => text(row.actor)).filter(Boolean))).map(value => ({ value, label: roleLabel(value) }));
  const currentRoles = strings(facts.current_roles);
  const roleText = currentRoles.length ? currentRoles.map(roleLabel).join('、') : strings(current.roles).map(roleLabel).join('、');
  const status = terminal ? (task.state === 'COMPLETED' ? '已完成；无当前执行步骤' : '已停止；无当前执行步骤') :
    currentId ? `${text(current.title)} · ${statusNames[text(current.status)] || text(current.status)}` :
      steps.length && steps.every(step => step.status === 'COMPLETED') ? '计划步骤均已记录完成；Task 尚未正式结单' :
        steps.some(step => step.status === 'COMPLETED') ? '当前步骤已结束；下一步尚未开始' : '尚未开始；未将计划标为执行中';
  const history = records(facts.plan_history);
  const issues = strings(facts.issues);
  return <section className="workflow-strip execution-workflow" aria-label="任务执行计划">
    <div className="section-heading"><h3 ref={heading} tabIndex={-1}>执行计划 <small>v{text(facts.plan_version) || '未记录'} · 有效等级 {text(workflow.effective_level) || '未解析'}</small></h3>
      <Button size="small" onClick={() => {
        const target = Array.from(list.current?.querySelectorAll<HTMLElement>('[data-step-id]') ?? []).find(el => !!currentId && el.dataset.stepId === currentId);
        (target ?? heading.current)?.focus(); (target ?? heading.current)?.scrollIntoView({ block: 'nearest', inline: 'center' });
      }}>定位当前步骤</Button></div>
    {issues.length > 0 && <Alert type="warning" showIcon title="部分执行事实无法可靠读取" description={issues.join('；')}/>}
    {!terminal && text(plan.effective_level) && text(workflow.effective_level) && plan.effective_level !== workflow.effective_level && <Alert type="warning" showIcon title="有效等级已变化；需要复核未开始的计划" description={`登记时等级 ${text(plan.effective_level)}，当前等级 ${text(workflow.effective_level)}。历史不重写，实际门禁义务不随旧计划降低。`}/>}
    {!!text(workflow.error) && <Alert type="warning" showIcon title="门禁路由未解析；以下保留已登记事实" description={text(workflow.error)}/>}
    <p className="execution-coordinator">Task 协调责任：<strong>{roleLabel(coordinator.role)}</strong> · 执行者标识 {text(coordinator.agent) || '未记录'}<span className="muted">（不随步骤角色切换）</span></p>
    <div className="execution-summary" aria-live="polite">
      <p><span>当前位置</span><strong>{status}</strong></p>
      <p><span>{currentRoles.length ? '本步骤未结束参与角色' : '当前步骤预期责任'}</span><strong>{terminal ? '无；下方均为历史记录' : roleText || '尚无当前步骤'}</strong><small>未结束参与不证明 Agent 在线</small></p>
      <p><span>等待 / 下一责任</span><strong>{terminal ? '无' : text(current.wait_reason) || '未记录等待'}</strong><small>{terminal ? '' : text(current.expected_next_actor) ? `下一责任：${roleLabel(current.expected_next_actor)}` : next.id ? `计划下一步：${text(next.title)}` : '下一步未记录'}</small></p>
      <p><span>最近记录</span><RecordedTime value={facts.last_recorded_at}/></p>
    </div>
    {steps.length ? <ol className="flow-steps execution-steps" ref={list} aria-label="正式记录的步骤顺序">
      {steps.map(step => {
        const id = text(step.id), participants = participations.filter(p => p.step_id === id), isCurrent = !terminal && currentId === id;
        const stepStatus = text(step.status);
        return <li key={id} data-step-id={id} data-state={stepStatus} tabIndex={0} className={isCurrent ? 'current-step' : ''} aria-current={isCurrent ? 'step' : undefined}>
          <div className="execution-step-title"><Tag>{terminal && stepStatus !== 'COMPLETED' ? `历史：${statusNames[stepStatus] || stepStatus}` : statusNames[stepStatus] || stepStatus}</Tag><code>{id}</code></div>
          <Button type="text" className="step-title-button" onClick={() => open(id)}>{text(step.title)}</Button>
          <small>{text(step.phase)}{strings(step.depends_on).length ? ` · 依赖 ${strings(step.depends_on).join('、')}` : ''}</small>
          <div className="participation-nodes" aria-label={`${text(step.title)}的角色参与`}>
            {participants.map(p => <Button key={text(p.participation_id)} className="participation-node" size="small" onClick={() => open(id, text(p.participation_id))}>
              <span>{roleLabel(p.role)} · {terminal && !p.ended_at ? '历史未结束：' : ''}{statusNames[text(p.status)] || text(p.status)}</span><small>{text(p.work_item_id) || '父 Task'} · {text(p.participation_id).slice(-8)}</small></Button>)}
            {strings(step.roles).filter(role => !participants.some(p => p.role === role)).map(role => <Button key={role} className="participation-node planned-role" size="small" onClick={() => open(id, undefined, role)}>计划：{roleLabel(role)}</Button>)}
          </div>
          {strings(step.linked_work_items).length > 0 && <div className="participation-nodes" aria-label="关联子工作">
            {strings(step.linked_work_items).map(wid => <a key={wid} href={`#work-unit-${wid}`} onClick={() => {
              const target = document.getElementById(`work-unit-${wid}`);
              if (target instanceof HTMLDetailsElement) target.open = true;
            }}>{strings(step.fix_work_items).includes(wid) ? 'Fix' : 'Work'}：{wid}</a>)}
          </div>}
          {!!text(step.wait_reason) && <p className="warning">等待：{text(step.wait_reason)}</p>}
        </li>;
      })}
    </ol> : <p>没有可展示的执行步骤；不会用固定阶段补造记录。</p>}
    {selectedStep && <section className="participation-detail" ref={detail} tabIndex={-1} aria-labelledby="participation-heading" onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); close(); } }}>
      <div className="section-heading"><h4 id="participation-heading">{selected ? `${roleLabel(selected.role)} · 这次参与` : `${text(selectedStep.title)} · ${selection?.role ? roleLabel(selection.role) : '步骤详情'}`}</h4><Button size="small" onClick={close}>关闭参与详情</Button></div>
      {selected ? <>
        <CopyText value={selected.participation_id} label="复制参与 ID"/>
        <Fields value={{ step_id: selected.step_id, plan_version: selected.plan_version, work_item_id: selected.work_item_id,
          actor: selected.role, actor_agent: selected.agent, scope: selected.scope, recorded_status: `${terminal && !selected.ended_at ? '历史未结束：' : ''}${statusNames[text(selected.status)] || text(selected.status)}`,
          started_at: selected.started_at, ended_at: selected.ended_at, duration_seconds: selected.duration_seconds,
          result: selected.result, findings: selected.findings, decisions: selected.decisions, evidence_refs: selected.evidence_refs,
          wait_reason: selected.wait_reason, expected_next_actor: selected.expected_next_actor }} labels={{
            step_id: '步骤 ID', plan_version: '开始时计划版本', actor_agent: '执行者记录标识', recorded_status: '已记录状态',
            ended_at: '真实结束记录', duration_seconds: '起止跨度（秒，包含等待；未闭合则未知）', result: '已完成工作 / 结果',
            findings: '发现', decisions: '决定记录（不是授权）', evidence_refs: '证据引用（未核验适用性）',
            wait_reason: '阻塞 / 等待', expected_next_actor: '交接 / 下一责任' }}/>
        <Disclosure label="这次参与的开始、等待、恢复与结束记录">{records(selected.history).map(row => <Fields key={text(row.event_id)} value={row}/>)}</Disclosure>
      </> : <>
        <p className="muted">{selection?.role ? '该角色尚无实际参与记录，不能推断开始时间或完成工作。' : '步骤边界是发生记录，不替代专业验证、审查或人工验收。'}</p>
        <Fields value={selectedStep} labels={{ id: '步骤 ID', roles: '预期角色', depends_on: '前置步骤', work_item_ids: '关联 Work', status: '步骤记录状态', evidence_refs: '引用（非 PASS）' }}/>
      </>}
    </section>}
    <section className="execution-timeline" aria-label="角色步骤时间线">
      <h4>角色 / 步骤活动</h4><div className="execution-filters">
        <label>角色<Select aria-label="按角色筛选" allowClear placeholder="全部角色" value={roleFilter} options={roleOptions} onChange={setRoleFilter}/></label>
        <label>步骤<Select aria-label="按步骤筛选" allowClear placeholder="全部步骤" value={stepFilter} options={steps.map(step => ({ value: text(step.id), label: text(step.title) }))} onChange={setStepFilter}/></label>
        <span role="status" className="muted">匹配 {rows.length} / {timeline.length} 条已记录边界</span>
      </div>
      <Table<FactRecord> size="small" key={`${roleFilter || ''}:${stepFilter || ''}`} rowKey={row => text(row.event_id)} dataSource={[...rows].reverse()}
        pagination={{ pageSize: 8, showSizeChanger: false, hideOnSinglePage: true }} scroll={{ x: 640 }} locale={{ emptyText: '没有匹配的活动记录；不代表角色在线或工作已经发生。' }} columns={[
          { title: '时间 / 步骤', width: 165, render: (_, row) => <><RecordedTime value={row.created_at}/><br/><code>{text(row.step_id)}</code></> },
          { title: '角色 / 边界', width: 150, render: (_, row) => <>{roleLabel(row.actor)}<br/>{actions[text(row.action)] || text(row.action)}{row.work_item_id ? <><br/><code>{text(row.work_item_id)}</code></> : null}</> },
          { title: '实际记录', render: (_, row) => <><p>{text(row.summary) || '摘要未记录'}</p>{text(row.wait_reason) && <small>等待：{text(row.wait_reason)}</small>}</> },
          { title: '详情', width: 92, render: (_, row) => <Button size="small" onClick={() => open(text(row.step_id), text(row.participation_id) || undefined)}>查看{row.participation_id ? '参与' : '步骤'}</Button> },
        ]}/>
    </section>
    <Disclosure label={`计划依据与调整历史 · ${history.length} 版`}>
      <Fields value={{ assessment: plan.assessment, scope_refs: plan.scope_refs, effect_scope: plan.effect_scope,
        history, source: facts.source, legacy_event_ids: facts.legacy_event_ids, legacy_issues: facts.legacy_issues }} labels={{ assessment: '评估依据（引用前置评估，不补造开始时间）', scope_refs: '现有授权范围引用', effect_scope: '记录效果', legacy_event_ids: '历史未记录步骤关联的事件', legacy_issues: '旧工作段记录诊断（不追加新计划义务）' }}/>
    </Disclosure>
    <Disclosure label="既有门禁路由（不由步骤完成或角色记录代签）"><Fields value={workflow.route}/></Disclosure>
    <p className="muted execution-note">{text(facts.note)} 工作台只读；计划角色与实际参与分开，未知时间不估算，终态不冒充当前运行。</p>
  </section>;
});
