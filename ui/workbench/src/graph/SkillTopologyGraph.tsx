import { useCallback, useEffect, useMemo, useState } from 'react';
import { Button, Tag, Typography } from 'antd';
import { Background, Handle, MarkerType, Position, ReactFlow, ReactFlowProvider, useNodesState, useReactFlow, type Edge, type Node, type NodeProps } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { explainValue } from '../facts';
import { KIND_LABELS, SKILL_STATUS_LABELS, SOURCE_LABELS, layoutTopology, topologyDisplayEdges, TOPOLOGY_COLUMN_KINDS, TOPOLOGY_NODE_WIDTH, TOPOLOGY_NODE_HEIGHT, type Topology } from './topology';
import { useAppearance } from '../theme';

const EDGE_COLOR = 'var(--node-border)';
interface SkillNodeData extends Record<string, unknown> {
    label: string;
    id: string;
    kind: string;
    sourceKind: string;
    status: string;
    order: number | null;
    detached: boolean;
    shared: number;
    dim: boolean;
    emphasis: boolean;
    selected: boolean;
    usage?: string;
    onSelect: (id: string) => void;
}
type SkillFlowNode = Node<SkillNodeData, 'skill'>;

function SkillNode({ data }: NodeProps<SkillFlowNode>) {
    const source = SOURCE_LABELS[data.sourceKind] ?? data.sourceKind;
    const status = SKILL_STATUS_LABELS[data.status] ?? data.status;
    const isEntry = data.kind === 'product-entry';
    return <div className={`skill-graph-node${isEntry ? ' is-entry' : ''}${data.emphasis ? ' is-emphasized' : ''}${data.dim ? ' is-dim' : ''}${data.sourceKind === 'external' ? ' is-external' : ''}`}
      title={`${data.id} · ${source} · ${status}`}>
      <Handle id="target-left" type="target" position={Position.Left}/>
      <Handle id="target-right" type="target" position={Position.Right}/>
      <div className="skill-graph-head">
        {data.order !== null && <span className="skill-order">{data.order}</span>}
        <button type="button" className="skill-node-select nodrag nopan" aria-pressed={data.selected}
          aria-label={`选择 ${data.label}（${data.id}，${source}，${status}）`}
          onClick={event => { event.stopPropagation(); data.onSelect(data.id); }}>{data.label}</button>
        <Tag variant="filled" className={isEntry ? 'skill-entry-badge' : undefined} title={explainValue('kind', data.kind) || data.kind}>{isEntry ? '总入口' : KIND_LABELS[data.kind] ?? data.kind}</Tag>
        {data.shared > 1 && <Typography.Text type="secondary" className="skill-shared" title="目录声明的引用关系数量">×{data.shared}</Typography.Text>}
      </div>
      <div className="skill-node-meta"><span className="skill-id">{data.id}</span>
        {data.usage && <span className="skill-usage" title={`相对于当前选中领域/角色的声明：${data.usage}`}>{data.usage}</span>}
      </div>
      <div className="skill-node-state">{isEntry && <span className="skill-entry-hint">从这里开始</span>}<Tag variant="filled">{source}</Tag><span>{status}</span>
        {data.detached && <span>{data.sourceKind === 'external' ? '未关联' : '未连通'}</span>}
      </div>
      <Handle id="source-left" type="source" position={Position.Left}/>
      <Handle id="source-right" type="source" position={Position.Right}/>
    </div>;
}
const nodeTypes = { skill: SkillNode };

