import { record, text, valueText } from '../facts';
import type { FactRecord, TaskData } from '../types';
import { buildWorkflowRelations, type WorkflowRelations } from './workflowRelations';
export interface GraphObject {
    id: string;
    objectId: string;
    kind: 'task' | 'work_item';
    title: string;
    status: string;
    owner: string;
    parentTaskId: string;
    belongs: boolean;
    records: FactRecord[];
    issues: string[];
}
export interface Dependency {
    id: string;
    source: string;
    target: string;
    kind: 'dependency';
}
export interface GraphIssue {
    code: string;
    message: string;
    objectIds: string[];
}
export interface GraphModel {
    workflow: WorkflowRelations;
    taskId: string;
    taskNodeId: string;
    groupId: string;
    nodes: GraphObject[];
    edges: Dependency[];
    issues: GraphIssue[];
    invalidRecords: FactRecord[];
    topology: string;
}
const compare = (a: string, b: string) => a < b ? -1 : a > b ? 1 : 0;
const identity = (...parts: string[]) => JSON.stringify(parts);
/** Pure display projection. Only explicit object identity/parent/dependency fields carry relationships. */
export function buildGraph(contextKey: string, data: TaskData): GraphModel {
    const task = record(data.task), taskId = text(task.task_id);
    const taskNodeId = identity(contextKey, taskId, 'task', taskId);
    const groupId = identity(contextKey, taskId, 'work_item_group');
    const issues: GraphIssue[] = [], invalidRecords: FactRecord[] = [];
    const addIssue = (code: string, message: string, objectIds: string[] = []) => issues.push({ code, message, objectIds });
    const nodes: GraphObject[] = [{
            id: taskNodeId, objectId: taskId, kind: 'task', title: text(task.title),
            status: text(task.state), owner: text(task.owner), parentTaskId: '', belongs: false, records: [task], issues: []
        }];
    if (!taskId)
        addIssue('TASK_ID_MISSING', '当前响应没有正式 Task ID，不能解释工作归属。');
    const groups = new Map<string, FactRecord[]>();
    const work = record(data.work_items);
    if (work.source !== 'work_item')
        addIssue('WORK_SOURCE_UNCONFIRMED', '当前响应未确认 WorkItem 来源，不将任意对象解释为工作项。');
    const rawItems = Array.isArray(work.items) ? work.items : [];
    if (!Array.isArray(work.items)) {
        addIssue('WORK_ITEMS_INVALID', '工作项列表未取得或类型异常，不解释为已确认没有工作项。');
        invalidRecords.push({ items: work.items ?? null });
    }
    for (const raw of rawItems) {
        if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
            invalidRecords.push({ raw });
            addIssue('ITEM_RECORD_INVALID', '存在非对象工作记录，保留原值，不生成工作节点。');
            continue;
        }
        const row = record(raw);
        if (work.source !== 'work_item') {
            invalidRecords.push(row);
            continue;
        }
        const id = typeof row.item_id === 'string' && row.item_id.trim() ? row.item_id : '';
        if (!id) {
            invalidRecords.push(row);
            addIssue('ITEM_ID_MISSING', '存在未提供正式 ID 的记录，保留在原始记录区，不生成索引型假 ID。');
            continue;
        }
        const existing = groups.get(id) ?? [];
        groups.set(id, [...existing, row]);
    }
    for (const [id, rows] of [...groups.entries()].sort(([a], [b]) => compare(a, b))) {
        const row = rows[0], duplicate = rows.length > 1;
        const parent = duplicate && new Set(rows.map(r => text(r.task_id))).size !== 1 ? '' : text(row.task_id);
        const belongs = !!taskId && parent === taskId && work.source === 'work_item';
        const codes: string[] = [];
        if (duplicate) {
            codes.push('DUPLICATE_ID');
            addIssue('DUPLICATE_ID', `${id} 有 ${rows.length} 条同身份记录；节点标为歧义，详情保留全部记录。`, [id]);
        }
        if (!parent) {
            codes.push('PARENT_UNRECORDED');
            addIssue('PARENT_UNRECORDED', `${id} 未记录正式 task_id，不根据名称推断归属。`, [id]);
        }
        else if (!belongs) {
            codes.push('PARENT_CONFLICT');
            addIssue('PARENT_CONFLICT', `${id} 的归属 ${parent} 与当前上下文或来源不符，单独展示。`, [id]);
        }
        nodes.push({
            id: identity(contextKey, taskId, 'work_item', id), objectId: id, kind: 'work_item',
            title: duplicate ? `${id}（${rows.length} 条歧义记录）` : text(row.title), status: duplicate ? '' : text(row.status),
            owner: duplicate ? '' : text(row.owner_agent) || text(row.owner_role), parentTaskId: parent, belongs,
            records: rows, issues: codes
        });
    }
    const byObjectId = new Map(nodes.filter(n => n.kind === 'work_item').map(n => [n.objectId, n]));
    const edgeMap = new Map<string, Dependency>();
    for (const target of nodes.filter(n => n.kind === 'work_item')) {
        for (const row of target.records) {
            const deps = row.depends_on;
            if (!Array.isArray(deps)) {
                addIssue('DEPENDENCIES_UNRECORDED', `${target.objectId} 的依赖不是有效数组；不解释为已确认无依赖。`, [target.objectId]);
                continue;
            }
            for (const raw of deps) {
                const id = typeof raw === 'string' ? raw : '';
                if (!id.trim()) {
                    addIssue('DEPENDENCY_INVALID', `${target.objectId} 含无有效 ID 的依赖值：${JSON.stringify(raw)}`, [target.objectId]);
                    continue;
                }
                const source = byObjectId.get(id);
                if (!source) {
                    addIssue('DANGLING_DEPENDENCY', `${id} → ${target.objectId}：前置对象未取得，此引用不生成假节点。`, [id, target.objectId]);
                    continue;
                }
                if (!source.belongs || !target.belongs || source.records.length !== 1 || target.records.length !== 1) {
                    addIssue('DEPENDENCY_AMBIGUOUS', `${id} → ${target.objectId}：身份或归属未确认；原引用保留，不伪画确定依赖。`, [id, target.objectId]);
                    continue;
                }
                const edgeId = identity(contextKey, taskId, 'dependency', id, target.objectId);
                edgeMap.set(edgeId, { id: edgeId, source: source.id, target: target.id, kind: 'dependency' });
            }
        }
    }
    const edges = [...edgeMap.values()].sort((a, b) => compare(a.id, b.id));
    // Reachability identifies actual cycle members, not every downstream node blocked by a cycle.
    const outgoing = new Map<string, string[]>();
    for (const edge of edges)
        outgoing.set(edge.source, [...(outgoing.get(edge.source) ?? []), edge.target]);
    for (const node of nodes.filter(n => n.kind === 'work_item')) {
        const seen = new Set<string>(), pending = [...(outgoing.get(node.id) ?? [])];
        let cyclic = false;
        while (pending.length) {
            const id = pending.pop()!;
            if (id === node.id) {
                cyclic = true;
                break;
            }
            if (seen.has(id))
                continue;
            seen.add(id);
            pending.push(...(outgoing.get(id) ?? []));
        }
        if (cyclic)
            node.issues.push('DEPENDENCY_CYCLE');
    }
    const cyclic = nodes.filter(n => n.issues.includes('DEPENDENCY_CYCLE')).map(n => n.objectId);
    if (cyclic.length)
        addIssue('DEPENDENCY_CYCLE', `循环依赖涉及：${cyclic.join('、')}。原边保留；异常区域位置不代表可执行顺序。`, cyclic);
    for (const problem of Array.isArray(work.issues) ? work.issues : [])
        addIssue('RUNTIME_WORKITEM_ISSUE', valueText(problem));
    const workflow = buildWorkflowRelations(contextKey, data);
    const topology = JSON.stringify([nodes.map(n => [n.id, n.belongs, n.parentTaskId]), edges.map(e => [e.source, e.target]), [...workflow.activityStages, ...workflow.stages].map(stage => stage.id)]);
    return { taskId, taskNodeId, groupId, nodes, edges, issues, invalidRecords, topology, workflow };
}
export function relatedIds(model: GraphModel, start: string, direction: 'upstream' | 'downstream'): Set<string> {
    const seen = new Set<string>([start]), found = new Set<string>(), pending = [start];
    while (pending.length) {
        const id = pending.pop()!;
        for (const edge of model.edges) {
            const next = direction === 'downstream' ? edge.source === id ? edge.target : '' : edge.target === id ? edge.source : '';
            if (next && !seen.has(next)) {
                seen.add(next);
                found.add(next);
                pending.push(next);
            }
        }
    }
    return found;
}
export function visibleIds(model: GraphModel, showItems: boolean, collapsed: Set<string>): Set<string> {
    if (!showItems)
        return new Set([model.taskNodeId]);
    const visible = new Set(model.nodes.map(n => n.id));
    for (const id of collapsed)
        for (const child of relatedIds(model, id, 'downstream'))
            if (!collapsed.has(child))
                visible.delete(child);
    return visible;
}
