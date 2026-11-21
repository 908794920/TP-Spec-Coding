import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { Alert, Button, Pagination, Select, Tag, Typography } from 'antd';
import { record, records, stageLabel, stateLabel, text, timestampText, workflowNextResponsibility } from '../facts';
import type { FactRecord, WorkItems } from '../types';
import type { WorkflowHandle, WorkflowProps } from './WorkflowStrip';
import { Disclosure, Fields } from './Facts';
import { QuickWorkflowSummary } from './QuickWorkflowSummary';
import { actions, currentDescription, filterEvents, groupParticipations, newestEvents,
    participationLabel, roleLabel, statusNames, stepRoles, strings,
    type EventScope, type ExecutionEvent, type ExecutionStep, type Participation } from './executionView';

function RecordedTime({ value }: { value: unknown }) {
    return <span title={text(value)}>{value ? timestampText(value) : '未记录'}</span>;
}
function EventList({ rows }: { rows: ExecutionEvent[] }) {
    const [page, setPage] = useState(1);
    const current = Math.min(page, Math.max(1, Math.ceil(rows.length / 8)));
    return <>
      {!rows.length && <p className="muted">没有匹配的已绑定事件。</p>}
      <ol className="role-events" aria-label="已绑定事件">
        {rows.slice((current - 1) * 8, current * 8).map(event => <li key={text(event.event_id)}>
          <div className="role-event-heading"><RecordedTime value={event.created_at}/><strong>{roleLabel(event.actor)} · {actions[text(event.action)] || text(event.action)}</strong></div>
          <p>{text(event.summary) || '摘要未记录'}</p>
          {!!text(event.wait_reason) && <p className="warning">等待：{text(event.wait_reason)}</p>}
          <Disclosure label="结果、证据与原始记录"><Fields value={{ result: event.result, findings: event.findings,
            decisions: event.decisions, evidence_refs: event.evidence_refs, expected_next_actor: event.expected_next_actor,
            event_id: event.event_id, event_type: event.event_type, step_id: event.step_id,
            participation_id: event.participation_id, actor_agent: event.actor_agent, work_item_id: event.work_item_id,
            plan_version: event.plan_version }} labels={{ result: '结果', findings: '发现', decisions: '决定记录',
              evidence_refs: '证据引用', expected_next_actor: '下一责任', actor_agent: '执行者标识' }}/></Disclosure>
        </li>)}
      </ol>
      {rows.length > 8 && <Pagination size="small" responsive current={current} pageSize={8} total={rows.length}
        showSizeChanger={false} onChange={setPage}/>}
    </>;
}
function ParticipationDetail({ selected, timeline, terminal, scope, setScope, onClose }: {
    selected: Participation; timeline: ExecutionEvent[]; terminal: boolean;
    scope: EventScope; setScope: (value: EventScope) => void; onClose: () => void;
}) {
    const rows = filterEvents(timeline, selected, scope);
    return <section className="role-participation-detail" aria-label={`${roleLabel(selected.role)}参与详情`}
      onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); onClose(); } }}>
      <div className="section-heading"><h5>{roleLabel(selected.role)} · {participationLabel(selected, terminal)}</h5><Button size="small" onClick={onClose}>关闭参与详情</Button></div>
      <dl className="participation-facts">
        <div><dt>本次范围</dt><dd>{text(selected.scope) || '未记录'}</dd></div>
        <div><dt>结果</dt><dd>{text(selected.result) || '尚无结果记录'}</dd></div>
        {!!text(selected.wait_reason) && <div><dt>等待原因</dt><dd>{text(selected.wait_reason)}</dd></div>}
        {!!text(selected.expected_next_actor) && <div><dt>交接 / 下一责任</dt><dd>{roleLabel(selected.expected_next_actor)}</dd></div>}
      </dl>
      <Disclosure label="发现、决定、证据与起止详情"><Fields value={{ findings: selected.findings, decisions: selected.decisions,
        evidence_refs: selected.evidence_refs, actor_agent: selected.agent, work_item_id: selected.work_item_id, started_at: selected.started_at, ended_at: selected.ended_at,
        duration_seconds: selected.duration_seconds, participation_id: selected.participation_id, plan_version: selected.plan_version }}
        labels={{ findings: '发现', decisions: '决定记录（不是授权）', evidence_refs: '证据引用', started_at: '开始记录',
          ended_at: '结束记录', duration_seconds: '起止跨度（秒，包含等待）', plan_version: '开始时计划版本' }}/></Disclosure>
      <div className="role-event-controls"><label>事件范围 <Select aria-label="事件范围" value={scope}
        options={[{ value: 'participation', label: '本次参与' }, { value: 'role', label: '本角色在本步骤的全部参与' }, { value: 'step', label: '本步骤全部事件' }]}
        onChange={setScope}/></label><span role="status">匹配 {rows.length} / {timeline.filter(row => row.step_id === selected.step_id).length} 条本步骤事件</span></div>
      <EventList key={scope} rows={rows}/>
    </section>;
}
function RoleGroup({ role, participants, timeline, terminal, current, workById, onWorkItem }: {
    role: string; participants: Participation[]; timeline: ExecutionEvent[]; terminal: boolean; current: boolean;
    workById: Map<string, FactRecord>; onWorkItem?: (id: string) => void;
}) {
    const [selectedId, setSelectedId] = useState('');
    const [scope, setScope] = useState<EventScope>('participation');
    const trigger = useRef<HTMLButtonElement | null>(null);
    const history = useRef<HTMLDetailsElement>(null);
    const selected = participants.find(p => p.participation_id === selectedId);
    useEffect(() => { if (selectedId && !selected) setSelectedId(''); }, [selectedId, selected]);
    const group = groupParticipations(participants);
    const older = current ? [] : group.history;
    const selectedInHistory = older.some(p => p.participation_id === selectedId);
    // 刷新后所选参与可能转入历史，保留原详情及筛选。
    useEffect(() => { if (selectedInHistory && history.current) history.current.open = true; }, [selectedInHistory, selectedId]);
    const close = () => { setSelectedId(''); requestAnimationFrame(() => trigger.current?.focus()); };
    function participant(p: Participation) {
        const last = newestEvents(p.history)[0];
        const workId = text(p.work_item_id), work = workById.get(workId);
        const startOnly = !last || last.action === 'start';
        const summary = startOnly ? '已登记范围' : text(last.summary);
        const result = text(p.result);
        const nextActor = text(p.expected_next_actor);
        const open = p.participation_id === selectedId;
        return <div className="role-participation" key={text(p.participation_id)}>
          <div className="role-participation-row">
            <button type="button" className="role-participation-button" aria-expanded={open}
              ref={element => { if (element && open) trigger.current = element; }}
              onClick={event => { trigger.current = event.currentTarget; setScope('participation'); setSelectedId(open ? '' : text(p.participation_id)); }}>
              <span className="role-participation-title"><strong>{roleLabel(role)}</strong><span className="disclosure-caret" aria-hidden="true">{open ? '▾' : '▸'}</span></span>
              <span className="muted">{participationLabel(p, terminal)}</span>
            </button>
            <div className="role-work">{work && onWorkItem
              ? <button type="button" className="knowledge-link" onClick={() => onWorkItem(workId)}>{text(work.title) || workId}</button>
              : text(work?.title) || text(p.scope) || '范围未记录'}</div>
            <div className="role-progress">
              <div>{summary || result || '暂无进展记录'}{result && summary && result !== summary && <> · {result}</>}</div>
              {!!text(p.wait_reason) && <div className="warning">{terminal ? '历史等待' : '等待'}：{text(p.wait_reason)}</div>}
              {nextActor && (p.status === 'HANDED_OFF' || !!text(p.wait_reason)) && <div className="muted">
                {p.status === 'HANDED_OFF' ? '交接给' : '等待责任方'}：{responsibilityLabel(nextActor)}
              </div>}
            </div>
            <span className="role-recorded-at muted"><RecordedTime value={last?.created_at ?? (p.ended_at || p.started_at)}/></span>
          </div>
          {open && selected && <ParticipationDetail key={selectedId} selected={selected} timeline={timeline}
            terminal={terminal} scope={scope} setScope={setScope} onClose={close}/>}
        </div>;
    }
    return <section className="step-role-group" aria-label={`${roleLabel(role)}的参与`}>
      {!participants.length ? !terminal && <p className="planned-role">计划参与 · {roleLabel(role)}</p> : <>
        {(current ? [...group.visible, ...group.history] : group.visible).map(participant)}
        {!!older.length && <details ref={history} className="role-history"><summary>该角色更早的参与 · {older.length} 次</summary>{older.map(participant)}</details>}
      </>}
    </section>;
}

