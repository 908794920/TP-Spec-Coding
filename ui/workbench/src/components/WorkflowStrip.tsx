import { forwardRef, useImperativeHandle, useRef, useState } from 'react';
import { Collapse, Typography } from 'antd';
import { record, records, stageLabel, text } from '../facts';
import { Disclosure, Fields } from './Facts';
import type { FactRecord } from '../types';
import { ExecutionWorkflow } from './ExecutionWorkflow';
export interface WorkflowHandle {
    locateCurrent: () => void;
}
const LegacyWorkflowStrip = forwardRef<WorkflowHandle, {
    workflow: FactRecord;
    task: FactRecord;
}>(({ workflow, task }, ref) => {
    const current = record(workflow.current_step), next = record(workflow.next_step), steps = records(workflow.steps);
    const currentId = text(current.stage);
    const heading = useRef<HTMLHeadingElement>(null);
    const list = useRef<HTMLOListElement>(null);
    const [openKeys, setOpenKeys] = useState<string[]>(['sequence']);
    useImperativeHandle(ref, () => ({
        locateCurrent() {
            setOpenKeys(old => old.includes('sequence') ? old : [...old, 'sequence']);
            // The step list stays mounted (forceRender), but focus/scroll must wait for the panel to be visible.
            requestAnimationFrame(() => requestAnimationFrame(() => {
                const target = Array.from(list.current?.querySelectorAll<HTMLElement>('[data-stage]') ?? [])
                    .find(element => !!currentId && element.dataset.stage === currentId);
                const focusTarget = target ?? heading.current;
                focusTarget?.focus();
                focusTarget?.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' });
            }));
        }
    }), [currentId]);
    const terminal = task.state === 'COMPLETED' || task.state === 'CANCELLED' || workflow.retired === true;
    return <section className="workflow-strip" aria-label="当前适用流程"><h3 ref={heading} tabIndex={-1}>实际流程 <small>有效等级 {text(workflow.effective_level) || '未解析'}</small></h3>
    <p className="muted">历史未记录具体执行计划与独立角色参与；以下只展示可解析的既有流程事实。</p>
    <div className="step-summary"><p><span>当前步骤</span><strong>{terminal ? '已结束；无当前执行步骤' : stageLabel(current) || '当前步骤未解析'}</strong><small>来源：{text(workflow.current_step_source) || '未记录'}</small></p>
      <p><span>下一步</span><strong>{terminal ? '无' : stageLabel(next) || '未提供下一步'}</strong><small>来源：{text(workflow.next_step_source) || '未记录'}</small></p></div>
    {/* The contract-version guard blocks INFERRING the route; it does not make the task unreadable.
        So when no current step resolves, the RECORDED facts stay on screen instead of disappearing
        together with the inference — a task older than the active contract still shows where it is.
        The reference stages are deliberately still not presented as this task's route. */}
    {!currentId && <div className="workflow-fallback">
      {!!text(workflow.error) && <p className="muted">无法按当前契约推断流程：<Typography.Text code>{text(workflow.error)}</Typography.Text></p>}
      <Fields value={{ base_version: task.base_version, phase: task.phase, risk_level: task.risk_level, flow_level: task.flow_level }}
        labels={{ base_version: '任务契约', phase: '已记录阶段', risk_level: '风险等级' }}/>
    </div>}
    <Collapse className="wb-disclosure" size="small" activeKey={openKeys} onChange={keys => setOpenKeys(Array.isArray(keys) ? keys : [keys])} items={[{ key: 'sequence', forceRender: true, label: `适用阶段顺序 · ${steps.length} 项（不是工作项依赖）`, children:
      steps.length ? <ol className="flow-steps" ref={list}>{steps.map((step, i) => <li key={`${text(step.stage)}:${i}`} data-stage={text(step.stage)} tabIndex={0} className={currentId && currentId === text(step.stage) ? 'current-step' : ''} aria-current={currentId && currentId === text(step.stage) ? 'step' : undefined}>
        <strong>{stageLabel(step)}</strong><span>{text(step.status) || '状态未记录'}</span><small>{text(record(step.role_display).label) || text(step.role) || '负责人未记录'}</small></li>)}</ol> : <p>当前未取得适用流程；不按参考阶段补齐 L3。</p> }]}/>
    <Disclosure className="compact-details" label="流程定义与解析来源"><Fields value={{ effective_level: workflow.effective_level, current_step: current, next_step: next, conditional_roles: workflow.conditional_roles, route: workflow.route, error: workflow.error }}/></Disclosure>
  </section>;
});

export const WorkflowStrip = forwardRef<WorkflowHandle, { workflow: FactRecord; task: FactRecord }>((props, ref) => {
    const execution = record(props.workflow.execution);
    return execution.status && execution.status !== 'NOT_RECORDED'
        ? <ExecutionWorkflow {...props} ref={ref}/>
        : <LegacyWorkflowStrip {...props} ref={ref}/>;
});
