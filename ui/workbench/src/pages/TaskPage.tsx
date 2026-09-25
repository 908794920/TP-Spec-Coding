import { Button } from 'antd';
import { api } from '../api';
import { useRead } from '../useRead';
import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Context, Envelope, ReadState, TaskData } from '../types';
import { record, stateLabel, text } from '../facts';
import { buildGraph, type GraphObject } from '../graph/model';
import type { GraphHandle } from '../graph/TaskGraph';
import { TaskDetail, type TaskDetailTab } from '../components/TaskDetail';
import { WorkflowStrip, type WorkflowHandle } from '../components/WorkflowStrip';
import { WorkResults } from '../components/WorkResults';
import { TaskDocuments } from '../components/TaskDocuments';
import { EventTimeline } from '../components/EventTimeline';
import { Disclosure, Empty, Fields, Problems, ReadStatus } from '../components/Facts';

/* 关系图依赖 @xyflow/react 及其样式，进入任务时默认展开，保留独立 lazy 分块。
   加载占位沿用 graph-canvas，图出现时保持区域尺寸，避免布局跳动。 */
const TaskGraph = lazy(() => import('../graph/TaskGraph').then(module => ({ default: module.TaskGraph })));

function focusAfterReveal(element: HTMLElement | null) {
    if (!element)
        return;
    requestAnimationFrame(() => {
        element.focus({ preventScroll: true });
        element.scrollIntoView({ block: 'nearest', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    });
}

function WorkflowDiagnostics({ context, taskId, data, workItemId }: {
    context: Context;
    taskId: string;
    data: TaskData;
    workItemId?: string;
}) {
    const workflow = record(data.workflow), support = record(data.data_support);
    return <div className="task-diagnostics">
      <EventTimeline events={data.timeline} scope={data.timeline_scope} workItemId={workItemId}/>
      <Disclosure className="route-diagnostics" label="路由与来源字段">
        <Fields value={{ current_step: workflow.current_step, current_step_source: workflow.current_step_source,
          next_step: workflow.next_step, next_step_source: workflow.next_step_source, route: workflow.route,
          effective_level: workflow.effective_level, error: workflow.error }}
          labels={{ current_step: '当前步骤原值', current_step_source: '当前步骤来源', next_step: '下一步原值',
            next_step_source: '下一步来源', effective_level: '有效流程等级', error: '解析提示' }}/>
      </Disclosure>
      <Disclosure className="task-read-diagnostics" label="数据支持、工作区与读取边界">
        <Fields value={{ task_id: taskId, context_key: context.context_key, project_id: context.project_id,
          workspace_root: context.workspace_root, data_support: support, timeline_scope: data.timeline_scope }}
          labels={{ task_id: '正式 Task ID', context_key: '上下文键', project_id: '项目 ID', workspace_root: '工作区路径',
            data_support: '数据支持', timeline_scope: '时间线读取范围' }}/>
      </Disclosure>
    </div>;
}

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
    const [detailTab, setDetailTab] = useState<TaskDetailTab>('overview');
    const [graphExpanded, setGraphExpanded] = useState(true);
    const [graphMounted, setGraphMounted] = useState(true), [pendingGraphLocate, setPendingGraphLocate] = useState('');
    const graph = useRef<GraphHandle>(null), workflow = useRef<WorkflowHandle>(null);
    const graphDetails = useRef<HTMLDetailsElement>(null);
    const documentsDetails = useRef<HTMLDetailsElement>(null), documentsFocus = useRef<HTMLDivElement>(null);
    const workResultsFocus = useRef<HTMLDivElement>(null);
    const workReturnFocus = useRef<{ id: string; trigger: HTMLElement | null } | null>(null);
    const returnFocus = useRef<HTMLElement | null>(null);
    const selected = model.nodes.find(n => n.id === selectedId);
    const taskObject = model.nodes.find(n => n.id === model.taskNodeId);
    const task = record(data.task);

    const onDetails = useCallback(() => requestDetails(true), []);
    const onRefreshDetails = useCallback(() => { requestDetails(true); refreshDetails(n => n + 1); }, []);
    const onCloseout = useCallback(() => { requestCloseout(true); refreshCloseout(n => n + 1); }, []);
    const rememberFocus = useCallback(() => {
        const active = document.activeElement;
        returnFocus.current = active instanceof HTMLElement ? active : null;
    }, []);
    const openTaskDetail = useCallback((tab: TaskDetailTab) => {
        if (!taskObject)
            return;
        rememberFocus();
        setSelectedId(taskObject.id);
        setDetailTab(tab);
        setDetailOpen(true);
    }, [rememberFocus, taskObject]);
    const onOpen = useCallback((object: GraphObject) => {
        rememberFocus();
        setSelectedId(object.id);
        setDetailTab('overview');
        setDetailOpen(true);
    }, [rememberFocus]);
    const close = useCallback(() => {
        setDetailOpen(false);
        const target = returnFocus.current;
        returnFocus.current = null;
        requestAnimationFrame(() => {
            if (target && document.contains(target))
                target.focus();
            else
                graph.current?.focusNode(selectedId);
        });
    }, [selectedId]);
    useEffect(() => {
        if (selectedId && !selected) {
            setSelectedId('');
            setDetailOpen(false);
            setDetailTab('overview');
        }
    }, [selectedId, selected]);
    useEffect(() => {
        if (!pendingGraphLocate || !graphMounted)
            return;
        let frame = 0, attempts = 0;
        const locate = () => {
            if (graph.current) {
                graph.current.locate(pendingGraphLocate);
                setPendingGraphLocate('');
                return;
            }
            if (attempts++ < 60)
                frame = requestAnimationFrame(locate);
            else
                setPendingGraphLocate('');
        };
        frame = requestAnimationFrame(locate);
        return () => cancelAnimationFrame(frame);
    }, [graphMounted, pendingGraphLocate]);

    const openDocuments = useCallback(() => {
        if (documentsDetails.current)
            documentsDetails.current.open = true;
        focusAfterReveal(documentsFocus.current);
    }, []);
    const openWorkItem = useCallback((id: string) => {
        workReturnFocus.current = { id, trigger: document.activeElement instanceof HTMLElement ? document.activeElement : null };
        if (documentsDetails.current)
            documentsDetails.current.open = true;
        requestAnimationFrame(() => requestAnimationFrame(() => {
            const root = workResultsFocus.current;
            const item = Array.from(root?.querySelectorAll<HTMLDetailsElement>('details[id]') ?? [])
                .find(element => element.id === `work-unit-${id}`);
            if (item) {
                item.open = true;
                focusAfterReveal(item.querySelector<HTMLElement>('summary') ?? item);
            }
            else
                focusAfterReveal(root);
        }));
    }, []);
    useEffect(() => {
        const root = workResultsFocus.current;
        const returnFromWork = (event: Event) => {
            const entry = workReturnFocus.current, target = event.target;
            if (entry && target instanceof HTMLDetailsElement && target.id === `work-unit-${entry.id}` && !target.open) {
                workReturnFocus.current = null;
                if (entry.trigger && document.contains(entry.trigger)) focusAfterReveal(entry.trigger);
            }
        };
        root?.addEventListener('toggle', returnFromWork, true);
        return () => root?.removeEventListener('toggle', returnFromWork, true);
    }, []);
    const locateGraph = useCallback((id: string) => {
        if (graphDetails.current)
            graphDetails.current.open = true;
        setGraphMounted(true);
        setPendingGraphLocate(id);
    }, []);

    return <div className="task-workspace-shell">
    <div className="task-quick-actions" aria-label="Task 详情入口">
      <Button size="small" onClick={() => openTaskDetail('overview')}>Task 概况</Button>
      <Button size="small" onClick={() => openTaskDetail('blockers')}>阻塞详情</Button>
      <Button size="small" onClick={() => openTaskDetail('verification')}>验证验收</Button>
    </div>
    <section className="task-main" aria-label="Task 当前流程">
      <WorkflowStrip workflow={record(data.workflow)} task={task} ref={workflow} blockers={data.blockers}
        onDocuments={openDocuments} onWorkItem={openWorkItem}/>
    </section>
    <details ref={graphDetails} open={graphExpanded} className="task-support-section task-auxiliary task-relations" onToggle={event => { setGraphExpanded(event.currentTarget.open); if (event.currentTarget.open) setGraphMounted(true); }}>
      <summary>工作关系</summary>
      <div className="task-auxiliary-body">
        <div className="section-heading"><h3>工作关系</h3><div className="graph-actions">
          <Button size="small" onClick={() => graph.current?.locateCurrent()}>定位当前步骤</Button>
          <Button size="small" disabled={task.state !== 'BLOCKED'} onClick={() => locateGraph(model.taskNodeId)}>定位阻塞 Task</Button>
        </div></div>
        <p className="support-note">沿阶段查看参与角色、工作摘要和事件记录。点击阶段卡片展开明细，或用上方按钮定位当前阶段。</p>
        {graphMounted ? <Suspense fallback={<div className="graph-canvas graph-loading" role="status">正在加载关系图…</div>}>
          <TaskGraph ref={graph} model={model} selectedId={selectedId} onOpen={onOpen}/>
        </Suspense> : <p className="support-note" role="status">展开工作关系后加载关系图。</p>}
      </div>
    </details>
    <details ref={documentsDetails} className="task-support-section task-auxiliary task-materials">
      <summary>任务资料与验收</summary>
      <div className="task-auxiliary-body">
        <section className="task-detail-entry" aria-label="任务详情入口">
          <div className="section-heading"><h3>任务详情</h3><div className="graph-actions">
            <Button size="small" onClick={() => openTaskDetail('overview')}>Task 概况</Button>
            <Button size="small" onClick={() => openTaskDetail('blockers')}>阻塞详情</Button>
            <Button size="small" onClick={() => openTaskDetail('verification')}>验证验收</Button>
          </div></div>
          <p className="muted">详情入口直接读取当前 Task；打开阻塞或验收页时才请求对应详情，不依赖关系图先加载。</p>
        </section>
        <div ref={documentsFocus} className="task-documents-focus task-auxiliary-focus" tabIndex={-1}>
          <TaskDocuments value={data.documents}/>
        </div>
        <div ref={workResultsFocus} className="task-work-results-focus" tabIndex={-1}>
          <WorkResults value={data.work_items}/>
        </div>
      </div>
    </details>
    <details className="task-support-section task-auxiliary task-diagnostics-group">
      <summary>任务历史与诊断</summary>
      <div className="task-auxiliary-body">
        <WorkflowDiagnostics context={context} taskId={taskId} data={data} workItemId={selected?.kind === 'work_item' ? selected.objectId : undefined}/>
      </div>
    </details>
    {detailOpen && selected && <TaskDetail object={selected} snapshot={snapshot} initialTab={detailTab} defaultTab="overview" onClose={close} details={details}
      onDetails={onDetails} onRefreshDetails={onRefreshDetails} closeout={closeout} closeoutRequested={closeoutRequested} onCloseout={onCloseout}/>}
  </div>;
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
    const data = read.data?.data, task = record(data?.task);
    const displayState = data ? stateLabel('task', task.state).split(' · ')[0] : '状态未读取';
    return <div className="page task-page"><div className="page-heading"><div><span className="eyebrow">任务工作区 · {context.name}</span><h2>{text(task.title) || '任务'} {taskId && <small className="task-id"><code>{taskId}</code></small>}</h2><p>{displayState}</p></div></div>
    <ReadStatus {...read}/>{data && <><Problems items={data.problems}/><TaskWorkspace key={JSON.stringify([context.context_key, taskId])} context={context} snapshot={read.data!} revision={revision}/></>}
  </div>;
}