function StepContent({ step, steps, participants, timeline, terminal, current, workById, onWorkItem }: {
    step: ExecutionStep; steps: ExecutionStep[]; participants: Participation[]; timeline: ExecutionEvent[];
    terminal: boolean; current: boolean; workById: Map<string, FactRecord>; onWorkItem?: (id: string) => void;
}) {
    const own = participants.filter(p => p.step_id === step.id);
    const events = timeline.filter(row => row.step_id === step.id);
    const dependencies = strings(step.depends_on);
    const remaining = strings(step.linked_work_items).filter(id => !own.some(p => p.work_item_id === id));
    return <div className="execution-step-body">
      {current && own.length > 0 && <h4>已登记参与</h4>}
      {stepRoles(step, own).map(role => <RoleGroup key={role} role={role} participants={own.filter(p => text(p.role) === role)}
        timeline={timeline} terminal={terminal} current={current} workById={workById} onWorkItem={onWorkItem}/>)}
      {!stepRoles(step, own).length && <p className="muted">未登记角色。</p>}
      {!!remaining.length && <div className="step-work-links"><span>关联工作</span>{remaining.map(id =>
        <Button key={id} size="small" onClick={() => onWorkItem?.(id)}>{text(workById.get(id)?.title) || id}</Button>)}</div>}
      <dl className="step-facts">
        <div><dt>本步目标</dt><dd>{text(step.scope) || '未记录'}</dd></div>
        <div><dt>前置步骤及参与角色</dt><dd>{dependencies.length ? dependencies.map(id => {
            const dependency = steps.find(s => s.id === id);
            const roles = Array.from(new Set(participants.filter(p => p.step_id === id).map(p => roleLabel(p.role))));
            return <p key={id}>{text(dependency?.title) || id}{roles.length > 0 && <> · {roles.join('、')}</>}</p>;
        }) : '无前置步骤'}</dd></div>
        {!current && !!text(step.wait_reason) && <div><dt>历史等待</dt><dd>{text(step.wait_reason)}</dd></div>}
      </dl>
      <Disclosure label={`本步骤全部事件 · ${events.length} 条`}><EventList rows={events}/></Disclosure>
      <Disclosure label="步骤来源与边界记录"><Fields value={step}/></Disclosure>
    </div>;
}

