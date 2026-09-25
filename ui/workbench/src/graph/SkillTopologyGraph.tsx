import { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Modal, Spin, Tag, Typography } from 'antd';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeSlug from 'rehype-slug';
import { api } from '../api';
import { Background, Handle, MarkerType, Position, ReactFlow, ReactFlowProvider, useNodesState, type Edge, type Node, type NodeProps } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { explainValue } from '../facts';
import type { Topology } from './topology';
import { useAppearance } from '../theme';

/* The skill topology as a node-link graph. Positions are computed, never auto-laid-out: x is the
   level and y is the node's order inside that level, so the sequence the payload carries in its edge
   order stays visible as top-to-bottom order in every column. Shared skills are one node with several
   incoming edges rather than a row per owner, which is what makes the fan-in readable. */
const NODE_WIDTH = 212, NODE_HEIGHT = 46, GAP_X = 72, GAP_Y = 12;
const KIND_BADGE: Record<string, string> = { 'product-entry': '入口', 'domain-agent': '领域 Agent', 'formal-role': '角色', 'capability-skill': 'SKILL' };
const RELATION_LABEL: Record<string, string> = { 'routes-to': '路由', 'owns-role': '拥有', 'uses-skill': '使用' };
// 默认连线统一浅灰；选中节点的直接关联线与箭头使用强调色。
const EDGE_COLOR = 'var(--node-border)';

interface SkillNodeData extends Record<string, unknown> {
    label: string;
    id: string;
    kind: string;
    order: number | null;
    shared: number;
    dim: boolean;
    emphasis: boolean;
    usage?: string;
}
type SkillFlowNode = Node<SkillNodeData, 'skill'>;

function SkillNode({ data }: NodeProps<SkillFlowNode>) {
    return <div className={`skill-graph-node${data.emphasis ? ' is-emphasized' : ''}${data.dim ? ' is-dim' : ''}`}
      title={data.id}>
      <Handle type="target" position={Position.Left}/>
      <div className="skill-graph-head">
        {data.order !== null && <span className="skill-order">{data.order}</span>}
        <Typography.Text strong>{data.label}</Typography.Text>
        <Tag variant="filled" title={explainValue('kind', data.kind) || data.kind}>{KIND_BADGE[data.kind] ?? data.kind}</Tag>
        {data.shared > 1 && <Typography.Text type="secondary" className="skill-shared">×{data.shared}</Typography.Text>}
      </div>
      <div className="skill-node-meta">{data.label !== data.id && <span className="skill-id">{data.id}</span>}
        {data.usage && <span className="skill-usage" title={`相对于当前选中角色：${data.usage}`}>{data.usage}</span>}
      </div>
      <Handle type="source" position={Position.Right}/>
    </div>;
}
/* Declared once: a new object on every render makes React Flow re-mount every node. */
const nodeTypes = { skill: SkillNode };

function buildNodes(topology: Topology): SkillFlowNode[] {
    const byLevel = new Map<number, string[]>();
    topology.nodes.forEach((_, id) => {
        const level = topology.level.get(id);
        if (level === undefined)
            return;
        byLevel.set(level, [...(byLevel.get(level) ?? []), id]);
    });
    const tallest = Math.max(1, ...[...byLevel.values()].map(ids => ids.length));
    const nodes: SkillFlowNode[] = [];
    byLevel.forEach((ids, level) => {
        /* Within a level the order is the recorded one; the column is only shifted as a block. */
        const ordered = [...ids].sort((a, b) => (topology.order.get(a) ?? 0) - (topology.order.get(b) ?? 0));
        const offset = (tallest - ordered.length) * (NODE_HEIGHT + GAP_Y) / 2;
        ordered.forEach((id, index) => {
            const node = topology.nodes.get(id)!;
            nodes.push({
                id, type: 'skill', position: { x: level * (NODE_WIDTH + GAP_X), y: offset + index * (NODE_HEIGHT + GAP_Y) },
                style: { width: NODE_WIDTH, height: NODE_HEIGHT },
                data: { label: node.name, id: node.id, kind: node.kind, shared: topology.parentCount.get(node.id) ?? 0,
                    order: ids.length > 1 ? (topology.order.get(node.id) ?? null) : null, dim: false, emphasis: false },
            });
        });
    });
    return nodes;
}

