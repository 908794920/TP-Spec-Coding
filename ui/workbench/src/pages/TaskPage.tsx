import { Button } from 'antd';
import { api } from '../api';
import { useRead } from '../useRead';
import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Context, Envelope, ReadState, TaskData } from '../types';
import { record, stateLabel, text } from '../facts';
import { buildGraph, type GraphObject } from '../graph/model';
import type { GraphHandle } from '../graph/TaskGraph';
import { TaskDetail } from '../components/TaskDetail';
import { WorkflowStrip, type WorkflowHandle } from '../components/WorkflowStrip';
import { WorkResults } from '../components/WorkResults';
import { TaskDocuments } from '../components/TaskDocuments';
import { EventTimeline } from '../components/EventTimeline';
import { Empty, Problems, ReadStatus } from '../components/Facts';
/* The graph pulls in @xyflow/react and its stylesheet, which the first screen never shows; loading it
   on demand keeps both out of the entry chunk. The fallback reuses `.graph-canvas` so the region is
   already the right size and nothing shifts when it arrives. */
const TaskGraph = lazy(() => import('../graph/TaskGraph').then(module => ({ default: module.TaskGraph })));
function TaskWorkspace({ context, snapshot, revision }: {
    context: Context;
    snapshot: Envelope<TaskData>;
    revision: number;
}) {
    const data = snapshot.data;
    const taskId = text(record(data.task).task_id);
    const [detailsRequested, requestDetails] = useState(false), [detailRevision, refreshDetails] = useState(0);
    const [closeoutRequested, requestCloseout] = useState(false), [closeoutRevision, refreshCloseout] = useState(0);
    const identity = JSON.stringify([context.context_key, taskId]);
    const details = useRead(detailsRequested ? identity + '/details' : '', `${revision}:${detailRevision}`, signal => api.details(context.context_key, taskId, signal));
    const closeout = useRead(closeoutRequested ? identity + '/closeout' : '', `${revision}:${closeoutRevision}`, signal => api.closeout(context.context_key, taskId, signal));
    const model = useMemo(() => buildGraph(context.context_key, data), [context.context_key, data]);
    const [selectedId, setSelectedId] = useState(''), [detailOpen, setDetailOpen] = useState(false);
    const graph = useRef<GraphHandle>(null), workflow = useRef<WorkflowHandle>(null);
    const selected = model.nodes.find(n => n.id === selectedId);
    useEffect(() => { if (selectedId && !selected) {
        setSelectedId('');
        setDetailOpen(false);
    } }, [selectedId, selected]);
    const onOpen = useCallback((object: GraphObject) => { setSelectedId(object.id); setDetailOpen(true); }, []);
    const close = useCallback(() => { setDetailOpen(false); requestAnimationFrame(() => graph.current?.focusNode(selectedId)); }, [selectedId]);
    const support = record(data.data_support), task = record(data.task);
    return <>
    <WorkflowStrip workflow={record(data.workflow)} task={task} ref={workflow}/>
    <WorkResults value={data.work_items}/>
    <TaskDocuments value={data.documents}/>
    <div className="section-heading"><h3>工作关系</h3><div className="graph-actions"><Button size="small" onClick={() => workflow.current?.locateCurrent()}>定位当前步骤</Button><Button size="small" disabled={task.state !== 'BLOCKED'} onClick={() => graph.current?.locate(model.taskNodeId)}>定位阻塞 Task</Button><Button size="small" onClick={() => graph.current?.locate(model.taskNodeId)}>Task 概况</Button></div></div>
    <p className="support-note">Task / WorkItem 关系来自账本；新版结果契约见上方子工作详情，旧记录缺失字段不补造。Agent Thread 绑定：{text(support.agent_thread_binding) || '未提供'}。</p>
    <div className={`task-workspace ${detailOpen && selected ? 'with-detail' : ''}`}>
      <Suspense fallback={<div className="graph-canvas graph-loading" role="status">正在加载关系图…</div>}>
        <TaskGraph ref={graph} model={model} selectedId={selectedId} onOpen={onOpen}/>
      </Suspense>
      {detailOpen && selected && <TaskDetail object={selected} snapshot={snapshot} onClose={close} details={details}
        onDetails={() => requestDetails(true)} onRefreshDetails={() => { requestDetails(true); refreshDetails(n => n + 1); }}
        closeout={closeout} closeoutRequested={closeoutRequested} onCloseout={() => { requestCloseout(true); refreshCloseout(n => n + 1); }}/>}
    </div>
    <EventTimeline events={data.timeline} scope={data.timeline_scope} workItemId={selected?.kind === 'work_item' ? selected.objectId : undefined}/>
  </>;
}
export function TaskPage({ context, taskId, read, revision }: {
    context?: Context;
    taskId: string;
    revision: number;
    read: ReadState<Envelope<TaskData>>;
}) {
    if (!context || !taskId)
        return <div className="page task-page"><div className="page-heading"><div><span className="eyebrow">任务工作区</span><h2>尚未选择 Task</h2></div></div>
        <Empty title="选择一个 Task 查看工作关系">从项目总览或左侧任务索引进入；不会自动选取“最近任务”。</Empty></div>;
    const data = read.data?.data;
    return <div className="page task-page"><div className="page-heading"><div><span className="eyebrow">任务工作区 · {context.name}</span><h2><code>{taskId}</code> {text(record(data?.task).title)}</h2><p>{data ? stateLabel('task', record(data.task).state) : '状态未读取'} · {context.workspace_root}</p></div></div>
    <ReadStatus {...read}/>{data && <><Problems items={data.problems}/><TaskWorkspace key={JSON.stringify([context.context_key, taskId])} context={context} snapshot={read.data!} revision={revision}/></>}
  </div>;
}