const routeStages: Record<string, string> = {
    requirement: '需求确认', architecture: '架构设计', architecture_review: '架构审查', planning: '规划',
    development: '开发', verification: '验证', review: '代码审查', delivery: '交付', complete: '结单',
};
export function responsibilityLabel(value: unknown): string {
    return value === 'human_owner' ? '用户' : text(value) ? roleLabel(value) : '未记录';
}

export function CurrentBlockers({ workflow, task, blockers, workItems, onWorkItem, showNext }: {
    workflow: FactRecord; task: FactRecord; blockers?: unknown; workItems?: WorkItems; onWorkItem?: (id: string) => void; showNext?: boolean;
}) {
    const execution = record(workflow.execution);
    if (execution.terminal === true || workflow.retired === true || task.state === 'COMPLETED' || task.state === 'CANCELLED')
        return null;
    const current = record(execution.current_step), route = record(workflow.route), context = record(route.context);
    const waiting = record(context.waiting ?? record(workflow.next_step).waiting), alignment = record(route.plan_route_alignment);
    const action = text(route.recommended_action);
    const blocked = task.state === 'BLOCKED';
    const prerequisite = alignment.alignment_status === 'PREREQUISITE_REPAIR';
    const repair = alignment.alignment_status === 'REWORK_FIX_REQUIRED';
    const workPending = action === 'workitem_resolve';
    const namedOwner = text(waiting.responsibility) || text(route.next_responsibility);
    const needsUser = namedOwner === 'human_owner' || (!namedOwner && route.requires_human === true &&
        (route.confirmation_required === true || ['await_security_decision', 'await_effect_approval'].includes(action)));
    const operation = text(alignment.operation_stage) || text(waiting.source_stage);
    const steps = records(execution.steps).filter(step => step.phase === operation);
    const operationName = steps.length === 1 ? text(steps[0].title) : (routeStages[operation] || operation);
    const operationDiffers = !!operation && operation !== text(current.phase);
    const reasons = blocked ? records(blockers).map(item => text(item.reason)).filter(Boolean) : [];
    const recordedReason = namedOwner || text(waiting.condition) ? reasons[0] : '';
    const routeReason = text(waiting.reason) || text(route.blocker) || recordedReason ||
        (needsUser ? '等待用户确认' : repair ? '需处理返修工作' : workPending ? '需处理关联 Work 的结果' : '');
    const stepReason = current.status === 'WAITING' ? text(current.wait_reason) : '';
    const stepOwner = text(current.expected_next_actor);
    const sameReason = !!routeReason && routeReason === stepReason;
    const routeBlocked = !!(routeReason || text(waiting.condition) || prerequisite);
    const taskReasons = reasons.filter(reason => reason !== routeReason && reason !== stepReason);
    if (!routeBlocked && !blocked && current.status !== 'WAITING')
        return showNext ? <p>下一责任人：<strong>{responsibilityLabel(workflowNextResponsibility(workflow, false))}</strong></p> : null;
    const condition = text(waiting.condition);
    const recordedCondition = condition.startsWith('具体恢复条件尚未结构化记录') ? '' : condition;

    const routeWork = records(context.work_items);
    const received = new Set(workPending ? routeWork.filter(item => text(record(item.receipt).event_id)).map(item => text(item.item_id)) : []);
    const waitWork = [...new Set([...strings(current.waiting_work_items), ...routeWork.map(item => text(item.item_id))])]
        .filter(id => !received.has(id) && workItems?.items?.some(item => item.item_id === id));
    const routeOwner = needsUser ? 'human_owner' : namedOwner ||
        ((prerequisite || repair || workPending) ? text(alignment.responsible_role) || text(route.role_id) : '');
    const stepTitle = text(current.title) || stageLabel(workflow.current_step);
    return <section className="task-blocker" aria-label={blocked ? '任务阻塞' : '当前卡点'}>
      <h4>{blocked ? '任务阻塞' : '当前卡点'}<span> · {stepTitle || '任务'}暂不能推进</span></h4>
      {routeBlocked && <div className="blocker-reason">
        {operationName && (operationDiffers || prerequisite) && <p>眼下需先处理<strong>{operationName}</strong></p>}
        <p><strong>{routeReason || (operationName ? '前置工作尚未完成' : '原因未记录')}</strong></p>
        <p className="blocker-owner">下一责任人：<strong>{responsibilityLabel(routeOwner)}</strong>{needsUser && <Tag color="warning">需要你处理</Tag>}</p>
        <p className="muted">解除条件：{recordedCondition || '未记录'}</p>
        {sameReason && stepOwner && stepOwner !== routeOwner && <p className="muted">步骤恢复责任方：{responsibilityLabel(stepOwner)}</p>}
      </div>}
      {taskReasons.map((reason, index) => <div className="blocker-reason" key={index}>
        <p><strong>{reason}</strong></p><p>下一责任人：未记录</p><p className="muted">解除条件：未记录</p>
      </div>)}
      {!sameReason && (current.status === 'WAITING' || (blocked && !routeBlocked && !taskReasons.length)) &&
        <div className="blocker-reason"><p><strong>{stepReason || '原因未记录'}</strong></p>
          <p className="blocker-owner">下一责任人：<strong>{responsibilityLabel(stepOwner)}</strong>{stepOwner === 'human_owner' && <Tag color="warning">需要你处理</Tag>}</p>
          <p className="muted">解除条件：未记录</p>
        </div>}
      {onWorkItem && !!waitWork.length && <div className="step-work-links">{waitWork.map(id =>
        <Button key={id} size="small" onClick={() => onWorkItem(id)}>{text(workItems?.items.find(item => item.item_id === id)?.title) || id}</Button>)}</div>}
    </section>;
}

