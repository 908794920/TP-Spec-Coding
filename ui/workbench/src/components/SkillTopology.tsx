import { useMemo, useRef, useState, type ComponentProps } from 'react';
import { Alert, Button, Input, Select, Space, Table, Tag, Typography } from 'antd';
import { DownOutlined, RightOutlined, SearchOutlined } from '@ant-design/icons';
import { explainValue } from '../facts';
import { EXTERNAL_SKILL_MANAGER, KIND_LABELS, RELATION_LABELS, SKILL_STATUS_LABELS, SOURCE_LABELS, readTopology, type TopoEdge, type TopoNode, type Topology } from '../graph/topology';
import { SkillDocument } from './SkillDocument';

interface SkillRow {
    key: string;
    node: TopoNode;
    edge?: TopoEdge;
    children?: SkillRow[];
}

function skillRows(topology: Topology): SkillRow[] {
    function branch(node: TopoNode, key: string, ancestors: ReadonlySet<string>, edge?: TopoEdge): SkillRow {
        const path = new Set(ancestors).add(node.id);
        const declared = topology.children.get(node.id) ?? [];
        const links = node.id === EXTERNAL_SKILL_MANAGER ? [...declared, ...topology.managementEdges] : declared;
        const children = links.flatMap((link, index) => {
            const child = topology.nodes.get(link.to);
            if (!child || path.has(child.id)) return [];
            return [branch(child, `${key}/${index}:${child.id}`, path, link)];
        });
        return { key, node, edge, children: children.length ? children : undefined };
    }

    return topology.entry.map(node => branch(node, node.id, new Set()));
}

function branchKeys(rows: SkillRow[]): string[] {
    return rows.flatMap(row => row.children ? [row.key, ...branchKeys(row.children)] : []);
}

function SkillTableCell({ className, children, ...props }: ComponentProps<'td'>) {
    const isNameColumn = className?.split(' ').includes('skill-name-column');
    return <td {...props} className={className}>
      {isNameColumn ? <div className="skill-tree-cell">{children}</div> : children}
    </td>;
}

