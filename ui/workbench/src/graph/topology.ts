import { record, records, text } from '../facts';
import type { FactRecord } from '../types';

export const KIND_LABELS: Record<string, string> = { 'product-entry': '入口', 'domain-agent': '领域 Agent', 'formal-role': '角色', 'capability-skill': 'SKILL' };
export const RELATION_LABELS: Record<string, string> = { 'routes-to': '路由', 'owns-role': '拥有', 'uses-skill': '声明使用', uses: '声明关联', 'management-group': '管理分组' };
export const SKILL_STATUS_LABELS: Record<string, string> = { available: '可读取', disabled: '已停用', missing: '文件缺失', invalid: '无效', unknown: '未记录' };
export const SOURCE_LABELS: Record<string, string> = { builtin: '内置', external: '外部' };
export const TOPOLOGY_NODE_WIDTH = 244, TOPOLOGY_NODE_HEIGHT = 72;
export const TOPOLOGY_COLUMN_KINDS = ['product-entry', 'domain-agent', 'formal-role', 'capability-skill'] as const;

/* Level/order describe the recorded edges, not execution. External packages retain their own
   identity and metadata; unconnected packages never acquire a fabricated owner or level. */
export interface TopoNode {
    id: string;
    name: string;
    kind: string;
    path: string;
    sourceKind: string;
    sourceRoot: string;
    status: string;
    enabled?: boolean;
    reason: string;
    description: string;
    upstream: string;
    version: string;
    entrySha256: string;
    appliesTo: string[];
    autoSelectable: boolean;
}
export interface TopoEdge {
    from: string;
    to: string;
    relation: string;
    mode: string;
}
export interface Topology {
    rootId: string;
    nodes: Map<string, TopoNode>;
    edges: TopoEdge[];
    children: Map<string, TopoEdge[]>;
    parentCount: Map<string, number>;
    level: Map<string, number>;
    order: Map<string, number>;
    entry: TopoNode[];
    orphans: TopoNode[];
    kinds: [string, number][];
    relations: [string, number][];
    status: string;
    error: string;
    external: { root: string; configPath: string; status: string };
    problems: { code: string; message: string; nodeId: string }[];
}

function readNode(nodes: FactRecord, id: string): TopoNode {
    const node = record(nodes[id]);
    return {
        id, name: text(node.name) || id, kind: text(node.kind), path: text(node.path),
        sourceKind: text(node.source_kind) || (id.startsWith('external:local:') ? 'external' : 'builtin'),
        sourceRoot: text(node.source_root), status: text(node.status) || 'unknown',
        enabled: typeof node.enabled === 'boolean' ? node.enabled : undefined,
        reason: text(node.reason), description: text(node.description), upstream: text(node.upstream),
        version: text(node.version), entrySha256: text(node.entry_sha256),
        appliesTo: Array.isArray(node.applies_to) ? node.applies_to.filter((v): v is string => typeof v === 'string') : [],
        autoSelectable: node.auto_selectable === true,
    };
}

export function readTopology(value: unknown): Topology {
    const source = record(value), external = record(source.external);
    const raw = record(source.nodes);
    const nodes = new Map(Object.keys(raw).map(id => [id, readNode(raw, id)]));
    const edges: TopoEdge[] = records(source.edges).map(edge => ({
        from: text(edge.from), to: text(edge.to), relation: text(edge.relation), mode: text(edge.mode),
    })).filter(edge => nodes.has(edge.from) && nodes.has(edge.to));
    const children = new Map<string, TopoEdge[]>(), parentCount = new Map<string, number>();
    edges.forEach(edge => {
        children.set(edge.from, [...(children.get(edge.from) ?? []), edge]);
        parentCount.set(edge.to, (parentCount.get(edge.to) ?? 0) + 1);
    });
    const rootId = text(source.root_id);
    // First breadth-first visit fixes the recorded level, even for shared nodes or cyclic input.
    const level = new Map<string, number>(), order = new Map<string, number>(), placed = new Map<number, number>();
    const queue: string[] = [];
    const place = (id: string, depth: number) => {
        level.set(id, depth);
        placed.set(depth, (placed.get(depth) ?? 0) + 1);
        order.set(id, placed.get(depth)!);
        queue.push(id);
    };
    if (nodes.has(rootId)) place(rootId, 0);
    for (let head = 0; head < queue.length; head += 1) {
        const id = queue[head];
        (children.get(id) ?? []).forEach(edge => {
            if (!level.has(edge.to)) place(edge.to, level.get(id)! + 1);
        });
    }
    const kinds = new Map<string, number>(), relations = new Map<string, number>();
    nodes.forEach(node => kinds.set(node.kind, (kinds.get(node.kind) ?? 0) + 1));
    edges.forEach(edge => relations.set(edge.relation, (relations.get(edge.relation) ?? 0) + 1));
    return {
        rootId, nodes, edges, children, parentCount, level, order,
        entry: nodes.has(rootId) ? [nodes.get(rootId)!] : [],
        orphans: [...nodes.values()].filter(node => !level.has(node.id)),
        kinds: [...kinds].sort((a, b) => b[1] - a[1]),
        relations: [...relations].sort((a, b) => b[1] - a[1]),
        status: text(source.status), error: text(source.error),
        external: { root: text(external.root), configPath: text(external.config_path), status: text(external.status) },
        problems: records(source.problems).map(p => ({ code: text(p.code), message: text(p.message), nodeId: text(p.node_id) })),
    };
}

