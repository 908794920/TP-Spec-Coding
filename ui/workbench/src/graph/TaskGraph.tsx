import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import { Button, Input, Select, Typography } from 'antd';
import { ReactFlow, ReactFlowProvider, Background, MarkerType, applyNodeChanges, useReactFlow, type Edge, type NodeChange } from '@xyflow/react';
import { WorkGroup, WorkNode, type WorkbenchNode } from './WorkNode';
import { relatedIds, visibleIds, type GraphModel, type GraphObject } from './model';
import { layoutGraph, NODE_HEIGHT, NODE_WIDTH } from './layout';
import { Disclosure, Fields } from '../components/Facts';
import { useAppearance } from '../theme';
import { text } from '../facts';
import { WorkflowStageNode, WorkflowStageDetails, STAGE_WIDTH, STAGE_HEIGHT } from './WorkflowStageNode';
import { stageHasCompletedWork } from './workflowRelations';
import '@xyflow/react/dist/style.css';
import './workflowRelations.css';
const nodeTypes = { work: WorkNode, workGroup: WorkGroup, stage: WorkflowStageNode };
const relationStages = (model: GraphModel) => [...model.workflow.activityStages, ...model.workflow.stages];
const completionStyle = (completed: boolean) => completed ? { stroke: 'var(--graph-completed)', strokeWidth: 2 } : {};
const markerColor = (completed: boolean) => completed ? 'var(--graph-completed)' : 'var(--node-border)';
export interface GraphHandle {
    locate: (id: string) => void;
    focusNode: (id: string) => void;
    locateCurrent: () => void;
}
interface Props {
    model: GraphModel;
    selectedId: string;
    onOpen: (object: GraphObject) => void;
}
function initialNodes(model: GraphModel): WorkbenchNode[] {
    const layout = layoutGraph(model), count = model.nodes.filter(n => n.belongs).length;
    const group: WorkbenchNode = {
        id: model.groupId, type: 'workGroup', data: { label: `归属 Task · ${model.taskId}`, count },
        position: { x: layout.group.x, y: layout.group.y }, style: { width: layout.group.width, height: layout.group.height },
        selectable: false, draggable: false, focusable: false, connectable: false, deletable: false
    };
    return [
        ...(count ? [group] : []),
        ...model.nodes.map(object => ({
            id: object.id, type: 'work' as const, data: { object }, position: layout.positions[object.id],
            ...(object.belongs ? { parentId: model.groupId, extent: 'parent' as const } : {}),
            style: { width: NODE_WIDTH, height: NODE_HEIGHT }, connectable: false, deletable: false,
            ariaLabel: `${object.kind === 'task' ? 'Task' : 'WorkItem'} ${object.objectId} ${object.title}，按 Enter 打开详情`
        })),
        ...relationStages(model).map(stage => ({
            id: stage.id, type: 'stage' as const, data: { stage }, position: {
                x: 32 + (stage.activityOnly ? model.workflow.activityStages : model.workflow.stages).findIndex(item => item.id === stage.id) * (STAGE_WIDTH + 64),
                y: !stage.activityOnly && model.workflow.activityStages.length ? 570 : 180 },
            style: { width: STAGE_WIDTH, height: STAGE_HEIGHT }, connectable: false, deletable: false,
            ariaLabel: `${stage.title} · ${stage.status}，按 Enter 查看角色与工作记录`
        })),
    ];
}
const GraphCanvas = forwardRef<GraphHandle, Props>(({ model, selectedId, onOpen }, ref) => {
    const { resolved } = useAppearance();
    const root = useRef<HTMLDivElement>(null);
    const flow = useReactFlow<WorkbenchNode, Edge>();
    const [nodes, setNodes] = useState<WorkbenchNode[]>(() => initialNodes(model));
    const [query, setQuery] = useState(''), [showItems, setShowItems] = useState(true);
    const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
    const [direction, setDirection] = useState<'none' | 'upstream' | 'downstream'>('none');
    const [stageId, setStageId] = useState('');
    const selectedStage = relationStages(model).find(stage => stage.id === stageId);
    const currentStage = model.workflow.stages.find(stage => stage.current) ?? model.workflow.stages.find(stage => stage.next);
    const initialFocus = model.workflow.stages.length ? model.workflow.stages.slice(Math.max(0, model.workflow.stages.findIndex(stage => stage.id === currentStage?.id)),
        Math.max(0, model.workflow.stages.findIndex(stage => stage.id === currentStage?.id)) + 2).map(stage => ({ id: stage.id })) : undefined;
    const previousTopology = useRef(model.topology);
    useEffect(() => {
        const changed = previousTopology.current !== model.topology;
        if (changed) {
            setNodes(initialNodes(model));
            previousTopology.current = model.topology;
            setCollapsed(old => new Set([...old].filter(id => model.nodes.some(n => n.id === id))));
        }
        else {
            const objects = new Map(model.nodes.map(n => [n.id, n]));
            const stages = new Map(relationStages(model).map(stage => [stage.id, stage]));
            setNodes(old => old.map(node => objects.has(node.id) ? { ...node, data: { ...node.data, object: objects.get(node.id) } }
                : stages.has(node.id) ? { ...node, data: { ...node.data, stage: stages.get(node.id) } } : node));
        }
        // Status updates never fit/re-layout. A topology change may lay out, but does not steal focus.
    }, [model]);
    const visible = useMemo(() => visibleIds(model, showItems, collapsed), [model, showItems, collapsed]);
    const highlighted = useMemo(() => direction === 'none' || !selectedId ? new Set<string>() : new Set([selectedId, ...relatedIds(model, selectedId, direction)]), [model, selectedId, direction]);
    const completedWork = useMemo(() => new Set(model.nodes.filter(node => node.status === 'COMPLETED' && !node.issues.length).map(node => node.id)), [model.nodes]);
    const displayNodes = useMemo(() => nodes.map(node => {
        if (node.type === 'workGroup')
            return { ...node, hidden: !showItems };
        if (node.type === 'stage') return { ...node, selected: node.id === stageId };
        return {
            ...node, hidden: !visible.has(node.id), selected: node.id === selectedId,
            data: { ...node.data, dim: highlighted.size > 0 && !highlighted.has(node.id), emphasis: highlighted.has(node.id) }
        };
    }), [nodes, visible, showItems, selectedId, highlighted, stageId]);
    const edges: Edge[] = useMemo(() => [...model.edges.map(edge => ({
        id: edge.id, source: edge.source, target: edge.target,
        type: 'smoothstep', deletable: false, reconnectable: false, selectable: false, focusable: false,
        hidden: !visible.has(edge.source) || !visible.has(edge.target), label: '前置依赖',
        className: completedWork.has(edge.target) ? 'edge-completed' : undefined,
        markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18, color: markerColor(completedWork.has(edge.target)) },
        style: {
            ...completionStyle(completedWork.has(edge.target)),
            strokeWidth: highlighted.has(edge.source) && highlighted.has(edge.target) ? 2.5 : completedWork.has(edge.target) ? 2 : 1.5,
            opacity: highlighted.size > 0 && !(highlighted.has(edge.source) && highlighted.has(edge.target)) ? 0.22 : 1
        }
    })), ...model.workflow.stages.map((stage, index) => ({
        id: `${stage.id}:sequence`, source: index ? model.workflow.stages[index - 1].id : model.taskNodeId, target: stage.id,
        ...(index ? {} : { sourceHandle: 'stages' }),
        type: 'smoothstep', deletable: false, reconnectable: false, selectable: false, focusable: false,
        label: index ? '阶段顺序' : '任务阶段', className: stageHasCompletedWork(stage) ? 'edge-completed' : undefined,
        style: { strokeDasharray: '5 4', ...completionStyle(stageHasCompletedWork(stage)) },
        markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18, color: markerColor(stageHasCompletedWork(stage)) }
    })), ...model.workflow.activityStages.map(stage => ({
        id: `${stage.id}:recorded`, source: model.taskNodeId, sourceHandle: 'stages', target: stage.id,
        type: 'smoothstep', deletable: false, reconnectable: false, selectable: false, focusable: false,
        label: stageHasCompletedWork(stage) ? '阶段活动 · 已记录完成' : '阶段活动', className: stageHasCompletedWork(stage) ? 'edge-completed' : undefined,
        style: { strokeDasharray: '2 5', ...completionStyle(stageHasCompletedWork(stage)) }
    }))], [model.edges, model.workflow.stages, model.workflow.activityStages, model.taskNodeId, visible, highlighted, completedWork]);
    const focusNode = useCallback((id: string) => {
        const node = Array.from(root.current?.querySelectorAll<HTMLElement>('.react-flow__node') ?? []).find(el => el.getAttribute('data-id') === id);
        (node ?? root.current?.querySelector<HTMLElement>('#graph-query'))?.focus({ preventScroll: true });
    }, []);
    const locate = useCallback((id: string) => {
        const stage = relationStages(model).find(item => item.id === id);
        if (stage) {
            setStageId(id);
            requestAnimationFrame(() => { void flow.fitView({ nodes: [{ id }], padding: .3, maxZoom: 1, duration: 180 }); focusNode(id); });
            return;
        }
        const object = model.nodes.find(n => n.id === id);
        if (!object)
            return;
        setShowItems(true);
        setCollapsed(new Set());
        // Wait for hidden=false to reach React Flow before locating a collapsed search result.
        requestAnimationFrame(() => requestAnimationFrame(() => { void flow.fitView({ nodes: [{ id }], padding: .7, maxZoom: 1.15, duration: 180 }); focusNode(id); onOpen(object); }));
    }, [model, flow, focusNode, onOpen]);
    useImperativeHandle(ref, () => ({ locate, focusNode, locateCurrent: () => {
        const target = currentStage ?? model.workflow.stages[0];
        if (target) locate(target.id);
        else locate(model.taskNodeId);
    } }), [locate, focusNode, currentStage, model.workflow.stages, model.taskNodeId]);
    const onNodesChange = useCallback((changes: NodeChange<WorkbenchNode>[]) => {
        // Only coordinates/dimensions are mutable. Selection is controlled by the detail target.
        const allowed = changes.filter(change => change.type === 'position' || change.type === 'dimensions');
        setNodes(old => applyNodeChanges<WorkbenchNode>(allowed, old));
    }, []);
    const q = query.trim().toLocaleLowerCase();
    const results = q ? model.nodes.filter(n => `${n.objectId}\n${n.title}\n${n.owner}`.toLocaleLowerCase().includes(q)) : [];
    const stageResults = q ? relationStages(model).filter(stage => `${stage.title}\n${stage.key}\n${stage.roles.map(role => role.label).join('\n')}`.toLocaleLowerCase().includes(q)) : [];
    const hiddenCount = model.nodes.length - visible.size;
    const selected = model.nodes.find(n => n.id === selectedId);
    function expand() { setShowItems(true); setCollapsed(new Set()); }
    function rearrange() { setNodes(initialNodes(model)); requestAnimationFrame(() => requestAnimationFrame(() => { void flow.fitView({ padding: .14, duration: 180 }); })); }
    return <div className="task-graph" ref={root}>
    {!!model.workflow.activityStages.length && <nav className="workflow-stage-navigation" aria-label="已记录阶段活动定位"><span className="muted">已有阶段活动</span>
      {model.workflow.activityStages.map(stage => <Button key={stage.id} size="small" type={stage.id === stageId ? 'primary' : 'default'} onClick={() => locate(stage.id)}>{stage.title} · {stage.events.length} 条</Button>)}
    </nav>}
    {!!model.workflow.stages.length && <nav className="workflow-stage-navigation" aria-label="流程阶段定位">
      {model.workflow.stages.map(stage => <Button key={stage.id} size="small" aria-current={stage.current ? 'step' : undefined}
        type={stage.id === stageId ? 'primary' : 'default'} onClick={() => locate(stage.id)}>{stage.title}{stage.current ? ' · 当前记录' : stage.next ? ' · 下一步' : ''}</Button>)}
    </nav>}
    <div className="graph-toolbar" aria-label="图形浏览工具">
      <div className="graph-actions"><Button size="small" onClick={() => { void flow.zoomIn(); }} aria-label="放大画布">放大</Button><Button size="small" onClick={() => { void flow.zoomOut(); }} aria-label="缩小画布">缩小</Button><Button size="small" onClick={() => { void flow.fitView({ padding: .14, duration: 180 }); }}>适配视图</Button><Button size="small" onClick={rearrange}>重排</Button></div>
      <div className="graph-actions"><Button size="small" aria-pressed={!showItems} onClick={() => setShowItems(v => !v)}>{showItems ? '收起工作项' : '展开工作项'}</Button>
        <Button size="small" disabled={!selected || selected.kind === 'task'} onClick={() => { if (selectedId)
        setCollapsed(old => new Set([...old, selectedId])); }}>收起选中项下游</Button>
        <Button size="small" disabled={!hiddenCount && !collapsed.size} onClick={expand}>展开全部</Button></div>
      <label className="direction">依赖高亮<Select<'none' | 'upstream' | 'downstream'> className="direction-select" value={direction} onChange={setDirection} disabled={!selectedId} popupMatchSelectWidth={180} options={[{ value: 'none', label: '不高亮' }, { value: 'upstream', label: '选中项上游' }, { value: 'downstream', label: '选中项下游' }]}/></label>
    </div>
    <div className="graph-search"><label htmlFor="graph-query">定位对象</label><Input className="graph-query" id="graph-query" type="search" allowClear placeholder="阶段、角色、Task / WorkItem" value={query} onChange={e => setQuery(e.target.value)}/>
      <span className="muted">{model.workflow.activityStages.length ? `${model.workflow.activityStages.length} 组阶段活动 · ` : ''}{model.workflow.stages.length} 个{model.workflow.explicit ? '计划步骤' : '阶段'} · {model.nodes.length} 个工作对象 · {model.edges.length} 条工作依赖{hiddenCount ? ` · 隐藏 ${hiddenCount} 个工作对象` : ''}</span></div>
    {q && <div className="graph-results" aria-label="对象搜索结果"><p>{results.length + stageResults.length} 项匹配</p><ul>{stageResults.map(stage => <li key={stage.id}><button type="button" onClick={() => locate(stage.id)}>{stage.title} · {stage.roles.map(role => role.label).join('、')}</button></li>)}{results.map(n => <li key={n.id}><button type="button" onClick={() => locate(n.id)}><code>{n.objectId}</code><span>{n.title || '标题未记录'}</span>{!visible.has(n.id) && <small>展开并定位</small>}</button></li>)}</ul></div>}
    <div className="graph-canvas" onKeyDownCapture={event => {
            if (event.key !== 'Enter' && event.key !== ' ')
                return;
            const target = event.target as HTMLElement;
            if (target.matches('input,button,select,textarea,a'))
                return;
            const id = target.closest('.react-flow__node')?.getAttribute('data-id');
            const stage = relationStages(model).find(item => item.id === id);
            if (stage) {
                event.preventDefault(); event.stopPropagation(); setStageId(stage.id); return;
            }
            const object = model.nodes.find(n => n.id === id);
            if (object) {
                event.preventDefault();
                event.stopPropagation();
                onOpen(object);
            }
        }}>
      <ReactFlow<WorkbenchNode, Edge> colorMode={resolved} nodes={displayNodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onNodeClick={(_, node) => {
        if (node.data.stage) setStageId(node.data.stage.id);
        else if (node.data.object) { setStageId(''); onOpen(node.data.object); }
      }} fitView fitViewOptions={{ padding: .14, maxZoom: 1, ...(initialFocus ? { nodes: initialFocus } : {}) }} minZoom={.08} maxZoom={2} nodesConnectable={false} edgesReconnectable={false} deleteKeyCode={null} nodesFocusable edgesFocusable={false} selectionOnDrag={false} multiSelectionKeyCode={null} onBeforeDelete={async () => false} attributionPosition="bottom-left">
        <Background gap={20} size={1}/>
      </ReactFlow>
    </div>
    <p className="graph-legend"><span className="completed-edge-legend">绿色连线：指向的工作已有完成记录</span>；灰色：待执行或完成状态未确认。虚线连接阶段，实线表示工作依赖；阶段活动完成不等于整任务验收通过。</p>
    {model.workflow.truncated && <p className="warning" role="status">任务时间线仅取得最近 {model.workflow.returned} / {model.workflow.total} 条事件；阶段明细展示本次已取得记录，不能据此判断没有更早活动。</p>}
    {selectedStage && <WorkflowStageDetails stage={selectedStage} onClose={() => { setStageId(''); requestAnimationFrame(() => focusNode(selectedStage.id)); }}/>}
    {!!model.workflow.unassigned.length && <Disclosure label={`未绑定具体阶段的事件 · ${model.workflow.unassigned.length} 条`}>
      <p className="muted">以下记录没有足够的阶段绑定信息，保留原始记录，不按角色或摘要猜测所属阶段。</p>
      {model.workflow.unassigned.map((event, index) => <Disclosure key={text(event.source_event_id ?? event.event_id ?? event.id) || index} label={text(event.summary) || '事件摘要未记录'}><Fields value={event}/></Disclosure>)}
    </Disclosure>}
    {model.issues.length > 0 && <Disclosure className="graph-issues" open label={`图数据问题 · ${model.issues.length} 项`}><ul>{model.issues.map((issue, i) => <li key={`${issue.code}:${i}`}><Typography.Text code>{issue.code}</Typography.Text> {issue.message}</li>)}</ul></Disclosure>}
    {model.invalidRecords.length > 0 && <Disclosure className="graph-issues" label={`无正式身份的原始记录 · ${model.invalidRecords.length} 项`}>{model.invalidRecords.map((row, i) => <Fields key={i} value={row}/>)}</Disclosure>}
  </div>;
});
export const TaskGraph = forwardRef<GraphHandle, Props>((props, ref) => <ReactFlowProvider><GraphCanvas {...props} ref={ref}/></ReactFlowProvider>);