interface GraphProps { topology: Topology; onOpenDocument: (id: string) => void; disabled?: boolean }
function Canvas({ topology, onOpenDocument, disabled }: GraphProps) {
    const { resolved } = useAppearance();
    const flow = useReactFlow<SkillFlowNode, Edge>();
    const [selected, setSelected] = useState('');
    const displayEdges = useMemo(() => topologyDisplayEdges(topology), [topology]);
    const select = useCallback((id: string) => setSelected(current => current === id ? '' : id), []);
    const seeded = useMemo<SkillFlowNode[]>(() => layoutTopology(topology).map(item => {
        const node = topology.nodes.get(item.id)!;
        return {
            id: item.id, type: 'skill', position: item.position,
            style: { width: TOPOLOGY_NODE_WIDTH, height: TOPOLOGY_NODE_HEIGHT },
            data: { label: node.name, id: node.id, kind: node.kind, sourceKind: node.sourceKind, status: node.status,
                shared: topology.parentCount.get(node.id) ?? 0, order: item.order, detached: item.detached,
                dim: false, emphasis: false, selected: false, onSelect: select },
        };
    }), [topology, select]);
    const [nodes, setNodes, onNodesChange] = useNodesState<SkillFlowNode>(seeded);
    useEffect(() => {
        setNodes(seeded); setSelected('');
        // Fit again after a manual catalog refresh so added nodes remain visible.
        let next = 0;
        const first = requestAnimationFrame(() => { next = requestAnimationFrame(() => { void flow.fitView({ padding: .12, maxZoom: 1 }); }); });
        return () => { cancelAnimationFrame(first); cancelAnimationFrame(next); };
    }, [seeded, setNodes, flow]);
    const related = useMemo(() => {
        if (!selected) return new Set<string>();
        const ids = new Set([selected]);
        displayEdges.forEach(edge => {
            if (edge.from === selected) ids.add(edge.to);
            if (edge.to === selected) ids.add(edge.from);
        });
        return ids;
    }, [selected, displayEdges]);
    const usage = useMemo(() => {
        const result = new Map<string, string>();
        topology.edges.filter(edge => edge.from === selected && ['uses-skill', 'uses'].includes(edge.relation)).forEach(edge => {
            result.set(edge.to, edge.mode === 'default' ? '默认声明' : edge.mode === 'conditional' ? '条件声明' : edge.mode === 'declared' ? '声明关联' : edge.mode || '方式未记录');
        });
        return result;
    }, [selected, topology]);
    const display = useMemo(() => nodes.map(node => ({ ...node, data: { ...node.data,
        selected: selected === node.id, usage: usage.get(node.id), emphasis: related.has(node.id), dim: related.size > 0 && !related.has(node.id) } })), [nodes, related, usage, selected]);
    const edges: Edge[] = useMemo(() => {
        const positions = new Map(nodes.map(node => [node.id, node.position.x]));
        return displayEdges.map((edge, index) => {
        const highlighted = edge.from === selected || edge.to === selected;
        const color = highlighted ? 'var(--accent)' : EDGE_COLOR;
        const toLeft = (positions.get(edge.to) ?? 0) < (positions.get(edge.from) ?? 0);
        return {
            id: `${edge.from}->${edge.to}:${index}`, source: edge.from, target: edge.to,
            sourceHandle: toLeft ? 'source-left' : 'source-right', targetHandle: toLeft ? 'target-right' : 'target-left',
            type: 'smoothstep', deletable: false, reconnectable: false, selectable: false, focusable: false,
            zIndex: highlighted ? 1 : 0,
            markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color },
            ariaLabel: edge.relation === 'management-group' ? '自定义 SKILL 管理分组' : undefined,
            style: { stroke: color, strokeWidth: highlighted ? 2 : 1.5, strokeDasharray: edge.relation === 'management-group' ? '5 4' : undefined },
        };
        });
    }, [displayEdges, selected, nodes]);
    const counts = useMemo(() => {
        const byKind = new Map(topology.kinds);
        const known = TOPOLOGY_COLUMN_KINDS.map(kind => [KIND_LABELS[kind], byKind.get(kind) ?? 0] as const);
        const other = topology.nodes.size - known.reduce((total, [, count]) => total + count, 0);
        return other ? [...known, ['其他', other] as const] : known;
    }, [topology]);
    const externalOrphans = topology.orphans.filter(node => node.sourceKind === 'external').length;
    return <div className="topology-graph">
      <div className="graph-toolbar"><div className="graph-actions">
        <Button size="small" onClick={() => { void flow.zoomIn(); }}>放大</Button>
        <Button size="small" onClick={() => { void flow.zoomOut(); }}>缩小</Button>
        <Button size="small" onClick={() => { void flow.fitView({ padding: .12, maxZoom: 1 }); }}>适配视图</Button>
        <Button size="small" disabled={!selected} onClick={() => setSelected('')}>清除选中</Button>
      </div><Typography.Text type="secondary" className="graph-summary">
        {counts.map(([kind, count]) => `${kind} ${count} 个`).join(' · ')}；共 {topology.nodes.size} 个节点、{topology.edges.length} 条声明关系
      </Typography.Text>
        <Button size="small" disabled={!selected || disabled} title={selected ? '查看选中节点的来源与设定' : '请先选择一个节点'} onClick={() => onOpenDocument(selected)}>查看设定</Button>
      </div>
      {!!topology.orphans.length && <p className="skill-detached-note">外部能力（未关联）{externalOrphans} 个{topology.orphans.length > externalOrphans ? `，其他未连通节点 ${topology.orphans.length - externalOrphans} 个` : ''}；管理分组不代表已声明用途关联，未关联或未连通标记保留。</p>}
      <div className="graph-canvas">
        <ReactFlow<SkillFlowNode, Edge> colorMode={resolved} nodes={display} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange}
          onNodeClick={(_, node) => select(node.id)} nodesFocusable={false}
          fitView fitViewOptions={{ padding: .12, maxZoom: 1 }} minZoom={.1} maxZoom={2}
          nodesConnectable={false} edgesReconnectable={false} deleteKeyCode={null} edgesFocusable={false}
          selectionOnDrag={false} multiSelectionKeyCode={null} onBeforeDelete={async () => false} attributionPosition="bottom-left">
          <Background gap={20} size={1}/>
        </ReactFlow>
      </div>
      <p className="graph-legend">统一入口向两侧展开：浅层领域在左，含角色的分支在右。外部 SKILL 统一放在“自定义 SKILL 管理”的下一层，虚线表示管理分组；用途关联在设定详情中查看，实际使用方式不变。实线表示目录声明关系。数量与 ×N 仍统计原目录声明，不含管理分组，不是调用次数。可点击或用 Tab/Enter 选择节点，再查看设定。</p>
    </div>;
}

export function SkillTopologyGraph(props: GraphProps) {
    return <ReactFlowProvider><Canvas {...props}/></ReactFlowProvider>;
}