export interface TopologyPosition {
    id: string;
    position: { x: number; y: number };
    order: number | null;
    detached: boolean;
}

/** 只生成展示分组，原始用途关联、计数和读取来源保持不变。 */
export function topologyDisplayEdges(topology: Topology): TopoEdge[] {
    const manager = topology.nodes.get('tp-external-skill-management');
    if (manager?.sourceKind !== 'builtin' || manager.kind !== 'capability-skill' || !topology.level.has(manager.id)) return topology.edges;
    const external = [...topology.nodes.values()].filter(node => node.sourceKind === 'external');
    return [...topology.edges.filter(edge => topology.nodes.get(edge.to)?.sourceKind !== 'external'),
        ...external.map(node => ({ from: manager.id, to: node.id, relation: 'management-group', mode: '' }))];
}

/** 仅计算位置；外部方法包沿管理入口继续展开，不按用途关联分散放置。 */
export function layoutTopology(topology: Topology): TopologyPosition[] {
    const grouped = topologyDisplayEdges(topology).filter(edge => edge.relation === 'management-group');
    const managerId = grouped[0]?.from;
    const externalIds = new Set(grouped.map(edge => edge.to));
    const span = (id: string) => id === managerId ? Math.max(1, grouped.length) : 1;
    const leftDomains = [...new Set((topology.children.get(topology.rootId) ?? [])
        .filter(edge => edge.relation === 'routes-to' && topology.nodes.get(edge.to)?.kind === 'domain-agent')
        .map(edge => edge.to))].filter(id => (topology.children.get(id) ?? [])
            .every(edge => topology.nodes.get(edge.to)?.kind === 'capability-skill'));
    const leftDomainSet = new Set(leftDomains);
    const parents = new Map<string, string[]>();
    topology.edges.forEach(edge => parents.set(edge.to, [...(parents.get(edge.to) ?? []), edge.from]));
    // A shared capability stays on the right if any user is outside the shallow branches.
    // Its identity and incoming relationships are never duplicated to suit the layout.
    const leftSkills = new Set([...topology.nodes.values()].filter(node => node.kind === 'capability-skill' && !externalIds.has(node.id)
        && !!parents.get(node.id)?.length && parents.get(node.id)!.every(id => leftDomainSet.has(id))).map(node => node.id));
    const allocated = new Set<string>();
    const groups = leftDomains.map(id => {
        const skills: string[] = [];
        (topology.children.get(id) ?? []).forEach(edge => {
            if (leftSkills.has(edge.to) && !allocated.has(edge.to)) {
                allocated.add(edge.to);
                skills.push(edge.to);
            }
        });
        return { id, skills, height: Math.max(1, skills.reduce((sum, skill) => sum + span(skill), 0)) };
    });
    const columns = new Map<number, string[]>();
    const levelCounts = new Map<number, number>();
    topology.level.forEach(level => levelCounts.set(level, (levelCounts.get(level) ?? 0) + 1));
    const place = (id: string) => {
        if (leftDomainSet.has(id) || leftSkills.has(id) || externalIds.has(id)) return;
        const column = TOPOLOGY_COLUMN_KINDS.findIndex(kind => kind === topology.nodes.get(id)?.kind);
        const index = column < 0 ? TOPOLOGY_COLUMN_KINDS.length : column;
        columns.set(index, [...(columns.get(index) ?? []), id]);
    };
    topology.level.forEach((_, id) => place(id));
    topology.orphans.forEach(node => place(node.id));
    const leftHeight = groups.reduce((sum, group) => sum + group.height, 0) + Math.max(0, groups.length - 1) * .5;
    const height = (ids: string[]) => ids.reduce((sum, id) => sum + span(id), 0);
    const tallest = Math.max(1, leftHeight, ...[...columns.values()].map(height));
    const position = (id: string, column: number, row: number): TopologyPosition => ({
        id, position: { x: column * (TOPOLOGY_NODE_WIDTH + 72), y: row * (TOPOLOGY_NODE_HEIGHT + 12) },
        order: topology.level.has(id) && (levelCounts.get(topology.level.get(id)!) ?? 0) > 1 ? topology.order.get(id) ?? null : null,
        detached: !topology.level.has(id),
    });
    let row = (tallest - leftHeight) / 2;
    const left = groups.flatMap(group => {
        const start = row;
        const result = [position(group.id, -1, row + (group.height - 1) / 2), ...group.skills.map(id => {
            const item = position(id, -2, row + (span(id) - 1) / 2);
            row += span(id);
            return item;
        })];
        row = start + group.height + .5;
        return result;
    });
    const positions = [...left, ...[...columns].sort((a, b) => a[0] - b[0]).flatMap(([column, ids]) => {
        let offset = (tallest - height(ids)) / 2;
        return ids.map(id => {
            const item = position(id, column, offset + (span(id) - 1) / 2);
            offset += span(id);
            return item;
        });
    })];
    const manager = positions.find(item => item.id === managerId);
    if (manager) {
        const x = manager.position.x < 0 ? Math.min(...positions.map(item => item.position.x)) : Math.max(...positions.map(item => item.position.x));
        const column = x / (TOPOLOGY_NODE_WIDTH + 72) + (manager.position.x < 0 ? -1 : 1);
        const start = manager.position.y / (TOPOLOGY_NODE_HEIGHT + 12) - (grouped.length - 1) / 2;
        positions.push(...grouped.map((edge, index) => position(edge.to, column, start + index)));
    }
    return positions;
}
