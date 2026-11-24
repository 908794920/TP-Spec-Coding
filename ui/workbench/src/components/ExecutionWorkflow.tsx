import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import { Alert, Button, Drawer, Pagination, Segmented, Select, Tag } from 'antd';
import { explainValue, record, records, stageLabel, stateLabel, text, timestampText, workflowNextResponsibility } from '../facts';
import type { FactRecord, WorkItems } from '../types';
import type { WorkflowHandle, WorkflowProps } from './WorkflowStrip';
import { Disclosure, Fields } from './Facts';
import { QuickWorkflowSummary } from './QuickWorkflowSummary';
import { actions, filterEvents, groupParticipations, newestEvents,
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
      <ol className="role-events" aria-label="活动记录">
        {rows.slice((current - 1) * 8, current * 8).map(event => <li key={text(event.event_id)}>
          <div className="role-event-heading"><RecordedTime value={event.created_at}/><strong>{responsibilityLabel(event.actor)} · {actions[text(event.action)] || explainValue('operation', event.action) || explainValue('event_type', event.event_type)}</strong></div>
          <p>{text(event.summary) || '摘要未记录'}</p>
          {!!text(event.wait_reason) && <p className="warning">等待：{text(event.wait_reason)}</p>}
          <Disclosure label="结果、证据与原始记录"><Fields value={{ result: event.result, findings: event.findings,
            decisions: event.decisions, evidence_refs: event.evidence_refs, expected_next_actor: event.expected_next_actor,
            event_id: event.event_id, event_type: event.event_type, step_id: event.step_id, evidence_path: event.evidence_path,
            participation_id: event.participation_id, actor_agent: event.actor_agent, work_item_id: event.work_item_id,
            plan_version: event.plan_version }} labels={{ result: '结果', findings: '发现', decisions: '决定记录',
              evidence_refs: '证据引用', expected_next_actor: '下一责任', actor_agent: '执行者标识' }}/></Disclosure>
        </li>)}
      </ol>
      {rows.length > 8 && <Pagination size="small" responsive current={current} pageSize={8} total={rows.length}
        showSizeChanger={false} onChange={setPage}/>}
    </>;
}

