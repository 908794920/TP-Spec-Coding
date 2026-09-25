import { Handle, Position, type Node, type NodeProps } from '@xyflow/react';
import type { GraphObject } from './model';
import { stateLabel, stateTone } from '../facts';
import type { WorkflowStage } from './workflowRelations';
export type WorkbenchNode = Node<{
    object?: GraphObject;
    stage?: WorkflowStage;
    label?: string;
    count?: number;
    dim?: boolean;
    emphasis?: boolean;
}, 'work' | 'workGroup' | 'stage'>;
export function WorkNode({ data, selected }: NodeProps<WorkbenchNode>) {
    const row = data.object;
    if (!row)
        return null;
    return <div className={`work-node ${selected ? 'is-selected' : ''} ${data.dim ? 'is-dim' : ''} ${data.emphasis ? 'is-emphasized' : ''}`}>
    {row.kind === 'work_item' && <Handle type="target" position={Position.Left} isConnectable={false}/>}
    <div className="node-kind"><span>{row.kind === 'task' ? 'Task' : 'WorkItem'}</span>{row.issues.length > 0 && <span title={row.issues.join('、')}>数据待核对</span>}</div>
    <code className="node-id" title={row.objectId}>{row.objectId || 'ID 未记录'}</code><strong className="node-title" title={row.title}>{row.title || '标题未记录'}</strong>
    <div className={`node-state tone-${stateTone(row.kind, row.status)}`} title={stateLabel(row.kind, row.status)}>{stateLabel(row.kind, row.status)}</div>
    <div className="node-owner" title={row.owner}>负责人：{row.owner || '未记录'}</div>
    {row.kind === 'work_item' && <Handle type="source" position={Position.Right} isConnectable={false}/>}
    {row.kind === 'task' && <Handle id="stages" type="source" position={Position.Bottom} isConnectable={false}/>}
  </div>;
}
export function WorkGroup({ data }: NodeProps<WorkbenchNode>) { return <div className="work-group-label"><strong>{data.label}</strong><span>{data.count} 项 · 边框表示归属，不是执行依赖</span></div>; }