export const ExecutionWorkflow = forwardRef<WorkflowHandle, WorkflowProps>(({ workflow, task, blockers, workItems, onConditions, onDocuments, onWorkItem }, ref) => {
    const facts = record(workflow.execution), plan = record(facts.plan), assessment = record(plan.assessment);
    const steps = records(facts.steps) as ExecutionStep[], participants = records(facts.participations) as Participation[], timeline = newestEvents(facts.timeline);
    const workById = new Map(records(workItems?.items).map(item => [text(item.item_id), item]));
    const retired = workflow.retired === true;
    const terminal = facts.terminal === true || retired || task.state === 'COMPLETED' || task.state === 'CANCELLED';
    const current = terminal ? {} : record(facts.current_step), next = terminal ? {} : record(facts.next_step);
    const currentId = text(current.id), heading = useRef<HTMLHeadingElement>(null), list = useRef<HTMLOListElement>(null);
    const [expanded, setExpanded] = useState<string[]>(currentId ? [currentId] : []);
    const issues = strings(facts.issues);
    const noPlan = !facts.status || facts.status === 'NOT_RECORDED';
    const quick = workflow.workflow_mode === 'quick';
    const video = workflow.domain === 'video';
    const recordedStage = record(workflow.current_step).stage ? workflow.current_step
        : records(workflow.steps).find(step => step.stage === task.phase);
    useEffect(() => { setExpanded(old => old.filter(id => steps.some(step => step.id === id))); }, [facts.steps]);
    function locate() {
        if (currentId) setExpanded(old => old.includes(currentId) ? old : [...old, currentId]);
        requestAnimationFrame(() => {
            const element = Array.from(list.current?.querySelectorAll<HTMLDetailsElement>('[data-step-id]') || []).find(el => el.dataset.stepId === currentId);
            const target = element?.querySelector('summary') || heading.current;
            target?.focus(); target?.scrollIntoView({ block: 'nearest' });
        });
    }
    useImperativeHandle(ref, () => ({ locateCurrent: locate }));
    const assessmentDetails = { risk_level: task.risk_level, flow_level: task.flow_level, effective_level: workflow.effective_level,
        registered_level: plan.effective_level, source_refs: assessment.source_refs, omissions: assessment.omissions };
    return <section className="workflow-strip execution-workflow" aria-label="任务评估与执行步骤">
      {retired && <Alert type="info" showIcon title="已退休 · 历史只读"
        description={`最后正式工作流状态：${stateLabel('task', task.state)}。`}/>}
      <div className="execution-summary">
        <p><span>{noPlan ? '当前记录阶段' : '当前步骤'}</span><strong>{retired ? '已退休，历史只读' : terminal ? '任务已结束'
          : noPlan ? stageLabel(recordedStage) || text(task.phase) || '尚未记录' : currentDescription(facts, terminal)}</strong>
          {!!next.id && <small>计划下一步：{text(next.title)}</small>}
          {noPlan && !terminal && stageLabel(workflow.next_step) && <small>Runtime 建议：{stageLabel(workflow.next_step)}</small>}</p>
        <div className="step-list-actions">
          <Button size="small" onClick={onConditions}>{currentId ? '查看本步条件' : '阻塞详情'}</Button>
        </div>
      </div>
      <CurrentBlockers workflow={workflow} task={task} blockers={blockers} workItems={workItems} onWorkItem={onWorkItem} showNext/>
      {(issues.length > 0 || facts.status === 'INVALID') && <Alert type="warning" showIcon title="部分执行事实无法可靠读取" description={issues.join('；') || '执行计划记录异常，当前步骤待核实。'}/>}
      {!!text(workflow.error) && <Alert type="warning" showIcon title="流程路由未解析" description={text(workflow.error)}/>}
      {noPlan ? <div className="execution-empty"><strong>执行计划尚未登记</strong></div> : <>
        <div className="section-heading execution-list-heading"><h3 ref={heading} tabIndex={-1}>执行步骤</h3><div className="step-list-actions">
          <span className="muted">已记录完成 {steps.filter(step => step.status === 'COMPLETED').length} / 共 {steps.length} 步</span>
          {currentId && <Button size="small" onClick={locate}>定位当前步骤</Button>}
        </div></div>
        <ol className="execution-step-list" ref={list} aria-label="正式记录的步骤顺序">
          {steps.map((step, index) => {
              const id = text(step.id), own = participants.filter(p => p.step_id === id);
              const currentStep = currentId === id, open = expanded.includes(id);
              const recent = timeline.find(row => row.step_id === id && !row.participation_id);
              const planned = !terminal && step.status === 'PLANNED';
              return <li key={id}><details className={`execution-step${currentStep ? ' current-step' : ''}`}
                data-step-id={id} data-state={text(step.status)} open={open}
                onToggle={event => { const toggled = event.currentTarget.open; setExpanded(old => toggled ? old.includes(id) ? old : [...old, id] : old.filter(value => value !== id)); }}>
                <summary aria-current={currentStep ? 'step' : undefined}><span className="step-number">{index + 1}</span><span className="step-summary-content">
                  <span className="execution-step-title"><strong>{text(step.title) || id}</strong><Tag>{terminal && step.status !== 'COMPLETED' ? '历史 · ' : ''}{planned ? '待开始' : statusNames[text(step.status)] || text(step.status) || '状态未记录'}</Tag>{currentStep && <Tag color="blue">当前</Tag>}</span>
                  {own.length > 0 && !open && <span className="muted">已参与：{Array.from(new Set(own.map(p => roleLabel(p.role)))).join('、')}</span>}
                  {planned && !open && !!step.roles?.length && <span className="muted">计划参与：{strings(step.roles).map(roleLabel).join('、')}</span>}
                  {!open && !!text(recent?.result || recent?.summary) && <span className="step-recent">{text(recent?.result || recent?.summary)}</span>}
                </span><span className="disclosure-caret" aria-hidden="true">{open ? '▾' : '▸'}</span></summary>
                <StepContent step={step} steps={steps} participants={participants} timeline={timeline}
                  terminal={terminal} current={currentStep} workById={workById} onWorkItem={onWorkItem}/>
              </details></li>;
          })}
        </ol>
      </>}
      {quick ? <QuickWorkflowSummary workflow={workflow} terminal={terminal} onDocuments={onDocuments}/>
        : <><div className="task-assessment"><div><span className="eyebrow">{video ? '任务领域' : '任务评估'}</span><strong className="assessment-level">{video ? '视频制作' : text(workflow.effective_level) || '等级未解析'}</strong></div>
          {!noPlan && <div className="assessment-reason">{text(assessment.summary) ? <><span className="muted">计划登记时的评估依据</span><Typography.Paragraph ellipsis={{ rows: 2, expandable: 'collapsible', symbol: expanded => expanded ? '收起' : '展开依据' }}>{text(assessment.summary)}</Typography.Paragraph></>
            : <><p>未登记结构化评估依据</p><Button size="small" type="link" onClick={onDocuments}>查看当前任务文档</Button></>}
          </div>}</div>
          {!video && <Disclosure label="等级与评估来源"><Fields value={assessmentDetails}
            labels={{ registered_level: '计划登记等级', source_refs: '评估来源', omissions: '省略步骤的评估依据' }}/></Disclosure>}
          {!!text(plan.effective_level) && !!text(workflow.effective_level) && plan.effective_level !== workflow.effective_level && <Alert type="warning" showIcon title="当前等级与计划登记等级不同，需复核计划义务" description={`计划登记 ${text(plan.effective_level)}；当前 ${text(workflow.effective_level)}。`}/>}
        </>}
      <Disclosure label="计划调整与协调记录"><Fields value={{ coordinator: facts.coordinator, coordinator_source: facts.coordinator_source,
        current_roles: facts.current_roles, history: facts.plan_history, scope_refs: plan.scope_refs, source: facts.source,
        last_recorded_at: facts.last_recorded_at, legacy_event_ids: facts.legacy_event_ids, legacy_issues: facts.legacy_issues,
        current_step_source: workflow.current_step_source, next_step_source: workflow.next_step_source, route: workflow.route }}/></Disclosure>
    </section>;
});
