import { useMemo, useRef, useState, type ReactNode } from 'react';
import { Alert, Button, Space, Tag, Typography } from 'antd';
import { explainValue } from '../facts';
import { KIND_LABELS, RELATION_LABELS, SKILL_STATUS_LABELS, SOURCE_LABELS, readTopology, topologyDisplayEdges, type TopoEdge, type TopoNode, type Topology } from '../graph/topology';
import { SkillTopologyGraph } from '../graph/SkillTopologyGraph';
import { SkillDocument } from './SkillDocument';

interface ViewProps { topology: Topology; onOpenDocument: (id: string) => void; disabled: boolean }
/* 内置共享能力按声明父节点展开，外部包仅在管理分组中出现一次。
   循环检测限于当前路径，避免丢掉合法的内置共享分支。 */
function TopologyTree({ topology, onOpenDocument, disabled }: ViewProps) {
    const displayEdges = topologyDisplayEdges(topology);
    const children = new Map<string, TopoEdge[]>();
    displayEdges.forEach(edge => children.set(edge.from, [...(children.get(edge.from) ?? []), edge]));
    const grouped = new Set(displayEdges.filter(edge => edge.relation === 'management-group').map(edge => edge.to));
    function row(node: TopoNode, edge?: TopoEdge) {
        const shared = topology.parentCount.get(node.id) ?? 0;
        return <div className="skill-node" title={[node.id, node.sourceRoot, node.path].filter(Boolean).join(' · ')}>
          {edge && <><span className="skill-order">{topology.order.get(node.id)}</span>
            <span className="skill-relation" title={edge.relation}>{RELATION_LABELS[edge.relation] ?? edge.relation}</span></>}
          <Typography.Text strong>{node.name}</Typography.Text>
          <Typography.Text type="secondary" className="skill-id">{node.id}</Typography.Text>
          <Tag variant="filled" title={explainValue('kind', node.kind) || node.kind}>{KIND_LABELS[node.kind] ?? node.kind}</Tag>
          <Tag variant="filled">{SOURCE_LABELS[node.sourceKind] ?? node.sourceKind}</Tag>
          <span className="skill-source-status" data-status={node.status}>{SKILL_STATUS_LABELS[node.status] ?? node.status}</span>
          {grouped.has(node.id) && !topology.level.has(node.id) && <span>未关联</span>}
          {!!edge?.mode && <Typography.Text type="secondary" className="skill-mode">{edge.mode === 'declared' ? '已声明' : explainValue('mode', edge.mode) || edge.mode}</Typography.Text>}
          {shared > 1 && <Typography.Text type="secondary" className="skill-shared" title="目录声明的引用关系数量，非调用次数">共用 ×{shared}</Typography.Text>}
          <Button size="small" type="link" disabled={disabled} aria-label={`查看 ${node.name} 的设定（${node.id}）`} onClick={() => onOpenDocument(node.id)}>查看设定</Button>
        </div>;
    }
    function renderChildren(id: string, ancestors: Set<string>): ReactNode {
        const list = children.get(id) ?? [];
        if (!list.length) return null;
        const visited = new Set(ancestors).add(id);
        return <ul className="skill-children">{list.map((edge, index) => {
            const node = topology.nodes.get(edge.to)!;
            return <li key={`${edge.to}:${index}`}>
              {row(node, edge)}
              {visited.has(edge.to) ? <Typography.Text type="secondary">循环引用，不重复展开。</Typography.Text> : renderChildren(edge.to, visited)}
            </li>;
        })}</ul>;
    }
    const externalOrphans = topology.orphans.filter(node => node.sourceKind === 'external' && !grouped.has(node.id));
    const otherOrphans = topology.orphans.filter(node => node.sourceKind !== 'external');
    return <>
      {!topology.entry.length && <Typography.Text type="secondary">未记录入口节点（root_id={topology.rootId || '未记录'}）。可用节点仍单独列出。</Typography.Text>}
      {!!topology.entry.length && <ul className="skill-tree">{topology.entry.map(node => <li key={node.id}>
        {row(node)}{renderChildren(node.id, new Set())}
      </li>)}</ul>}
      {!!externalOrphans.length && <section className="skill-orphans" aria-label="外部能力（未关联）">
        <h3>外部能力（未关联） · {externalOrphans.length}</h3>
        <Typography.Text type="secondary">不虚构角色或执行连线；可按精确 ID 查看来源与设定。</Typography.Text>
        {externalOrphans.map(node => <div key={node.id}>{row(node)}</div>)}
      </section>}
      {!!otherOrphans.length && <section className="skill-orphans" aria-label="其他未连通节点">
        <h3>其他未连通节点 · {otherOrphans.length}</h3>
        {otherOrphans.map(node => <div key={node.id}>{row(node)}</div>)}
      </section>}
    </>;
}