function Canvas({ topology }: { topology: Topology }) {
    const { resolved } = useAppearance();
    const seeded = useMemo(() => buildNodes(topology), [topology]);
    const [nodes, setNodes, onNodesChange] = useNodesState<SkillFlowNode>(seeded);
    const [selected, setSelected] = useState('');
    const [documentId, setDocumentId] = useState('');
    const [document, setDocument] = useState<{ content: string; path: string } | null>(null);
    const [documentError, setDocumentError] = useState('');
    const [history, setHistory] = useState<{ path: string; hash: string }[]>([]);
    const location = history.at(-1);
    const article = useRef<HTMLElement>(null);
    const openDocument = () => {
        setHistory([{ path: '', hash: '' }]);
        setDocumentId(selected);
    };
    const follow = (href: string) => {
        if (!document) return;
        try {
            const base = new URL(document.path, 'https://local-doc.invalid/');
            const target = new URL(href, base);
            if (target.origin !== base.origin) return;
            setHistory(current => [...current, { path: decodeURIComponent(target.pathname.slice(1)), hash: decodeURIComponent(target.hash.slice(1)) }]);
        } catch { setDocumentError('文档链接格式无效'); }
    };
    useEffect(() => {
        if (!document || !article.current) return;
        article.current.scrollTop = 0;
        if (location?.hash) {
            const target = [...article.current.querySelectorAll('[id]')].find(element => element.id === location.hash);
            target?.scrollIntoView({ block: 'start' });
        }
    }, [document, location]);
    useEffect(() => {
        setDocumentId('');
    }, [topology]);
    useEffect(() => {
        setDocument(null); setDocumentError('');
        if (!documentId) return;
        const controller = new AbortController();
        api.skillDocument(documentId, controller.signal, location?.path).then(value => {
            if (!controller.signal.aborted) setDocument(value);
        }).catch(error => {
            if (!controller.signal.aborted) setDocumentError(String(error.message ?? error));
        });
        return () => controller.abort();
    }, [documentId, location?.path]);
    useEffect(() => { setNodes(seeded); setSelected(''); }, [seeded, setNodes]);
    /* Selecting a node marks it and its direct relations, which is how a shared skill shows its owners. */
    const related = useMemo(() => {
        if (!selected)
            return new Set<string>();
        const ids = new Set([selected]);
        topology.edges.forEach(edge => {
            if (edge.from === selected)
                ids.add(edge.to);
            if (edge.to === selected)
                ids.add(edge.from);
        });
        return ids;
    }, [selected, topology.edges]);
    const usage = useMemo(() => {
        const result = new Map<string, string>();
        if (topology.nodes.get(selected)?.kind !== 'formal-role') return result;
        topology.edges.filter(edge => edge.from === selected && edge.relation === 'uses-skill').forEach(edge => {
            result.set(edge.to, edge.mode === 'default' ? '默认使用' : edge.mode === 'conditional' ? '条件触发' : edge.mode || '方式未记录');
        });
        return result;
    }, [selected, topology]);
    const display = useMemo(() => nodes.map(node => ({ ...node, data: { ...node.data,
        usage: usage.get(node.id), emphasis: related.has(node.id), dim: related.size > 0 && !related.has(node.id) } })), [nodes, related, usage]);
    const edges: Edge[] = useMemo(() => topology.edges.map((edge, index) => {
        const highlighted = edge.from === selected || edge.to === selected;
        const color = highlighted ? 'var(--accent)' : EDGE_COLOR;
        return {
            id: `${edge.from}->${edge.to}:${index}`, source: edge.from, target: edge.to,
            type: 'smoothstep', deletable: false, reconnectable: false, selectable: false, focusable: false,
            // 折线会共用线段；将高亮线置于上层，避免后绘制的灰线遮住其中一段。
            zIndex: highlighted ? 1 : 0,
            markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color },
            style: { stroke: color, strokeWidth: highlighted ? 2 : 1.5 },
        };
    }), [topology.edges, selected]);
    const counts = useMemo(() => {
        const byLevel = new Map<number, number>();
        topology.nodes.forEach((_, id) => {
            const level = topology.level.get(id);
            if (level !== undefined)
                byLevel.set(level, (byLevel.get(level) ?? 0) + 1);
        });
        return [...byLevel].sort((a, b) => a[0] - b[0]);
    }, [topology]);
    return <div className="topology-graph">
      <div className="graph-toolbar"><div className="graph-actions">
        <Button size="small" disabled={!selected} onClick={() => setSelected('')}>清除选中</Button>
      </div><Typography.Text type="secondary" className="graph-summary">
        第 0 层入口 → {counts.slice(1).map(([level, count]) => `第 ${level} 层 ${count} 个`).join(' · ')}；共 {topology.nodes.size} 个节点、{topology.edges.length} 条关系
      </Typography.Text>
        <Button size="small" disabled={!selected} title={selected ? '查看选中节点的设定文档' : '请先选择一个节点'} onClick={openDocument}>查看设定</Button>
      </div>
      <Modal title={`${topology.nodes.get(documentId)?.name ?? ''} · 设定详情`} open={!!documentId} onCancel={() => setDocumentId('')} footer={null} width={900}>
        <Button size="small" disabled={history.length < 2} onClick={() => setHistory(current => current.slice(0, -1))}>返回上一篇</Button>
        <Typography.Paragraph type="secondary">{document?.path || location?.path}</Typography.Paragraph>
        {documentError ? <Alert type="error" showIcon title="设定读取失败" description={documentError}/> : !document ? <Spin description="正在读取设定…"/> : <>
          <article ref={article} className="skill-markdown"><Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSlug]} skipHtml components={{
            a: ({ children, href }) => href && /^(https?:|mailto:)/i.test(href) ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> : href && !/^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(href) ? <a href={href} onClick={event => { event.preventDefault(); follow(href); }}>{children}</a> : <span title={href}>{children}</span>,
            img: ({ alt }) => <span>{alt ? `[图片：${alt}]` : '[图片]'}</span>,
          }}>{document.content.replace(/^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/, '')}</Markdown></article>
        </>}
      </Modal>
      <div className="graph-canvas">
        <ReactFlow<SkillFlowNode, Edge> colorMode={resolved} nodes={display} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange}
          onNodeClick={(_, node) => setSelected(current => current === node.id ? '' : node.id)}
          fitView fitViewOptions={{ padding: .12, maxZoom: 1 }} minZoom={.15} maxZoom={2}
          nodesConnectable={false} edgesReconnectable={false} deleteKeyCode={null} edgesFocusable={false}
          selectionOnDrag={false} multiSelectionKeyCode={null} onBeforeDelete={async () => false} attributionPosition="bottom-left">
          <Background gap={20} size={1}/>
        </ReactFlow>
      </div>
      <p className="graph-legend">箭头＝关系方向：<strong>路由</strong>（入口 → 领域 Agent）、<strong>拥有</strong>（领域 Agent → 正式角色）、<strong>使用</strong>（角色 / Agent → 能力 SKILL）。节点内序号＝该层内的记录顺序；数据里没有独立的顺序字段，顺序按连线次序呈现，因此不做排序。带 ×N 的节点被 N 处引用，点它可突出直接关联节点与蓝色连线，其他连线保持浅灰。</p>
    </div>;
}

export function SkillTopologyGraph({ topology }: { topology: Topology }) {
    return <ReactFlowProvider><Canvas topology={topology}/></ReactFlowProvider>;
}
