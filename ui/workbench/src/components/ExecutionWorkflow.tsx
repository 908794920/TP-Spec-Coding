import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { Alert, Button, Pagination, Select, Tag, Typography } from 'antd';
import { record, records, text, timestampText } from '../facts';
import type { WorkflowHandle, WorkflowProps } from './WorkflowStrip';
import { Disclosure, Fields } from './Facts';
import { actions, currentDescription, filterEvents, groupParticipations, latestHandoff, newestEvents,
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
        <div><dt>执行者</dt><dd>{text(selected.agent) || '未记录'} · {text(selected.work_item_id) || '父 Task'}</dd></div>
        <div><dt>本次范围</dt><dd>{text(selected.scope) || '未记录'}</dd></div>
        <div><dt>结果</dt><dd>{text(selected.result) || '尚无结果记录'}</dd></div>
        {!!text(selected.wait_reason) && <div><dt>等待原因</dt><dd>{text(selected.wait_reason)}</dd></div>}
        {!!text(selected.expected_next_actor) && <div><dt>交接 / 下一责任</dt><dd>{roleLabel(selected.expected_next_actor)}</dd></div>}
      </dl>
      <Disclosure label="发现、决定、证据与起止详情"><Fields value={{ findings: selected.findings, decisions: selected.decisions,
        evidence_refs: selected.evidence_refs, started_at: selected.started_at, ended_at: selected.ended_at,
        duration_seconds: selected.duration_seconds, participation_id: selected.participation_id, plan_version: selected.plan_version }}
        labels={{ findings: '发现', decisions: '决定记录（不是授权）', evidence_refs: '证据引用', started_at: '开始记录',
          ended_at: '结束记录', duration_seconds: '起止跨度（秒，包含等待）', plan_version: '开始时计划版本' }}/></Disclosure>
      <div className="role-event-controls"><label>事件范围 <Select aria-label="事件范围" value={scope}
        options={[{ value: 'participation', label: '本次参与' }, { value: 'role', label: '本角色在本步骤的全部参与' }, { value: 'step', label: '本步骤全部事件' }]}
        onChange={setScope}/></label><span role="status">匹配 {rows.length} / {timeline.filter(row => row.step_id === selected.step_id).length} 条本步骤事件</span></div>
      <EventList key={scope} rows={rows}/>
    </section>;
}
function RoleGroup({ role, participants, timeline, terminal }: {
    role: string; participants: Participation[]; timeline: ExecutionEvent[]; terminal: boolean;
}) {
    const [selectedId, setSelectedId] = useState('');
    const [scope, setScope] = useState<EventScope>('participation');
    const trigger = useRef<HTMLButtonElement | null>(null);
    const history = useRef<HTMLDetailsElement>(null);
    const selected = participants.find(p => p.participation_id === selectedId);
    useEffect(() => { if (selectedId && !selected) setSelectedId(''); }, [selectedId, selected]);
    const group = groupParticipations(participants);
    const selectedInHistory = group.history.some(p => p.participation_id === selectedId);
    // 刷新后参与可能从最近记录移到历史；仍保持所选记录可见及其筛选条件。
    useEffect(() => { if (selectedInHistory && history.current) history.current.open = true; }, [selectedInHistory, selectedId]);
    const close = () => { setSelectedId(''); requestAnimationFrame(() => trigger.current?.focus()); };
    function participant(p: Participation) {
        const last = newestEvents(p.history)[0];
        return <div className="role-participation" key={text(p.participation_id)}>
          <button type="button" className="role-participation-button" aria-expanded={p.participation_id === selectedId}
            ref={element => { if (element && p.participation_id === selectedId) trigger.current = element; }}
            onClick={event => { trigger.current = event.currentTarget; setScope('participation'); setSelectedId(p.participation_id === selectedId ? '' : text(p.participation_id)); }}>
            <span className="role-participation-title"><strong>{roleLabel(role)}</strong><span>{participationLabel(p, terminal)}</span><span className="disclosure-caret" aria-hidden="true">{p.participation_id === selectedId ? '▾' : '▸'}</span></span>
            <span className="muted">{text(p.agent) || '执行者未记录'} · {text(p.work_item_id) || '父 Task'} · 开始 <RecordedTime value={p.started_at}/></span>
            <span className="participation-latest">{text(last?.summary) || text(p.result) || '暂无进展摘要'}</span>
          </button>
          {p.participation_id === selectedId && selected && <ParticipationDetail key={selectedId} selected={selected} timeline={timeline} terminal={terminal} scope={scope} setScope={setScope} onClose={close}/>}
        </div>;
    }
    return <section className="step-role-group" aria-label={`${roleLabel(role)}的参与`}>
      {!participants.length ? <p className="planned-role">{roleLabel(role)} · 计划角色，尚无实际参与记录</p> : <>
        {group.visible.map(participant)}
        {!!group.history.length && <details ref={history} className="role-history"><summary>该角色更早的参与 · {group.history.length} 次</summary>{group.history.map(participant)}</details>}
      </>}
    </section>;
}
function StepContent({ step, steps, participants, timeline, terminal, onWorkItem }: {
    step: ExecutionStep; steps: ExecutionStep[]; participants: Participation[]; timeline: ExecutionEvent[];
    terminal: boolean; onWorkItem?: (id: string) => void;
}) {
    const own = participants.filter(p => p.step_id === step.id);
    const handoff = latestHandoff(timeline, text(step.id));
    const dependencies = strings(step.depends_on);
    return <div className="execution-step-body">
      <dl className="step-facts">
        <div><dt>本步目标</dt><dd>{text(step.scope) || '未记录'}</dd></div>
        <div><dt>前置步骤及参与角色</dt><dd>{dependencies.length ? dependencies.map(id => {
            const dependency = steps.find(s => s.id === id);
            const roles = Array.from(new Set(participants.filter(p => p.step_id === id).map(p => roleLabel(p.role))));
            return <p key={id}>{text(dependency?.title) || id} · {roles.length ? roles.join('、') : '暂无实际参与角色'}</p>;
        }) : '无前置步骤'}</dd></div>
        <div><dt>最近明确交接</dt><dd>{handoff ? <>{roleLabel(handoff.actor)} → {roleLabel(handoff.expected_next_actor)} · <RecordedTime value={handoff.created_at}/><p>{text(handoff.summary)}</p></> : '未记录交接'}</dd></div>
        {!!text(step.wait_reason) && <div><dt>{terminal ? '历史等待' : '步骤等待'}</dt><dd>{text(step.wait_reason)}<p>下一责任：{text(step.expected_next_actor) ? roleLabel(step.expected_next_actor) : '未记录'} · <RecordedTime value={newestEvents(timeline).find(row => row.step_id === step.id && !row.participation_id)?.created_at}/></p></dd></div>}
      </dl>
      <div className="section-heading"><h4>角色进展与事件</h4><span className="muted">点击参与记录展开事件</span></div>
      {stepRoles(step, own).map(role => <RoleGroup key={role} role={role} participants={own.filter(p => text(p.role) === role)} timeline={timeline} terminal={terminal}/>)}
      {!stepRoles(step, own).length && <p className="muted">未登记角色。</p>}
      <Disclosure label={`本步骤全部事件 · ${timeline.filter(row => row.step_id === step.id).length} 条`}>
        <EventList rows={newestEvents(timeline).filter(row => row.step_id === step.id)}/>
      </Disclosure>
      {!!strings(step.linked_work_items).length && <div className="step-work-links"><span>关联工作</span>{strings(step.linked_work_items).map(id =>
        <Button key={id} size="small" onClick={() => onWorkItem?.(id)}>{strings(step.fix_work_items).includes(id) ? 'Fix' : 'Work'}：{id}</Button>)}</div>}
      <Disclosure label="步骤来源与边界记录"><Fields value={step}/></Disclosure>
    </div>;
}
export const ExecutionWorkflow = forwardRef<WorkflowHandle, WorkflowProps>(({ workflow, task, blockers, onDocuments, onWorkItem }, ref) => {
    const facts = record(workflow.execution), plan = record(facts.plan), assessment = record(plan.assessment);
    const steps = records(facts.steps) as ExecutionStep[], participants = records(facts.participations) as Participation[], timeline = newestEvents(facts.timeline);
    const terminal = facts.terminal === true || workflow.retired === true || task.state === 'COMPLETED' || task.state === 'CANCELLED';
    const current = terminal ? {} : record(facts.current_step), next = terminal ? {} : record(facts.next_step);
    const currentId = text(current.id), heading = useRef<HTMLHeadingElement>(null), list = useRef<HTMLOListElement>(null);
    const [expanded, setExpanded] = useState<string[]>(currentId ? [currentId] : []);
    const currentRoles = terminal || !currentId ? [] : strings(facts.current_roles);
    const issues = strings(facts.issues);
    const noPlan = !facts.status || facts.status === 'NOT_RECORDED';
    const latestBlockers = task.state === 'BLOCKED' ? records(blockers) : [];
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
    return <section className="workflow-strip execution-workflow" aria-label="任务评估与执行步骤">
      <div className="task-assessment"><div><span className="eyebrow">任务评估</span><strong className="assessment-level">{text(workflow.effective_level) || '等级未解析'}</strong></div>
        <div className="assessment-reason">{text(assessment.summary) ? <><span className="muted">计划登记时的评估依据</span><Typography.Paragraph ellipsis={{ rows: 2, expandable: 'collapsible', symbol: expanded => expanded ? '收起' : '展开依据' }}>{text(assessment.summary)}</Typography.Paragraph></> : <><p>未登记结构化评估依据</p><Button size="small" type="link" onClick={onDocuments}>查看当前任务文档</Button></>}
          {!text(workflow.effective_level) && <p>已记录风险等级：{text(task.risk_level) || '未记录'} · 流程等级：{text(task.flow_level) || '未记录'}</p>}
        </div></div>
      <Disclosure label="等级含义与评估来源"><p>L0–L3 表达风险与流程义务，不等同于独立技术难度或工作量评分。</p><Fields value={{ risk_level: task.risk_level, flow_level: task.flow_level,
        effective_level: workflow.effective_level, registered_level: plan.effective_level, source_refs: assessment.source_refs,
        omissions: assessment.omissions }} labels={{ registered_level: '计划登记等级', source_refs: '评估来源', omissions: '省略步骤的评估依据' }}/></Disclosure>
      {!!text(plan.effective_level) && !!text(workflow.effective_level) && plan.effective_level !== workflow.effective_level && <Alert type="warning" showIcon title="当前等级与计划登记等级不同，需复核计划义务" description={`计划登记 ${text(plan.effective_level)}；当前 ${text(workflow.effective_level)}。`}/>}
      {(issues.length > 0 || facts.status === 'INVALID') && <Alert type="warning" showIcon title="部分执行事实无法可靠读取" description={issues.join('；') || '执行计划记录异常，不能按正常记录解释。'}/>}
      {!!text(workflow.error) && <Alert type="warning" showIcon title="门禁路由未解析" description={text(workflow.error)}/>}
      <div className="execution-summary">
        <p><span>当前步骤</span><strong>{currentDescription(facts, terminal)}</strong>{!!next.id && <small>下一计划步骤：{text(next.title)}</small>}</p>
        <p><span>当前参与角色</span><strong>{terminal ? '无，以下为历史记录' : currentRoles.length ? currentRoles.map(roleLabel).join('、') : '暂无已登记的当前参与'}</strong><small>未结束参与不代表执行者在线</small></p>
      </div>
      {!!latestBlockers.length && <div className="task-blocker" role="status"><strong>任务阻塞</strong>{latestBlockers.map((blocker, i) => <div key={i}><p>{text(blocker.reason) || '原因未记录'}</p><small>来源：Task 阻塞记录 · <RecordedTime value={blocker.created_at}/> · 结构化下一责任：未记录</small></div>)}</div>}
      {!!text(current.wait_reason) && <div className="step-wait-summary"><strong>步骤等待：</strong>{text(current.wait_reason)}<small>下一责任：{text(current.expected_next_actor) ? roleLabel(current.expected_next_actor) : '未记录'} · 来源：步骤记录 · <RecordedTime value={timeline.find(row => row.step_id === currentId && !row.participation_id)?.created_at}/></small></div>}
      <div className="section-heading execution-list-heading"><h3 ref={heading} tabIndex={-1}>执行步骤</h3><div className="step-list-actions"><span className="muted">{noPlan ? '尚未登记' : `已记录完成 ${steps.filter(step => step.status === 'COMPLETED').length} / 共 ${steps.length} 步`}</span><Button size="small" onClick={locate}>定位当前步骤</Button></div></div>
      {noPlan ? <div className="execution-empty"><strong>执行计划尚未登记</strong><p>暂无已绑定的步骤与角色参与记录。既有通用阶段可在下方“任务历史与诊断”中查看。</p></div> : <ol className="execution-step-list" ref={list} aria-label="正式记录的步骤顺序">
        {steps.map((step, index) => {
            const id = text(step.id), own = participants.filter(p => p.step_id === id), recent = timeline.find(row => row.step_id === id);
            return <li key={id}><details className={`execution-step${currentId === id ? ' current-step' : ''}`} data-step-id={id} data-state={text(step.status)}
              open={expanded.includes(id)} onToggle={event => { const open = event.currentTarget.open; setExpanded(old => open ? old.includes(id) ? old : [...old, id] : old.filter(value => value !== id)); }}>
              <summary aria-current={currentId === id ? 'step' : undefined}><span className="step-number">{index + 1}</span><span className="step-summary-content"><span className="execution-step-title"><strong>{text(step.title) || id}</strong><Tag>{terminal && step.status !== 'COMPLETED' ? '历史 · ' : ''}{statusNames[text(step.status)] || text(step.status) || '状态未记录'}</Tag>{currentId === id && <Tag color="blue">当前</Tag>}</span><span className="muted">{own.length ? `已参与：${Array.from(new Set(own.map(p => roleLabel(p.role)))).join('、')}` : `计划角色：${strings(step.roles).map(roleLabel).join('、') || '未记录'}`}</span><span className="step-recent">{text(recent?.summary) || '尚无步骤执行事件'}</span></span><span className="disclosure-caret" aria-hidden="true">{expanded.includes(id) ? '▾' : '▸'}</span></summary>
              <StepContent step={step} steps={steps} participants={participants} timeline={timeline} terminal={terminal} onWorkItem={onWorkItem}/>
            </details></li>;
        })}
      </ol>}
      {!noPlan && !steps.length && <p>没有可可靠展示的执行步骤，请查看上方读取提示。</p>}
      <Disclosure label={`计划调整与协调记录 · ${records(facts.plan_history).length} 版`}><Fields value={{ coordinator: facts.coordinator, history: facts.plan_history,
        scope_refs: plan.scope_refs, source: facts.source, last_recorded_at: facts.last_recorded_at, legacy_event_ids: facts.legacy_event_ids, legacy_issues: facts.legacy_issues }}/></Disclosure>
      <p className="muted execution-note">步骤完成、角色参与结束与验证通过分别记录。专业验证与验收见任务详情。</p>
    </section>;
});
