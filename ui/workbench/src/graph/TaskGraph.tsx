import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import { Button, Input, Select, Typography } from 'antd';
import { ReactFlow, ReactFlowProvider, Background, MarkerType, applyNodeChanges, useReactFlow, type Edge, type NodeChange } from '@xyflow/react';
import { WorkGroup, WorkNode, type WorkbenchNode } from './WorkNode';
import { relatedIds, visibleIds, type GraphModel, type GraphObject } from './model';
import { layoutGraph, NODE_HEIGHT, NODE_WIDTH } from './layout';
import { Disclosure, Fields } from '../components/Facts';
import { useAppearance } from '../theme';
import '@xyflow/react/dist/style.css';
const nodeTypes = { work: WorkNode, workGroup: WorkGroup };
export interface GraphHandle {
    locate: (id: string) => void;
    focusNode: (id: string) => void;
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
            setNodes(old => old.map(node => objects.has(node.id) ? { ...node, data: { ...node.data, object: objects.get(node.id) } } : node));
        }
        // Status updates never fit/re-layout. A topology change may lay out, but does not steal focus.
    }, [model]);
    const visible = useMemo(() => visibleIds(model, showItems, collapsed), [model, showItems, collapsed]);
    const highlighted = useMemo(() => direction === 'none' || !selectedId ? new Set<string>() : new Set([selectedId, ...relatedIds(model, selectedId, direction)]), [model, selectedId, direction]);
    const displayNodes = useMemo(() => nodes.map(node => {
        if (node.type === 'workGroup')
            return { ...node, hidden: !showItems };
        return {
            ...node, hidden: !visible.has(node.id), selected: node.id === selectedId,
            data: { ...node.data, dim: highlighted.size > 0 && !highlighted.has(node.id), emphasis: highlighted.has(node.id) }
        };
    }), [nodes, visible, showItems, selectedId, highlighted]);
    const edges: Edge[] = useMemo(() => model.edges.map(edge => ({
        id: edge.id, source: edge.source, target: edge.target,
        type: 'smoothstep', deletable: false, reconnectable: false, selectable: false, focusable: false,
        hidden: !visible.has(edge.source) || !visible.has(edge.target), label: '前置依赖',
        markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18 },
        style: {
            strokeWidth: highlighted.has(edge.source) && highlighted.has(edge.target) ? 2.5 : 1.5,
            opacity: highlighted.size > 0 && !(highlighted.has(edge.source) && highlighted.has(edge.target)) ? 0.22 : 1
        }
    })), [model.edges, visible, highlighted]);
    const focusNode = useCallback((id: string) => {
        const node = Array.from(root.current?.querySelectorAll<HTMLElement>('.react-flow__node') ?? []).find(el => el.getAttribute('data-id') === id);
        (node ?? root.current?.querySelector<HTMLElement>('#graph-query'))?.focus({ preventScroll: true });
    }, []);
    const locate = useCallback((id: string) => {
        const object = model.nodes.find(n => n.id === id);
        if (!object)
            return;
        setShowItems(true);
        setCollapsed(new Set());
        // Wait for hidden=false to reach React Flow before locating a collapsed search result.
        requestAnimationFrame(() => requestAnimationFrame(() => { void flow.fitView({ nodes: [{ id }], padding: .7, maxZoom: 1.15, duration: 180 }); focusNode(id); onOpen(object); }));
    }, [model, flow, focusNode, onOpen]);
    useImperativeHandle(ref, () => ({ locate, focusNode }), [locate, focusNode]);
    const onNodesChange = useCallback((changes: NodeChange<WorkbenchNode>[]) => {
        // Only coordinates/dimensions are mutable. Selection is controlled by the detail target.
        const allowed = changes.filter(change => change.type === 'position' || change.type === 'dimensions');
        setNodes(old => applyNodeChanges<WorkbenchNode>(allowed, old));
    }, []);
    const q = query.trim().toLocaleLowerCase();
    const results = q ? model.nodes.filter(n => `${n.objectId}\n${n.title}\n${n.owner}`.toLocaleLowerCase().includes(q)) : [];
    const hiddenCount = model.nodes.length - visible.size;
    const selected = model.nodes.find(n => n.id === selectedId);
    function expand() { setShowItems(true); setCollapsed(new Set()); }
    function rearrange() { setNodes(initialNodes(model)); requestAnimationFrame(() => requestAnimationFrame(() => { void flow.fitView({ padding: .14, duration: 180 }); })); }
    return <div className="task-graph" ref={root}>
    <div className="graph-toolbar" aria-label="图形浏览工具">
      <div className="graph-actions"><Button size="small" onClick={() => { void flow.zoomIn(); }} aria-label="放大画布">放大</Button><Button size="small" onClick={() => { void flow.zoomOut(); }} aria-label="缩小画布">缩小</Button><Button size="small" onClick={() => { void flow.fitView({ padding: .14, duration: 180 }); }}>适配视图</Button><Button size="small" onClick={rearrange}>重排</Button></div>
      <div className="graph-actions"><Button size="small" aria-pressed={!showItems} onClick={() => setShowItems(v => !v)}>{showItems ? '收起工作项' : '展开工作项'}</Button>
        <Button size="small" disabled={!selected || selected.kind === 'task'} onClick={() => { if (selectedId)
        setCollapsed(old => new Set([...old, selectedId])); }}>收起选中项下游</Button>
        <Button size="small" disabled={!hiddenCount && !collapsed.size} onClick={expand}>展开全部</Button></div>
      <label className="direction">依赖高亮<Select<'none' | 'upstream' | 'downstream'> className="direction-select" value={direction} onChange={setDirection} disabled={!selectedId} popupMatchSelectWidth={180} options={[{ value: 'none', label: '不高亮' }, { value: 'upstream', label: '选中项上游' }, { value: 'downstream', label: '选中项下游' }]}/></label>
    </div>
    <div className="graph-search"><label htmlFor="graph-query">定位对象</label><Input className="graph-query" id="graph-query" type="search" allowClear placeholder="当前 Task / WorkItem 的 ID、标题或负责人" value={query} onChange={e => setQuery(e.target.value)}/>
      <span className="muted">{model.nodes.length} 个对象 · {model.edges.length} 条已确认依赖{hiddenCount ? ` · 隐藏 ${hiddenCount} 个对象` : ''}</span></div>
    {q && <div className="graph-results" aria-label="对象搜索结果"><p>{results.length} 项匹配</p><ul>{results.map(n => <li key={n.id}><button type="button" onClick={() => locate(n.id)}><code>{n.objectId}</code><span>{n.title || '标题未记录'}</span>{!visible.has(n.id) && <small>展开并定位</small>}</button></li>)}</ul></div>}
    <div className="graph-canvas" onKeyDownCapture={event => {
            if (event.key !== 'Enter' && event.key !== ' ')
                return;
            const target = event.target as HTMLElement;
            if (target.matches('input,button,select,textarea,a'))
                return;
            const id = target.closest('.react-flow__node')?.getAttribute('data-id');
            const object = model.nodes.find(n => n.id === id);
            if (object) {
                event.preventDefault();
                event.stopPropagation();
                onOpen(object);
            }
        }}>
      <ReactFlow<WorkbenchNode, Edge> colorMode={resolved} nodes={displayNodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onNodeClick={(_, node) => { if (node.data.object)
        onOpen(node.data.object); }} fitView fitViewOptions={{ padding: .14, maxZoom: 1 }} minZoom={.08} maxZoom={2} nodesConnectable={false} edgesReconnectable={false} deleteKeyCode={null} nodesFocusable edgesFocusable={false} selectionOnDrag={false} multiSelectionKeyCode={null} onBeforeDelete={async () => false} attributionPosition="bottom-left">
        <Background gap={20} size={1}/>
      </ReactFlow>
    </div>
    <p className="graph-legend">边框 / 归属标识＝正式父 Task；箭头＝前置 → 后续。拖动只改变视觉坐标，不能增删或重连业务关系。状态不代表执行者在线。</p>
    {model.issues.length > 0 && <Disclosure className="graph-issues" open label={`图数据问题 · ${model.issues.length} 项`}><ul>{model.issues.map((issue, i) => <li key={`${issue.code}:${i}`}><Typography.Text code>{issue.code}</Typography.Text> {issue.message}</li>)}</ul></Disclosure>}
    {model.invalidRecords.length > 0 && <Disclosure className="graph-issues" label={`无正式身份的原始记录 · ${model.invalidRecords.length} 项`}>{model.invalidRecords.map((row, i) => <Fields key={i} value={row}/>)}</Disclosure>}
  </div>;
});
export const TaskGraph = forwardRef<GraphHandle, Props>((props, ref) => <ReactFlowProvider><GraphCanvas {...props} ref={ref}/></ReactFlowProvider>);