export function SkillTopology({ value, loading = false, readError = '' }: { value: unknown; loading?: boolean; readError?: string }) {
    const topology = useMemo(() => readTopology(value), [value]);
    const [query, setQuery] = useState('');
    const [sourceFilter, setSourceFilter] = useState<'all' | 'builtin' | 'external'>('all');
    const [statusFilter, setStatusFilter] = useState<'all' | 'available' | 'disabled' | 'issue'>('all');
    const [expandedKeys, setExpandedKeys] = useState<string[] | null>(null);
    const [collapsedMatches, setCollapsedMatches] = useState<string[]>([]);
    const [selection, setSelection] = useState<{ id: string; topology: Topology } | null>(null);
    const opener = useRef<HTMLElement | null>(null);

    const blocked = loading || !!readError || !!topology.error;
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

    const rows = useMemo(() => skillRows(topology), [topology]);
    const term = query.trim().toLowerCase();
    const isSearching = !!term || sourceFilter !== 'all' || statusFilter !== 'all';
    const matched = useMemo(() => {
        const matchesNode = (node: TopoNode) => {
            const matchQ = !term || [node.id, node.name, node.description].some(value => value.toLowerCase().includes(term));
            const matchSource = sourceFilter === 'all' || node.sourceKind === sourceFilter;
            const matchStatus = statusFilter === 'all'
                || (statusFilter === 'issue' ? !['available', 'disabled'].includes(node.status) : node.status === statusFilter);
            return matchQ && matchSource && matchStatus;
        };
        function matchingBranches(branches: SkillRow[]): SkillRow[] {
            return branches.flatMap(row => {
                const children = row.children ? matchingBranches(row.children) : [];
                if (!children.length && !matchesNode(row.node)) return [];
                return [{ ...row, children: children.length ? children : undefined }];
            });
        }
        const unassigned = topology.orphans.filter(node => node.sourceKind === 'external' && matchesNode(node));
        return { rows: isSearching ? matchingBranches(rows) : rows, unassigned };
    }, [topology, rows, isSearching, term, sourceFilter, statusFilter]);

    const expandable = useMemo(() => branchKeys(matched.rows), [matched.rows]);
    const effectiveExpanded = isSearching
        ? expandable.filter(key => !collapsedMatches.includes(key))
        : expandedKeys ?? [topology.rootId];
    const allExpanded = expandable.length > 0 && expandable.every(key => effectiveExpanded.includes(key));
    const onExpand = (expanded: boolean, row: SkillRow) => {
        if (isSearching) {
            setCollapsedMatches(old => expanded ? old.filter(key => key !== row.key) : [...old, row.key]);
        } else {
            setExpandedKeys(old => {
                const keys = old ?? [topology.rootId];
                return expanded ? [...new Set([...keys, row.key])] : keys.filter(key => key !== row.key);
            });
        }
    };

    const externalCount = [...topology.nodes.values()].filter(node => node.sourceKind === 'external').length;
    const builtinCount = [...topology.nodes.values()].filter(node => node.sourceKind === 'builtin').length;
    const externalManager = topology.nodes.get(EXTERNAL_SKILL_MANAGER);
    const { unassigned } = matched;

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
        <p>外部目录：<code>{topology.external.root || '未提供'}</code> · 可选配置：<code>{topology.external.configPath || '未提供'}</code></p>
        <p>来源读取：{({ empty: '未发现外部能力', available: '已发现', partial: '部分条目存在问题', invalid: '外部来源异常' } as Record<string, string>)[topology.external.status] || topology.external.status || '未记录'}。
          {externalManager && <Button size="small" type="link" disabled={blocked} onClick={() => openDocument(externalManager.id)}>查看自定义 SKILL 管理说明</Button>}
        </p>
      </div>

      {!!topology.problems.length && <Alert className="skill-source-problems" type="warning" showIcon title="外部能力来源存在问题" description={<ul>{topology.problems.map((problem, index) => <li key={index}>
        <code>{problem.code}</code>：{problem.message}
        {problem.nodeId && <span> · {problem.nodeId}</span>}
        {topology.nodes.has(problem.nodeId) && <Button type="link" size="small" disabled={blocked} onClick={() => openDocument(problem.nodeId)}>查看来源</Button>}
      </li>)}</ul>}/>}

      <div className="skill-table-toolbar">
        <Input allowClear prefix={<SearchOutlined/>} placeholder="搜索能力名称、稳定 ID 或用途…" value={query} onChange={e => { setQuery(e.target.value); setCollapsedMatches([]); }} style={{ maxWidth: 320 }}/>
        <Select value={sourceFilter} onChange={value => { setSourceFilter(value); setCollapsedMatches([]); }} options={[{ value: 'all', label: '来源：全部' }, { value: 'builtin', label: '来源：内置' }, { value: 'external', label: '来源：外部' }]} style={{ width: 136 }}/>
        <Select value={statusFilter} onChange={value => { setStatusFilter(value); setCollapsedMatches([]); }} options={[{ value: 'all', label: '状态：全部' }, { value: 'available', label: '状态：可读取' }, { value: 'disabled', label: '状态：已停用' }, { value: 'issue', label: '状态：异常/缺失' }]} style={{ width: 148 }}/>
        {!isSearching && expandable.length > 0 && <Button size="small" onClick={() => setExpandedKeys(allExpanded ? [] : expandable)}>{allExpanded ? '全部收起' : '全部展开'}</Button>}
      </div>

      <Table<SkillRow>
        className="skill-hierarchy-table"
        size="small"
        rowKey="key"
        dataSource={matched.rows}
        components={{ body: { cell: SkillTableCell } }}
        scroll={{ x: 640 }}
        pagination={false}
        expandable={{
          expandedRowKeys: effectiveExpanded,
          onExpand,
          indentSize: 20,
          expandIcon: ({ expanded, onExpand: toggle, record: row }) => row.children?.length
            ? <Button size="small" type="text" icon={expanded ? <DownOutlined/> : <RightOutlined/>}
                aria-expanded={expanded} aria-label={expanded ? `收起 ${row.node.name}` : `展开 ${row.node.name}`} onClick={e => toggle(row, e)}/>
            : <span className="skill-expand-spacer"/>,
        }}
        columns={[
          { title: '节点 / 角色名称', className: 'skill-name-column', render: (_, row) => <div className="skill-tree-name">
            <strong>{row.node.name}</strong>
            <Tag variant="filled">{KIND_LABELS[row.node.kind] ?? row.node.kind}</Tag>
            {row.edge && <Tag color={row.edge.relation === 'management-group' ? 'default' : 'blue'}
                title={explainValue('mode', row.edge.mode) || row.edge.mode}>
              {RELATION_LABELS[row.edge.relation] ?? row.edge.relation}
            </Tag>}
            {!!row.children?.length && <span className="muted">({row.children.length} 项下级)</span>}
          </div> },
          { title: '稳定 ID', render: (_, row) => <code>{row.node.id}</code> },
          { title: '来源', width: 64, render: (_, row) => <Tag variant="filled">{SOURCE_LABELS[row.node.sourceKind] ?? row.node.sourceKind}</Tag> },
          { title: '状态', width: 76, className: 'skill-table-status', render: (_, row) => <span className="skill-source-status" data-status={row.node.status}>{SKILL_STATUS_LABELS[row.node.status] ?? row.node.status}</span> },
          { title: '操作', width: 96, render: (_, row) => <Button size="small" type="link" disabled={blocked} onClick={() => openDocument(row.node.id)}>查看设定</Button> },
        ]}
      />

      {!!unassigned.length && <section className="skill-orphans" aria-label="未归属外部能力">
        <h3>未归属外部能力 · {unassigned.length}</h3>
        <div className="skill-child-table-wrap">
          {unassigned.map(node => <div className="skill-child-row" key={node.id}>
            <div className="skill-child-name"><strong>{node.name}</strong><Tag variant="filled">{SOURCE_LABELS[node.sourceKind] ?? node.sourceKind}</Tag></div>
            <code className="skill-child-id">{node.id}</code>
            <span className="skill-source-status" data-status={node.status}>{SKILL_STATUS_LABELS[node.status] ?? node.status}</span>
            <Button size="small" type="link" disabled={blocked} onClick={() => openDocument(node.id)}>查看设定</Button>
          </div>)}
        </div>
      </section>}

      {selectedNode && <SkillDocument key={selectedNode.id} node={selectedNode} onClose={closeDocument}/>}
    </>;
}
