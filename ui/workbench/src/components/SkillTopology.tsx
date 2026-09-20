import { useMemo, useState } from 'react';
import { Button, Space, Tag, Typography } from 'antd';
import { explainValue } from '../facts';
import { readTopology, type Topology } from '../graph/topology';
import { SkillTopologyGraph } from '../graph/SkillTopologyGraph';

/* Rows stay short on purpose: kind and relation are two-character badges whose full wording lives in
   the tooltip, so the reader sees shape and order first and detail on demand. */
const KIND_BADGE: Record<string, string> = { 'product-entry': '入口', 'domain-agent': '领域 Agent', 'formal-role': '角色', 'capability-skill': 'SKILL' };
const RELATION_BADGE: Record<string, string> = { 'routes-to': '路由', 'owns-role': '拥有', 'uses-skill': '使用' };
const kindBadge = (kind: string) => <Tag variant="filled" title={explainValue('kind', kind) || kind}>{KIND_BADGE[kind] ?? kind}</Tag>;

/* The outline view of the same topology: one row per relation, indented by level, in the recorded
   order. Shared skills repeat under each owner here (the graph shows them once) and say so. */
function TopologyTree({ topology }: { topology: Topology }) {
    const depth = (id: string) => topology.level.get(id) ?? 0;
    function renderChildren(id: string): React.ReactNode {
        const list = topology.children.get(id) ?? [];
        const rows = list.filter(edge => depth(edge.to) > depth(id));
        if (!rows.length)
            return null;
        return <ul className="skill-children">{rows.map((edge, index) => {
            const node = topology.nodes.get(edge.to)!;
            const shared = topology.parentCount.get(edge.to) ?? 0;
            return <li key={`${edge.to}:${index}`}>
              <div className="skill-node" title={[node.id, node.path].filter(Boolean).join(' · ')}>
                <span className="skill-order">{topology.order.get(edge.to) ?? index + 1}</span>
                <span className="skill-relation" title={explainValue('relation', edge.relation) || edge.relation}>{RELATION_BADGE[edge.relation] ?? edge.relation}</span>
                <Typography.Text strong>{node.name}</Typography.Text>
                {node.name !== node.id && <Typography.Text type="secondary" className="skill-id">{node.id}</Typography.Text>}
                {kindBadge(node.kind)}
                {!!edge.mode && <Typography.Text type="secondary" className="skill-mode">{explainValue('mode', edge.mode) || edge.mode}</Typography.Text>}
                {shared > 1 && <Typography.Text type="secondary" className="skill-shared" title={`该 SKILL 由 ${shared} 处引用，会在各自父节点下重复出现`}>共用 ×{shared}</Typography.Text>}
              </div>
              {renderChildren(edge.to)}
            </li>;
        })}</ul>;
    }
    return <>
      {!topology.entry.length && <Typography.Text type="secondary">未记录入口节点（root_id={topology.rootId || '未记录'}），无法按层级展示。</Typography.Text>}
      {!!topology.entry.length && <ul className="skill-tree">{topology.entry.map(node => <li key={node.id}>
        <div className="skill-node" title={[node.id, node.path].filter(Boolean).join(' · ')}>
          <Typography.Text strong>{node.name}</Typography.Text>
          {node.name !== node.id && <Typography.Text type="secondary" className="skill-id">{node.id}</Typography.Text>}
          {kindBadge(node.kind)}</div>
        {renderChildren(node.id)}
      </li>)}</ul>}
      {!!topology.orphans.length && <div className="skill-orphans">
        <Typography.Text type="secondary">以下 {topology.orphans.length} 个节点无法从入口到达，单独列出：</Typography.Text>
        {topology.orphans.map(node => <div className="skill-node" key={node.id} title={node.path}>
          <Typography.Text>{node.name}</Typography.Text>{kindBadge(node.kind)}</div>)}
      </div>}
    </>;
}

export function SkillTopology({ value }: { value: unknown }) {
    /* Memoised on the payload: the graph re-seeds its node positions from this object, so a new one
       on every render would undo a drag. */
    const topology = useMemo(() => readTopology(value), [value]);
    const [view, setView] = useState<'graph' | 'tree'>('graph');
    /* No raw payload block and no identity block: both views below are readings of the same data, and
       a second copy of it as nested JSON was only a longer way to say the same thing. */
    return <>
      <Space className="skill-summary" size={10} wrap>
        {topology.kinds.map(([kind, count]) => <Tag key={kind} variant="filled" title={explainValue('kind', kind) || kind}>{KIND_BADGE[kind] ?? kind} · {count}</Tag>)}
        {topology.relations.map(([relation, count]) => <Typography.Text type="secondary" key={relation}
          title={explainValue('relation', relation) || relation}>{RELATION_BADGE[relation] ?? relation} {count}</Typography.Text>)}
      </Space>
      <Space className="skill-view-switch" size={8} wrap>
        <Button size="small" aria-pressed={view === 'graph'} onClick={() => setView('graph')}>拓扑图</Button>
        <Button size="small" aria-pressed={view === 'tree'} onClick={() => setView('tree')}>层级树</Button>
        <Typography.Text type="secondary">两种视图读的是同一份数据：图便于看共用与扇入，树便于看逐层展开的完整顺序。</Typography.Text>
      </Space>
      {view === 'graph' ? <SkillTopologyGraph topology={topology}/> : <TopologyTree topology={topology}/>}
    </>;
}