function ParticipationDetail({ selected, timeline, terminal, scope, setScope }: {
    selected: Participation; timeline: ExecutionEvent[]; terminal: boolean;
    scope: EventScope; setScope: (value: EventScope) => void;
}) {
    const rows = filterEvents(timeline, selected, scope);
    return <section className="role-participation-detail" aria-label={`${roleLabel(selected.role)}参与详情`}>
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

const routeStages: Record<string, string> = {
    requirement: '需求', discovery: '需求调研', product: '产品设计', architecture: '架构设计', architecture_review: '架构审查', planning: '实施规划',
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
    const routeStatus = text(workflow.route_read_status);
    const candidateStale = strings(route.reason_codes).includes('CHANGE_SET_STALE');
    const needsUser = namedOwner === 'human_owner' || (!namedOwner && route.requires_human === true &&
        (route.confirmation_required === true || ['await_security_decision', 'await_effect_approval'].includes(action)));
    const operation = text(alignment.operation_stage) || text(waiting.source_stage);
    const steps = records(execution.steps).filter(step => step.phase === operation);
    const operationName = steps.length === 1 ? text(steps[0].title) : (routeStages[operation] || operation);
    const operationDiffers = !!operation && operation !== text(current.phase);
    const reasons = blocked ? records(blockers).map(item => text(item.reason)).filter(Boolean) : [];
    const recordedReason = namedOwner || text(waiting.condition) ? reasons[0] : '';
    const routeReason = text(waiting.reason) || text(route.blocker) || recordedReason ||
        (needsUser ? '等待用户确认' : candidateStale ? '候选变更集已过期' : repair ? '需处理返修工作' : workPending ? '需处理关联 Work 的结果' : '');
    const stepReason = current.status === 'WAITING' ? text(current.wait_reason) : '';
    const stepOwner = text(current.expected_next_actor);
    const routeBlocked = !!(routeReason || text(waiting.condition) || prerequisite);
    const taskReasons = reasons.filter(reason => reason !== routeReason && reason !== stepReason);
    const nextFallback = workflowNextResponsibility(workflow, false);
    const recordedStage = record(workflow.current_step).stage ? workflow.current_step : records(workflow.steps).find(step => step.stage === task.phase);
    const plannedNext = text(record(execution.next_step).title);
    const displayedNext = !text(current.id) && !!plannedNext;
    const stepCaption = displayedNext ? '下一计划步骤' : text(current.id) ? '当前执行步骤' : '当前阶段';
    const stepTitle = text(current.title) || plannedNext || stageLabel(recordedStage) || routeStages[text(task.phase)] || explainValue('phase', task.phase) || '未记录';
    const condition = text(waiting.condition);
    const recordedCondition = condition.startsWith('具体恢复条件尚未结构化记录') ? '' : condition;
    const routeWork = records(context.work_items);
    const received = new Set(workPending ? routeWork.filter(item => text(record(item.receipt).event_id)).map(item => text(item.item_id)) : []);
    const waitWork = [...new Set([...strings(current.waiting_work_items), ...routeWork.map(item => text(item.item_id))])]
        .filter(id => !received.has(id) && workItems?.items?.some(item => item.item_id === id));
    const routeOwner = needsUser ? 'human_owner' : namedOwner ||
        ((prerequisite || repair || workPending) ? text(alignment.responsible_role) || text(route.role_id) : '');

    if (!routeBlocked && !blocked && current.status !== 'WAITING') {
        if (!showNext) return null;
        return <section className="task-blocker-banner is-clear" aria-label="当前进展与下一步">
          <div className="blocker-banner-grid">
            <div className="blocker-cell"><span>{stepCaption}</span><strong>{stepTitle}</strong></div>
            <div className="blocker-cell"><span>阻塞状态</span><strong role={routeStatus ? 'status' : undefined} className={routeStatus ? undefined : 'tone-good'}>{routeStatus || '无结构化阻塞'}</strong></div>
            <div className="blocker-cell"><span>建议动作</span><strong>{routeStatus ? '待确认' : stageLabel(workflow.next_step) || '按步骤推进'}</strong></div>
            <div className="blocker-cell"><span>下一责任人</span><strong>{routeStatus ? '待确认' : responsibilityLabel(nextFallback)}</strong></div>
          </div>
        </section>;
    }

    const primaryReason = routeReason || taskReasons[0] || stepReason || (operationName ? `需先处理${operationName}` : '等待解除前置条件');
    const primaryOwner = routeOwner || stepOwner;
    return <section className={`task-blocker-banner${blocked ? ' is-blocked' : ' is-waiting'}`} aria-label={blocked ? '当前进展与阻塞' : '当前进展与等待'}>
      <div className="blocker-banner-head">
        <strong>{blocked ? '当前进展与阻塞' : '当前进展与等待'}</strong>
        {needsUser && <Tag color="warning">需要你处理</Tag>}
        {operationName && (operationDiffers || prerequisite) && <span className="muted">前置环节：{operationName}</span>}
      </div>
      <div className="blocker-banner-grid">
        <div className="blocker-cell"><span>{stepCaption}</span><strong>{stepTitle}</strong></div>
        <div className="blocker-cell is-highlight"><span>阻塞 / 等待原因</span><strong>{primaryReason}</strong></div>
        <div className="blocker-cell"><span>解除条件</span><strong>{recordedCondition || '等待条件记录或确认'}</strong></div>
        <div className="blocker-cell"><span>下一责任人</span><strong>{responsibilityLabel(primaryOwner)}</strong></div>
      </div>
      {onWorkItem && !!waitWork.length && <div className="step-work-links"><span>关联待处理工作：</span>{waitWork.map(id =>
        <Button key={id} size="small" onClick={() => onWorkItem(id)}>{text(workItems?.items.find(item => item.item_id === id)?.title) || id}</Button>)}</div>}
    </section>;
}

const stepToneClass = (status: string, current: boolean): string => {
    if (current) return 'is-current';
    if (status === 'COMPLETED') return 'is-completed';
    if (status === 'WAITING' || status === 'BLOCKED') return 'is-waiting';
    return 'is-planned';
};

export const ExecutionWorkflow = forwardRef<WorkflowHandle, WorkflowProps>(({ workflow, task, blockers, lifecycleActivity, workItems, onDocuments, onWorkItem }, ref) => {
    const facts = record(workflow.execution), plan = record(facts.plan), assessment = record(plan.assessment);
    const steps = records(facts.steps) as ExecutionStep[], participants = records(facts.participations) as Participation[], timeline = newestEvents(facts.timeline);
    const workById = new Map(records(workItems?.items).map(item => [text(item.item_id), item]));
    const retired = workflow.retired === true;
    const terminal = facts.terminal === true || retired || task.state === 'COMPLETED' || task.state === 'CANCELLED';
    const current = terminal ? {} : record(facts.current_step);
    const currentId = text(current.id);
    const noPlan = !facts.status || facts.status === 'NOT_RECORDED';
    const issues = strings(facts.issues);
    const quick = workflow.workflow_mode === 'quick';
    const stepperRef = useRef<HTMLDivElement>(null);
    const phases = records(lifecycleActivity);
    const [view, setView] = useState<'lifecycle' | 'plan'>('lifecycle');
    const [phaseId, setPhaseId] = useState('');
    const activePhase = phases.find(phase => phase.phase === phaseId) ??
        phases.find(phase => phase.phase === task.phase) ?? phases.at(-1);
    const phaseName = (phase: unknown) => routeStages[text(phase)] || explainValue('phase', phase);

    const fallbackStages = useMemo(() => {
        if (!noPlan) return [];
        const recStage = text(record(workflow.current_step).stage) || text(task.phase);
        const nextStage = text(record(workflow.next_step).stage);
        return records(workflow.steps).map((item, idx) => {
            const st = text(item.stage);
            const isCurr = st === recStage;
            const isNext = st === nextStage;
            return {
                id: st || `stage-${idx}`,
                index: idx + 1,
                title: stageLabel(item) || routeStages[st] || st,
                status: text(item.status) || (isCurr ? 'ACTIVE' : isNext ? 'WAITING' : 'PLANNED'),
                isCurrent: isCurr || (!recStage && isNext),
                roles: text(item.role) ? [text(item.role)] : [],
                summary: text(item.summary) || (isNext ? '下一步建议' : ''),
            };
        });
    }, [noPlan, workflow.steps, workflow.current_step, workflow.next_step, task.phase]);

    const defaultStepId = currentId || text(steps.find(s => s.status !== 'COMPLETED')?.id) || text(steps[0]?.id) || fallbackStages.find(s => s.isCurrent)?.id || fallbackStages[0]?.id || '';
    const [selectedStepId, setSelectedStepId] = useState(defaultStepId);
    const [drawerRole, setDrawerRole] = useState<{ role: string; participation?: Participation; stepTitle: string;
        activity?: { rows: ExecutionEvent[]; total: number } } | null>(null);
    const [scope, setScope] = useState<EventScope>('participation');

    useEffect(() => {
        if (!steps.length && !fallbackStages.length) return;
        const valid = steps.some(s => text(s.id) === selectedStepId) || fallbackStages.some(s => s.id === selectedStepId);
        if (!valid) setSelectedStepId(defaultStepId);
    }, [steps, fallbackStages, selectedStepId, defaultStepId]);

    useImperativeHandle(ref, () => ({
        locateCurrent: () => {
            setView(steps.length || fallbackStages.length ? 'plan' : 'lifecycle');
            setPhaseId('');
            setSelectedStepId(defaultStepId);
            stepperRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        },
    }));

    const selectedStep = steps.find(s => text(s.id) === selectedStepId);
    const selectedStepTitle = text(selectedStep?.title) || fallbackStages.find(s => s.id === selectedStepId)?.title || '当前步骤';
    const stepParticipants = selectedStep ? participants.filter(p => p.step_id === selectedStepId) : [];
    const stepRoleIds = selectedStep
        ? stepRoles(selectedStep, stepParticipants)
        : (fallbackStages.find(s => s.id === selectedStepId)?.roles ?? []);
    const stepEvents = selectedStep ? timeline.filter(e => e.step_id === selectedStepId) : [];
    const recordingRoles = [...new Set(stepEvents.map(event => text(event.actor)))].filter(role => role && !stepRoleIds.includes(role));
    const stepDependencies = selectedStep ? strings(selectedStep.depends_on) : [];
    const hasPlanView = !!(steps.length || fallbackStages.length);
    const showLifecycle = !!activePhase && (view === 'lifecycle' || !hasPlanView);
    const planLabel = noPlan ? '流程状态' : '执行计划';

    return <section className="workflow-strip execution-workflow" aria-label="任务流程与角色看板">
      {retired && <Alert type="info" showIcon title="已退休 · 历史只读" description={`最后正式工作流状态：${stateLabel('task', task.state)}。`}/>}

      <CurrentBlockers workflow={workflow} task={task} blockers={blockers} workItems={workItems} onWorkItem={onWorkItem} showNext/>

      {(issues.length > 0 || facts.status === 'INVALID') && <Alert type="warning" showIcon title="部分执行事实无法可靠读取" description={issues.join('；') || '执行计划记录异常，当前步骤待核实。'}/>}
      {!!text(workflow.error) && <Alert type="warning" showIcon title="流程路由未解析" description={text(workflow.error)}/>}

      <div className="execution-stepper-wrap" ref={stepperRef}>
        <div className="section-heading">
          <h3>{showLifecycle || !hasPlanView ? '生命周期活动' : planLabel}</h3>
          {activePhase && hasPlanView && <Segmented aria-label="任务进度视图" size="small" value={showLifecycle ? 'lifecycle' : 'plan'}
            options={[{ label: '生命周期活动', value: 'lifecycle' }, { label: planLabel, value: 'plan' }]}
            onChange={setView}/>}
        </div>
        {showLifecycle ? <div className="execution-stepper" aria-label="有记录的生命周期阶段">
          {phases.map(phase => <button key={text(phase.phase)} type="button" aria-pressed={phase === activePhase}
            className={`stepper-node${phase === activePhase ? ' is-selected' : ''}`} onClick={() => setPhaseId(text(phase.phase))}>
            <div className="stepper-node-head"><strong className="stepper-title">{phaseName(phase.phase)}</strong></div>
            <div className="stepper-node-foot"><span>有活动记录</span><span>{records(phase.roles).length} 角色</span></div>
          </button>)}
        </div> : hasPlanView ? <>
        {!noPlan && <p className="muted">已完成 {steps.filter(s => s.status === 'COMPLETED').length} / 共 {steps.length} 步</p>}
        <div className="execution-stepper" role="tablist" aria-label={planLabel}>
          {(noPlan ? fallbackStages : steps.map((step, index) => {
              const id = text(step.id);
              const own = participants.filter(p => p.step_id === id);
              const roles = new Set([...stepRoles(step, own), ...timeline.filter(event => event.step_id === id)
                  .map(event => text(event.actor)).filter(Boolean)]);
              return {
                  id,
                  index: index + 1,
                  title: text(step.title) || id,
                  status: text(step.status) || 'PLANNED',
                  isCurrent: currentId === id,
                  roles: [...roles],
                  summary: text(step.scope),
              };
          })).map((item, idx, arr) => {
              const selected = item.id === selectedStepId;
              const statusText = item.isCurrent ? `${statusNames[item.status] || item.status} · 当前`
                  : item.status === 'PLANNED' ? '未开始' : statusNames[item.status] || item.status;
              return <div className="stepper-item-wrap" key={item.id}>
                <button type="button" role="tab" aria-selected={selected}
                  className={`stepper-node ${stepToneClass(item.status, item.isCurrent)}${selected ? ' is-selected' : ''}`}
                  onClick={() => setSelectedStepId(item.id)}>
                  <div className="stepper-node-head">
                    <span className="stepper-index">{item.index}</span>
                    <strong className="stepper-title">{item.title}</strong>
                    <span className="stepper-role-count">{item.roles.length} 角色</span>
                  </div>
                  <div className="stepper-node-foot">
                    <span className="stepper-status">{statusText}</span>
                    {selected && <span className="stepper-viewing">查看中</span>}
                  </div>
                </button>
                {idx < arr.length - 1 && <span className="stepper-arrow" aria-hidden="true">→</span>}
              </div>;
          })}
        </div></> : <p className="muted">暂无可展示的阶段活动。</p>}
      </div>

      {showLifecycle ? <div className="step-roles-section">
        <div className="section-heading"><h4>{phaseName(activePhase.phase)} · 角色活动</h4></div>
        <div className="role-cards-grid">
          {records(activePhase.roles).map(activity => {
              const role = text(activity.role), rows = newestEvents(activity.events);
              const recent = rows[0], total = Number(activity.event_count);
              return <button key={role} type="button" className="role-work-card"
                onClick={() => setDrawerRole({ role, stepTitle: phaseName(activePhase.phase), activity: { rows, total } })}>
                <div className="role-card-head"><strong>{role ? responsibilityLabel(role) : '角色未记录'}</strong></div>
                <p className="role-card-summary">{text(recent?.summary) || '摘要未记录'}</p>
                <div className="role-card-foot"><span>{total} 条活动记录</span><RecordedTime value={recent?.created_at}/></div>
              </button>;
          })}
        </div>
      </div> : hasPlanView && <div className="step-roles-section">
        <div className="section-heading">
          <h4>{selectedStepTitle} · 角色工作与记录</h4>
          {selectedStep && <span className="muted">{text(selectedStep.scope) || '点击角色卡片查看活动时间线与证据'}</span>}
        </div>
        {stepRoleIds.length > 0 || recordingRoles.length > 0 ? <div className="role-cards-grid">
          {[...stepRoleIds, ...recordingRoles].map(role => {
              const roleEvents = stepEvents.filter(event => text(event.actor) === role);
              const roleParts = stepParticipants.filter(p => text(p.role) === role);
              const grouped = groupParticipations(roleParts);
              const primary = grouped.visible[0];
              const lastEvent = primary ? newestEvents(primary.history)[0] : roleEvents[0];
              const workId = primary ? text(primary.work_item_id) : '';
              const work = workId ? workById.get(workId) : undefined;
              const statusLabel = primary ? participationLabel(primary, terminal) : roleEvents.length ? '有本步记录'
                  : noPlan ? '流程责任角色' : '计划参与 · 尚无记录';
              const activityText = primary
                  ? (text(primary.wait_reason) ? `等待：${text(primary.wait_reason)}` : text(primary.result) || text(lastEvent?.summary) || text(primary.scope) || '已登记范围')
                  : text(lastEvent?.summary) || fallbackStages.find(s => s.id === selectedStepId)?.summary || '尚无参与记录';
              const evCount = primary ? records(primary.evidence_refs).length + strings(primary.evidence_refs).length : 0;
              const timeVal = lastEvent?.created_at ?? (primary?.ended_at || primary?.started_at);
              const isWaiting = primary && (primary.status === 'WAITING' || !!text(primary.wait_reason));
              const isDone = primary && primary.status === 'COMPLETED';
              return <button type="button" key={role}
                className={`role-work-card${isWaiting ? ' is-waiting' : isDone ? ' is-done' : ''}${drawerRole?.role === role ? ' is-selected' : ''}`}
                onClick={() => { setScope('participation'); setDrawerRole({ role, participation: primary, stepTitle: selectedStepTitle,
                    activity: !primary && roleEvents.length ? { rows: roleEvents, total: roleEvents.length } : undefined }); }}>
                <div className="role-card-head">
                  <strong>{responsibilityLabel(role)}</strong>
                  <Tag color={isWaiting ? 'warning' : isDone ? 'success' : 'default'}>{statusLabel}</Tag>
                </div>
                <div className="role-card-body">
                  <span className="muted">在「{selectedStepTitle}」的工作</span>
                  <p className="role-card-summary">{activityText}</p>
                </div>
                <div className="role-card-foot">
                  <span>{work ? `Work: ${text(work.title) || workId}` : evCount > 0 ? `${evCount} 条证据引用` : '点击查看详情'}</span>
                  <span className="muted">{timeVal ? timestampText(timeVal).slice(5, 16) : '—'}</span>
                </div>
              </button>;
          })}
        </div> : <p className="muted">该步骤暂无已登记的参与角色。</p>}

        {selectedStep && (stepDependencies.length > 0 || stepEvents.length > 0) && <Disclosure label={`本步目标、前置依赖与全部事件 (${stepEvents.length} 条)`}>
          <dl className="step-facts">
            <div><dt>本步目标</dt><dd>{text(selectedStep.scope) || '未记录'}</dd></div>
            <div><dt>前置步骤</dt><dd>{stepDependencies.length ? stepDependencies.map(id => text(steps.find(s => s.id === id)?.title) || id).join('、') : '无'}</dd></div>
          </dl>
          <EventList rows={stepEvents}/>
        </Disclosure>}
      </div>}

      {/* 3. Quick Summary if quick workflow */}
      {quick && <QuickWorkflowSummary workflow={workflow} terminal={terminal} onDocuments={onDocuments}/>}

      <Drawer open={!!drawerRole} size={540} onClose={() => setDrawerRole(null)} destroyOnHidden
        title={drawerRole ? `${drawerRole.stepTitle} · ${drawerRole.role ? responsibilityLabel(drawerRole.role) : '角色未记录'}` : ''}>
        {drawerRole?.participation ? <ParticipationDetail selected={drawerRole.participation} timeline={timeline}
          terminal={terminal} scope={scope} setScope={setScope}/>
          : drawerRole?.activity ? <>
              {drawerRole.activity.total > drawerRole.activity.rows.length && <p className="muted">显示最近 {drawerRole.activity.rows.length} 条 / 共 {drawerRole.activity.total} 条</p>}
              <EventList key={`${drawerRole.stepTitle}:${drawerRole.role}`} rows={drawerRole.activity.rows}/>
            </>
          : <div className="empty-state"><p>该角色在「{drawerRole?.stepTitle}」步骤尚无已登记的活动或证据记录。</p>
            {onDocuments && <Button size="small" onClick={() => { setDrawerRole(null); onDocuments(); }}>查看任务资料与 Work</Button>}
          </div>}
      </Drawer>
    </section>;
});
