import { forwardRef, useImperativeHandle, useRef } from 'react';
import { record, records, stageLabel, text } from '../facts';
import { Fields } from './Facts';
import type { FactRecord } from '../types';
export interface WorkflowHandle {
    locateCurrent: () => void;
}
export const WorkflowStrip = forwardRef<WorkflowHandle, {
    workflow: FactRecord;
}>(({ workflow }, ref) => {
    const current = record(workflow.current_step), next = record(workflow.next_step), steps = records(workflow.steps);
    const currentId = text(current.stage);
    const heading = useRef<HTMLHeadingElement>(null);
    const list = useRef<HTMLOListElement>(null);
    const sequence = useRef<HTMLDetailsElement>(null);
    useImperativeHandle(ref, () => ({
        locateCurrent() {
            const target = Array.from(list.current?.querySelectorAll<HTMLElement>('[data-stage]') ?? [])
                .find(element => !!currentId && element.dataset.stage === currentId);
            if (target && sequence.current) sequence.current.open = true;
            const focusTarget = target ?? heading.current;
            focusTarget?.focus();
            focusTarget?.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' });
        }
    }), [currentId]);
    return <section className="workflow-strip" aria-label="当前适用流程"><h3 ref={heading} tabIndex={-1}>实际流程 <small>有效等级 {text(workflow.effective_level) || '未解析'}</small></h3>
    <div className="step-summary"><p><span>当前步骤</span><strong>{stageLabel(current) || '当前步骤未解析'}</strong><small>来源：{text(workflow.current_step_source) || '未记录'}</small></p>
      <p><span>下一步</span><strong>{stageLabel(next) || '未提供下一步'}</strong><small>来源：{text(workflow.next_step_source) || '未记录'}</small></p></div>
    <details open ref={sequence}><summary>适用阶段顺序 · {steps.length} 项（不是工作项依赖）</summary>
      {steps.length ? <ol className="flow-steps" ref={list}>{steps.map((step, i) => <li key={`${text(step.stage)}:${i}`} data-stage={text(step.stage)} tabIndex={0} className={currentId && currentId === text(step.stage) ? 'current-step' : ''} aria-current={currentId && currentId === text(step.stage) ? 'step' : undefined}>
        <strong>{stageLabel(step)}</strong><span>{text(step.status) || '状态未记录'}</span><small>{text(record(step.role_display).label) || text(step.role) || '负责人未记录'}</small></li>)}</ol> : <p>当前未取得适用流程；不按参考阶段补齐 L3。</p>}
    </details><details className="compact-details"><summary>流程定义与解析来源</summary><Fields value={{ effective_level: workflow.effective_level, current_step: current, next_step: next, conditional_roles: workflow.conditional_roles, route: workflow.route }}/></details>
  </section>;
});
