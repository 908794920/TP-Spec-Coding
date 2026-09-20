import { record, records, text } from '../facts';
import type { FactRecord } from '../types';

/* The skill topology as the page reads it. Two of these fields are derived, and only because the
   payload states neither: `level` is the distance from `root_id`, and `order` is the position inside
   that level. The payload carries NO sequence field at all — checked on every node and every edge:
   order / seq / index / rank / position / step / phase are all absent — so the sequence can only be
   the order the edges arrive in, and both views render it as received rather than sorting. */
export interface TopoNode {
    id: string;
    name: string;
    kind: string;
    path: string;
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
}

function readNode(nodes: FactRecord, id: string): TopoNode {
    const node = record(nodes[id]);
    return { id, name: text(node.name) || id, kind: text(node.kind), path: text(node.path) };
}

export function readTopology(value: unknown): Topology {
    const source = record(value);
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
    /* Breadth-first from the entry: a node is placed at the first level it is reached at and keeps
       that level however many parents point at it. Visiting each node once also makes a cycle in the
       data impossible to loop over. */
    const level = new Map<string, number>(), order = new Map<string, number>(), placed = new Map<number, number>();
    const queue: string[] = [];
    const place = (id: string, depth: number) => {
        level.set(id, depth);
        placed.set(depth, (placed.get(depth) ?? 0) + 1);
        order.set(id, placed.get(depth)!);
        queue.push(id);
    };
    if (nodes.has(rootId))
        place(rootId, 0);
    for (let head = 0; head < queue.length; head += 1) {
        const id = queue[head];
        (children.get(id) ?? []).forEach(edge => {
            if (!level.has(edge.to))
                place(edge.to, level.get(id)! + 1);
        });
    }
    const kinds = new Map<string, number>(), relations = new Map<string, number>();
    nodes.forEach(node => kinds.set(node.kind, (kinds.get(node.kind) ?? 0) + 1));
    edges.forEach(edge => relations.set(edge.relation, (relations.get(edge.relation) ?? 0) + 1));
    return {
        rootId, nodes, edges, children, parentCount, level, order,
        entry: nodes.has(rootId) ? [nodes.get(rootId)!] : [],
        /* Anything the entry cannot reach is listed instead of disappearing. */
        orphans: [...nodes.values()].filter(node => !level.has(node.id)),
        kinds: [...kinds].sort((a, b) => b[1] - a[1]),
        relations: [...relations].sort((a, b) => b[1] - a[1]),
    };
}
