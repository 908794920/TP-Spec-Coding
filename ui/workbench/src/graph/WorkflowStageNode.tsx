import { Handle, Position, type NodeProps } from '@xyflow/react';
import { Button, Tag } from 'antd';
import { record, text, timestampText } from '../facts';
import { actions, statusNames } from '../components/executionView';
import { Disclosure, Fields } from '../components/Facts';
import type { WorkbenchNode } from './WorkNode';
import type { WorkflowStage } from './workflowRelations';

export const STAGE_WIDTH = 340, STAGE_HEIGHT = 310;
export function WorkflowStageNode({ data, selected }: NodeProps<WorkbenchNode>) {
    const stage = data.stage;
    if (!stage) return null;
    return <div className={`workflow-stage-node${selected ? ' is-selected' : ''}${stage.current ? ' is-current' : ''}`}>
      <Handle type="target" position={Position.Left} isConnectable={false}/>
      <div className="stage-node-heading"><span>{stage.activityOnly ? '已记录阶段活动' : stage.explicit ? '执行步骤' : '流程阶段'}</span><span>{stage.current ? '当前记录阶段' : stage.next ? '下一步' : ''}</span></div>
      <strong className="stage-node-title">{stage.title}</strong>
      <div className="stage-node-status">{stage.status}<span>{stage.events.length} 条已取得事件</span></div>
      <div className="stage-node-roles">
        {stage.roles.slice(0, 2).map(role => <section key={role.id}>
          <strong>{role.label}</strong>
          <small>{role.events.length ? `已记录 ${role.events.length} 条活动` : role.participations.length ? `已登记 ${role.participations.length} 次参与` : '计划角色 · 尚无执行记录'}</small>
          <p>{text(role.events[0]?.summary) || text(role.participations[0]?.result) || '暂无工作摘要'}</p>
        </section>)}
        {!stage.roles.length && <p className="muted">尚无角色记录</p>}
      </div>
      <div className="stage-node-more">{stage.roles.length > 2 ? `共 ${stage.roles.length} 个角色 · ` : ''}点击查看角色与全部已取得记录</div>
      <Handle type="source" position={Position.Right} isConnectable={false}/>
    </div>;
}

export function WorkflowStageDetails({ stage, onClose }: { stage: WorkflowStage; onClose: () => void }) {
    return <section className="workflow-stage-details" aria-label={`${stage.title}的角色与工作记录`}>
      <div className="section-heading"><div><h4>{stage.title} · 角色与工作记录</h4><p className="muted">{stage.status} · {stage.events.length} 条已取得事件。阶段记录与验证通过分别展示。</p></div><Button size="small" onClick={onClose}>收起阶段详情</Button></div>
      {stage.activityOnly && <p className="muted">这些活动已明确记录阶段，未绑定到后续执行计划中的具体步骤；保留实际工作，不补造步骤或参与起止。</p>}
      <div className="stage-role-details">
        {stage.roles.map(role => <section key={role.id} className="stage-role-history" aria-label={`${role.label}的工作记录`}>
          <header><strong>{role.label}</strong><span>{role.events.length} 条工作记录{role.participations.length ? ` · ${role.participations.length} 次参与` : ''}</span></header>
          {!role.events.length && !role.participations.length && <p className="muted">此角色来自阶段安排，尚无实际执行记录。</p>}
          {role.participations.map((participation, index) => <p key={text(participation.participation_id) || index}>
            <Tag>{statusNames[text(participation.status)] || text(participation.status) || '状态未记录'}</Tag>{text(participation.agent) || '执行者未记录'}{text(participation.result) && ` · ${text(participation.result)}`}
          </p>)}
          <ol className="stage-activity-list">{role.events.map((event, index) => {
              const detail = record(event.detail), presentation = record(event.presentation);
              return <li key={text(event.source_event_id ?? event.event_id ?? event.id) || index}>
                <div className="stage-activity-heading"><time title={text(event.created_at)}>{event.created_at ? timestampText(event.created_at) : '时间未记录'}</time><span>{actions[text(event.action)] || text(presentation.event_label) || text(event.operation) || text(event.event_type) || '事件'}</span></div>
                <p>{text(event.summary) || '摘要未记录'}</p>
                {!!text(event.result) && <p>结果：{text(event.result)}</p>}
                <Disclosure label="来源与事件详情"><Fields value={{ event_id: event.source_event_id ?? event.event_id ?? event.id,
                  actor: event.actor, actor_agent: event.actor_agent, step_id: event.step_id, participation_id: event.participation_id,
                  phase: detail.phase, decision: event.decision, evidence: event.evidence_path ?? event.evidence, detail }}/></Disclosure>
              </li>;
          })}</ol>
        </section>)}
      </div>
      <Disclosure label="阶段定义与状态来源"><Fields value={stage.record}/></Disclosure>
    </section>;
}
