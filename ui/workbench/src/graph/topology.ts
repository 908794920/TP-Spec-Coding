import { record, records, text } from '../facts';
import type { FactRecord } from '../types';

export const KIND_LABELS: Record<string, string> = { 'product-entry': '入口', 'domain-agent': '领域 Agent', 'formal-role': '角色', 'capability-skill': 'SKILL' };
export const RELATION_LABELS: Record<string, string> = { 'routes-to': '路由', 'owns-role': '拥有', 'uses-skill': '声明使用', uses: '声明关联' };
export const SKILL_STATUS_LABELS: Record<string, string> = { available: '可读取', disabled: '已停用', missing: '文件缺失', invalid: '无效', unknown: '未记录' };
export const SOURCE_LABELS: Record<string, string> = { builtin: '内置', external: '外部' };
export const TOPOLOGY_NODE_WIDTH = 244, TOPOLOGY_NODE_HEIGHT = 72;

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

/** Geometry only. The rightmost orphan column is not a new topology level or a synthetic owner. */
export function layoutTopology(topology: Topology): TopologyPosition[] {
    const columns = new Map<number, string[]>();
    topology.level.forEach((level, id) => columns.set(level, [...(columns.get(level) ?? []), id]));
    const orphanColumn = Math.max(-1, ...columns.keys()) + 1;
    if (topology.orphans.length) columns.set(orphanColumn, topology.orphans.map(node => node.id));
    const tallest = Math.max(1, ...[...columns.values()].map(ids => ids.length));
    return [...columns].flatMap(([column, ids]) => {
        const offset = (tallest - ids.length) * (TOPOLOGY_NODE_HEIGHT + 12) / 2;
        return ids.map((id, index) => ({
            id, position: { x: column * (TOPOLOGY_NODE_WIDTH + 72), y: offset + index * (TOPOLOGY_NODE_HEIGHT + 12) },
            order: topology.level.has(id) && ids.length > 1 ? topology.order.get(id) ?? null : null,
            detached: !topology.level.has(id),
        }));
    });
}
