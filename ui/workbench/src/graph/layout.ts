import type { GraphModel } from './model';
export const NODE_WIDTH = 236, NODE_HEIGHT = 116;
export interface Point {
    x: number;
    y: number;
}
export interface Layout {
    positions: Record<string, Point>;
    group: {
        x: number;
        y: number;
        width: number;
        height: number;
    };
}
/** One deterministic layered layout. Cycles remain visible in an explicitly diagnosed final column. */
export function layoutGraph(model: GraphModel): Layout {
    const items = model.nodes.filter(n => n.kind === 'work_item' && n.belongs);
    const ids = new Set(items.map(n => n.id));
    const indegree = new Map(items.map(n => [n.id, 0])), rank = new Map(items.map(n => [n.id, 0]));
    const outgoing = new Map(items.map(n => [n.id, [] as string[]]));
    for (const edge of model.edges)
        if (ids.has(edge.source) && ids.has(edge.target)) {
            indegree.set(edge.target, indegree.get(edge.target)! + 1);
            outgoing.get(edge.source)!.push(edge.target);
        }
    const pending = items.filter(n => indegree.get(n.id) === 0).map(n => n.id).sort();
    const visited = new Set<string>();
    while (pending.length) {
        const id = pending.shift()!;
        visited.add(id);
        for (const next of outgoing.get(id)!) {
            rank.set(next, Math.max(rank.get(next)!, rank.get(id)! + 1));
            indegree.set(next, indegree.get(next)! - 1);
            if (indegree.get(next) === 0) {
                pending.push(next);
                pending.sort();
            }
        }
    }
    const maxRank = Math.max(0, ...[...visited].map(id => rank.get(id)!));
    for (const item of items)
        if (!visited.has(item.id))
            rank.set(item.id, maxRank + 1);
    const positions: Record<string, Point> = { [model.taskNodeId]: { x: 32, y: 0 } };
    const rows = new Map<number, number>();
    for (const item of items) {
        const column = rank.get(item.id)!, row = rows.get(column) ?? 0;
        rows.set(column, row + 1);
        positions[item.id] = { x: 24 + column * (NODE_WIDTH + 88), y: 62 + row * (NODE_HEIGHT + 36) };
    }
    const group = {
        x: 0, y: 170, width: Math.max(440, 48 + (Math.max(0, ...rank.values()) + 1) * (NODE_WIDTH + 88) - 88),
        height: Math.max(112, 86 + Math.max(0, ...rows.values()) * (NODE_HEIGHT + 36) - 36)
    };
    let ungrouped = 0;
    for (const item of model.nodes.filter(n => n.kind === 'work_item' && !n.belongs)) {
        positions[item.id] = { x: 32 + ungrouped * (NODE_WIDTH + 36), y: group.y + group.height + 70 };
        ungrouped++;
    }
    return { positions, group };
}