export function SkillTopology({ value, loading = false, readError = '' }: { value: unknown; loading?: boolean; readError?: string }) {
    const topology = useMemo(() => readTopology(value), [value]);
    const [view, setView] = useState<'graph' | 'tree'>('graph');
    const [selection, setSelection] = useState<{ id: string; topology: Topology } | null>(null);
    const opener = useRef<HTMLElement | null>(null);
    const blocked = loading || !!readError || !!topology.error;
    // Mask old document state in the refresh render itself, not after a late network/effect callback.
    const selectedNode = !blocked && selection && selection.topology === topology ? topology.nodes.get(selection.id) : undefined;
    const openDocument = (id: string) => {
        if (!blocked && topology.nodes.has(id)) {
            opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
            setSelection({ id, topology });
        }
    };
    const closeDocument = () => {
        setSelection(null);
        requestAnimationFrame(() => { if (opener.current?.isConnected) opener.current.focus(); });
    };
    const externalCount = [...topology.nodes.values()].filter(node => node.sourceKind === 'external').length;
    const builtinCount = [...topology.nodes.values()].filter(node => node.sourceKind === 'builtin').length;
    const externalManager = topology.nodes.get('tp-external-skill-management');
    return <>
      {loading && <Alert type="info" showIcon title="正在重新读取能力目录" description="以下为上次目录；刷新完成前不打开旧快照的设定。"/>}
      {readError && <Alert type="warning" showIcon title="能力目录重新读取失败" description="以下为上次成功目录，不代表当前来源状态；请使用页面顶部重新读取。"/>}
      {topology.error && <Alert type="error" showIcon title="能力目录不可用" description={topology.error}/>}
      <Space className="skill-summary" size={10} wrap>
        {topology.kinds.map(([kind, count]) => <Tag key={kind} variant="filled" title={explainValue('kind', kind) || kind}>{KIND_LABELS[kind] ?? kind} · {count}</Tag>)}
        {topology.relations.map(([relation, count]) => <Typography.Text type="secondary" key={relation} title={`${relation}：目录声明，不是实际调用次数`}>
          {RELATION_LABELS[relation] ?? relation} {count}</Typography.Text>)}
        <Typography.Text type="secondary">内置 {builtinCount} · 外部 {externalCount}</Typography.Text>
      </Space>
      <div className="skill-source-location">
        <p>外部目录：<code>{topology.external.root || '未提供'}</code></p>
        <p>可选配置：<code>{topology.external.configPath || '未提供'}</code></p>
        <p>来源读取：{({ empty: '未发现外部能力', available: '已发现', partial: '部分条目存在问题', invalid: '外部来源异常' } as Record<string, string>)[topology.external.status] || topology.external.status || '未记录'}。页面只读，不安装、不启用、不记录采用。</p>
        {externalManager && <p className="skill-management-entry">
          <span>管理入口：统一入口 → 基座维护 →</span>
          <Button size="small" type="link" disabled={blocked} onClick={() => openDocument(externalManager.id)}>查看自定义 SKILL 管理说明</Button>
        </p>}
      </div>
      {!!topology.problems.length && <Alert className="skill-source-problems" type="warning" showIcon title="外部能力来源存在问题" description={<ul>{topology.problems.map((problem, index) => <li key={index}>
        <code>{problem.code}</code>：{problem.message}
        {problem.nodeId && <span> · {problem.nodeId}</span>}
        {topology.nodes.has(problem.nodeId) && <Button type="link" size="small" disabled={blocked} onClick={() => openDocument(problem.nodeId)}>查看来源</Button>}
      </li>)}</ul>}/>}
      <Space className="skill-view-switch" size={8} wrap>
        <Button size="small" aria-pressed={view === 'graph'} onClick={() => setView('graph')}>拓扑图</Button>
        <Button size="small" aria-pressed={view === 'tree'} onClick={() => setView('tree')}>层级树</Button>
        <Typography.Text type="secondary">图与树均将外部 SKILL 展示在自定义管理之下；用途关联见设定。数量均为目录声明，不是实际调用。</Typography.Text>
      </Space>
      {view === 'graph' ? <SkillTopologyGraph topology={topology} onOpenDocument={openDocument} disabled={blocked}/> : <TopologyTree topology={topology} onOpenDocument={openDocument} disabled={blocked}/>}
      {selectedNode && <SkillDocument key={selectedNode.id} node={selectedNode} onClose={closeDocument}/>}
    </>;
}
