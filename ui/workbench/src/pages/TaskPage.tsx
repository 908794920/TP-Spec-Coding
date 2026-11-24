import { Button, Drawer, Skeleton } from 'antd';
import { ArrowLeftOutlined, FileTextOutlined, HistoryOutlined } from '@ant-design/icons';
import { api } from '../api';
import { useRead } from '../useRead';
import { useCallback, useLayoutEffect, useRef, useState } from 'react';
import type { Context, Envelope, ReadState, TaskData } from '../types';
import { record, stateLabel, text } from '../facts';
import { TaskDetail, type TaskDetailTab } from '../components/TaskDetail';
import { WorkflowStrip, type WorkflowHandle } from '../components/WorkflowStrip';
import { WorkResults } from '../components/WorkResults';
import { TaskDocuments } from '../components/TaskDocuments';
import { EventTimeline } from '../components/EventTimeline';
import { Disclosure, Empty, Fields, Problems, ReadStatus } from '../components/Facts';

function focusAfterReveal(element: HTMLElement | null) {
    if (!element)
        return;
    element.focus({ preventScroll: true });
    element.scrollIntoView({ block: 'nearest', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
}

function TaskMaterials({ data, expandedWork, materialTarget, onWorkToggle }: {
    data: TaskData;
    expandedWork: string[];
    materialTarget?: { workId?: string };
    onWorkToggle: (id: string, open: boolean) => void;
}) {
    const documents = useRef<HTMLDivElement>(null), results = useRef<HTMLDivElement>(null);
    const summary = useRef<HTMLElement>(null);
    useLayoutEffect(() => {
        if (!materialTarget) return;
        const target = materialTarget.workId ? summary.current ?? results.current : documents.current;
        if (!target) return;
        if (target.getClientRects().length) {
            focusAfterReveal(target);
            return;
        }
        const observer = new ResizeObserver(() => {
            if (!target.getClientRects().length) return;
            observer.disconnect();
            focusAfterReveal(target);
        });
        observer.observe(target);
        return () => observer.disconnect();
    }, [materialTarget]);

    return <>
      <div ref={documents} tabIndex={-1}><TaskDocuments value={data.documents}/></div>
      <div ref={results} tabIndex={-1}>
        <WorkResults value={data.work_items} expandedIds={expandedWork} onToggle={onWorkToggle}
          focusId={materialTarget?.workId} focusRef={summary}/>
      </div>
    </>;
}

function WorkflowDiagnostics({ context, taskId, data }: {
    context: Context;
    taskId: string;
    data: TaskData;
}) {
    const workflow = record(data.workflow), support = record(data.data_support);
    return <div className="task-diagnostics">
      <EventTimeline events={data.timeline} scope={data.timeline_scope}/>
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

function TaskLoadingSkeleton() {
    return <div className="task-skeleton-shell" role="status" aria-label="正在加载任务工作区">
      <div className="task-skeleton-banner"><Skeleton active paragraph={{ rows: 2 }}/></div>
      <div className="task-skeleton-stepper">{[1, 2, 3, 4, 5].map(i => <div className="task-skeleton-step" key={i}><Skeleton active title={false} paragraph={{ rows: 2 }}/></div>)}</div>
      <div className="task-skeleton-cards">{[1, 2, 3].map(i => <div className="task-skeleton-card" key={i}><Skeleton active paragraph={{ rows: 3 }}/></div>)}</div>
    </div>;
}

function TaskWorkspace({ context, snapshot, read, revision, sideDrawer, onCloseSideDrawer }: {
    context: Context;
    snapshot: Envelope<TaskData>;
    read: ReadState<Envelope<TaskData>>;
    revision: number;
    sideDrawer: 'materials' | 'history' | null;
    onCloseSideDrawer: () => void;
}) {
    const data = snapshot.data;
    const taskId = text(record(data.task).task_id);
    const [detailsRequested, requestDetails] = useState(false), [detailRevision, refreshDetails] = useState(0);
    const [closeoutRequested, requestCloseout] = useState(false), [closeoutRevision, refreshCloseout] = useState(0);
    const identity = JSON.stringify([context.context_key, taskId]);
    const shouldReadRoute = ['NEW', 'ACTIVE'].includes(text(data.task.state)) && data.workflow.retired !== true;
    const route = useRead(shouldReadRoute && !read.loading && !read.error ? identity + '/route' : '', revision,
        signal => api.taskRoute(context.context_key, taskId, signal));
    const routeMatches = !!route.data && route.data.read.task_revision === snapshot.read.task_revision;
    const routeWorkflow = routeMatches && !route.loading && !route.error ? route.data?.data.workflow : undefined;
    const routeStatus = !shouldReadRoute ? '' : read.error || route.error || routeWorkflow?.error ? '当前流转未取得'
        : route.data && !route.loading && !routeMatches ? '任务记录已更新，请重新读取'
        : routeWorkflow ? '' : '正在读取当前流转';
    const displayedWorkflow = { ...data.workflow, ...routeWorkflow, error: route.error || routeWorkflow?.error,
        route_read_status: routeStatus };
    const details = useRead(detailsRequested ? identity + '/details' : '', `${revision}:${detailRevision}`, signal => api.details(context.context_key, taskId, signal));
    const closeout = useRead(closeoutRequested ? identity + '/closeout' : '', closeoutRevision, signal => api.closeout(context.context_key, taskId, signal));
    const [detailOpen, setDetailOpen] = useState(false);
    const [detailTab, setDetailTab] = useState<TaskDetailTab>('overview');
    const [localSideDrawer, setLocalSideDrawer] = useState<'materials' | 'history' | null>(null);
    const activeDrawer = sideDrawer ?? localSideDrawer;
    const closeDrawer = useCallback(() => {
        setLocalSideDrawer(null);
        onCloseSideDrawer();
    }, [onCloseSideDrawer]);
    const [expandedWork, setExpandedWork] = useState<string[]>([]);
    const [materialTarget, setMaterialTarget] = useState<{ workId?: string }>();
    const workflow = useRef<WorkflowHandle>(null);
    const workReturnFocus = useRef<{ id: string; trigger: HTMLElement | null } | null>(null);
    const returnFocus = useRef<HTMLElement | null>(null);
    const task = record(data.task);

    const onDetails = useCallback(() => requestDetails(true), []);
    const onRefreshDetails = useCallback(() => { requestDetails(true); refreshDetails(n => n + 1); }, []);
    const onCloseout = useCallback(() => { requestCloseout(true); refreshCloseout(n => n + 1); }, []);
    const rememberFocus = useCallback(() => {
        const active = document.activeElement;
        returnFocus.current = active instanceof HTMLElement ? active : null;
    }, []);
    const openTaskDetail = useCallback((tab: TaskDetailTab) => {
        rememberFocus();
        setDetailTab(tab);
        setDetailOpen(true);
    }, [rememberFocus]);
    const close = useCallback(() => {
        setDetailOpen(false);
        const target = returnFocus.current;
        returnFocus.current = null;
        requestAnimationFrame(() => {
            if (target && document.contains(target))
                target.focus();
        });
    }, []);

    const setWorkOpen = useCallback((id: string, open: boolean) => {
        setExpandedWork(previous => {
            if (previous.includes(id) === open) return previous;
            return open ? [...previous, id] : previous.filter(workId => workId !== id);
        });
    }, []);
    const openDocuments = useCallback(() => {
        setLocalSideDrawer('materials');
        setMaterialTarget({});
    }, []);
    const openWorkItem = useCallback((id: string) => {
        workReturnFocus.current = { id, trigger: document.activeElement instanceof HTMLElement ? document.activeElement : null };
        setLocalSideDrawer('materials');
        setWorkOpen(id, true);
        setMaterialTarget({ workId: id });
    }, [setWorkOpen]);
    const onWorkToggle = useCallback((id: string, open: boolean) => {
        setWorkOpen(id, open);
        const origin = workReturnFocus.current;
        if (!open && origin?.id === id) {
            workReturnFocus.current = null;
            if (origin.trigger?.isConnected) focusAfterReveal(origin.trigger);
        }
    }, [setWorkOpen]);

    return <div className="task-workspace-shell">
    <section className="task-main" aria-label="Task 当前流程">
      <WorkflowStrip workflow={displayedWorkflow} task={task} ref={workflow} blockers={data.blockers}
        lifecycleActivity={data.lifecycle_activity}
        workItems={data.work_items} onConditions={() => openTaskDetail('blockers')}
        onDocuments={openDocuments} onWorkItem={openWorkItem}/>
    </section>

    <Drawer open={activeDrawer === 'materials'} size={580} onClose={closeDrawer} title="资料与 Work">
      <TaskMaterials data={data} expandedWork={expandedWork} materialTarget={materialTarget} onWorkToggle={onWorkToggle}/>
    </Drawer>

    <Drawer open={activeDrawer === 'history'} size={580} onClose={closeDrawer} title="历史与证据">
      <div className="task-history-drawer">
        <div className="task-history-actions">
          <Button size="small" onClick={() => openTaskDetail('overview')}>Task 概况</Button>
          <Button size="small" onClick={() => openTaskDetail('verification')}>验证验收</Button>
          <Button size="small" onClick={() => openTaskDetail('evidence')}>证据与交付</Button>
        </div>
        <ReadStatus {...read}/>
        <Problems items={data.problems}/>
        <WorkflowDiagnostics context={context} taskId={taskId} data={{ ...data, workflow: displayedWorkflow }}/>
      </div>
    </Drawer>

    {detailOpen && <TaskDetail snapshot={{ ...snapshot, data: { ...data, workflow: displayedWorkflow } }} initialTab={detailTab} defaultTab="overview" onClose={close} details={details}
      onDetails={onDetails} onRefreshDetails={onRefreshDetails} closeout={closeout} closeoutRequested={closeoutRequested} onCloseout={onCloseout}/>}
  </div>;
}

export function TaskPage({ context, taskId, read, revision, onOpenProject }: {
    context?: Context;
    taskId: string;
    revision: number;
    read: ReadState<Envelope<TaskData>>;
    onOpenProject: (key: string) => void;
}) {
    const [sideDrawer, setSideDrawer] = useState<'materials' | 'history' | null>(null);
    if (!context || !taskId)
        return <div className="page task-page"><div className="page-heading"><div><span className="eyebrow">任务工作区</span><h2>尚未选择 Task</h2></div></div>
        <Empty title="选择一个 Task 查看工作进展">从项目总览或左侧任务索引进入。</Empty></div>;
    const data = read.data?.data, task = record(data?.task);
    const displayState = data ? stateLabel('task', task.state).split(' · ')[0] : '';
    const issueCount = data?.problems?.length ?? 0;
    return <div className="page task-page">
      <div className="task-flat-header">
        <div className="task-flat-left">
          <Button size="small" className="task-back-btn" icon={<ArrowLeftOutlined/>} onClick={() => onOpenProject(context.context_key)}>返回 {context.name}</Button>
          <div className="task-title-line">
            <h2>{text(task.title) || taskId}</h2>
            {taskId && <code className="task-id-inline">{taskId}</code>}
            {displayState && <span className="task-state-pill">{displayState}</span>}
          </div>
        </div>
        {data && <div className="task-flat-actions">
          <Button size="small" icon={<FileTextOutlined/>} onClick={() => setSideDrawer('materials')}>资料与 Work</Button>
          <Button size="small" icon={<HistoryOutlined/>} onClick={() => setSideDrawer('history')}>
            历史与证据{issueCount > 0 ? ` (${issueCount})` : ''}
          </Button>
        </div>}
      </div>
      {read.loading && !data && <TaskLoadingSkeleton/>}
      {data && <TaskWorkspace key={JSON.stringify([context.context_key, taskId])} context={context} snapshot={read.data!} read={read} revision={revision}
        sideDrawer={sideDrawer} onCloseSideDrawer={() => setSideDrawer(null)}/>}
    </div>;
}
