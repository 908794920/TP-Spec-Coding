import { useId, useState } from 'react';
import { Alert, Button, Skeleton, Typography } from 'antd';
import { DashboardOutlined, DownOutlined, FolderOpenOutlined, FolderOutlined, RightOutlined } from '@ant-design/icons';
import { api } from '../api';
import { useRead } from '../useRead';
import { stateLabel, timestampRaw, timestampText } from '../facts';
import type { Context, Envelope, ProjectData, TaskIndexRow } from '../types';

/* A project is named by its folder: that is what the user recognises, and the full path stays one
   hover (or screen reader) away instead of being guessed at or truncated out of the label. */
function folderName(context: Context): string {
    const path = context.workspace_root || context.project_root || '';
    const parts = path.split(/[\\/]/).filter(Boolean);
    return parts.length ? parts[parts.length - 1] : context.name;
}
/* The sidebar row is narrow, so the day is shown and the exact instant stays in the tooltip; the
   workbench always renders timestamps on one clock, never as an approximated "n days ago". Leading
   zeros are dropped (`9-15`) to leave the title more room before it ellipsises. */
function shortDay(value: unknown): string {
    const raw = timestampRaw(value);
    if (!raw)
        return '';
    const [, month, day] = raw.slice(0, 10).split('-');
    return `${Number(month)}-${Number(day)}`;
}
const PREVIEW_COUNT = 5;

function ProjectRow({ context, expanded, selected, selectedTask, revision, onToggle, onOpenProject, onOpenTask }: {
    context: Context;
    expanded: boolean;
    selected: boolean;
    selectedTask: string;
    revision: number;
    onToggle: () => void;
    onOpenProject: () => void;
    onOpenTask: (taskId: string) => void;
}) {
    const listId = useId();
    const [showAll, setShowAll] = useState(false);
    const name = folderName(context);
    /* Lazy on purpose: a collapsed project costs no request at all, and expanding one only reads
       that project. Nothing is prefetched, and nothing is cached across projects. */
    const read = useRead<Envelope<ProjectData>>(expanded ? context.context_key : '', revision,
        signal => api.project(context.context_key, signal));
    const rows: TaskIndexRow[] = read.data?.data.task_index ?? [];
    const shown = showAll ? rows : rows.slice(0, PREVIEW_COUNT);
    const hidden = rows.length - shown.length;
    return <li className={selected ? 'project-row selected' : 'project-row'}>
      <div className="project-head">
        <button type="button" className="project-toggle" aria-expanded={expanded} aria-controls={listId}
          title={context.workspace_root || undefined} onClick={onToggle}>
          {expanded ? <DownOutlined className="caret"/> : <RightOutlined className="caret"/>}
          {expanded ? <FolderOpenOutlined className="folder"/> : <FolderOutlined className="folder"/>}
          <span className="project-name">{name}</span>
        </button>
        {/* The icon action is laid over the row instead of taking flow space, so the row itself stays
            one full-width toggle target. The button swallows its own click, so opening the project
            overview never also expands or collapses the folder. */}
        <span className="project-actions">
          <Button size="small" type="text" className="project-open" icon={<DashboardOutlined/>}
            aria-label={`打开 ${name} 的项目总览`} title="打开项目总览" onClick={onOpenProject}/>
        </span>
      </div>
      {expanded && <div className="project-tasks" id={listId}>
        {read.loading && <Skeleton active={false} title={false} paragraph={{ rows: 3 }}/>}
        {read.error && <Alert type="error" showIcon title={read.error}/>}
        {!read.loading && !read.error && !rows.length && <p className="muted">当前项目没有已取得的任务。</p>}
        {!!rows.length && <ul className="project-task-list">{shown.map(row => <li key={row.task_id}>
          <button type="button" className={selectedTask === row.task_id ? 'task-link selected' : 'task-link'}
            aria-current={selectedTask === row.task_id ? 'page' : undefined}
            title={`${row.task_id} · ${stateLabel('task', row.state)}${row.retired ? ' · 已退休' : ''} · ${timestampText(row.updated_at)}`}
            onClick={() => onOpenTask(row.task_id)}>
            <span>{row.title || row.task_id}</span>
            <small>{shortDay(row.updated_at)}</small>
          </button></li>)}</ul>}
        {hidden > 0 && <button type="button" className="see-more" onClick={() => setShowAll(true)}>查看更多 ({hidden})</button>}
        {!hidden && rows.length > PREVIEW_COUNT && <button type="button" className="see-more" onClick={() => setShowAll(false)}>收起</button>}
      </div>}
    </li>;
}
export function SidebarProjects({ contexts, selectedKey, selectedTask, revision, onOpenProject, onOpenTask }: {
    contexts: Context[];
    selectedKey: string;
    selectedTask: string;
    revision: number;
    onOpenProject: (contextKey: string) => void;
    onOpenTask: (contextKey: string, taskId: string) => void;
}) {
    /* Expanding is transient view state, not a persisted preference: it follows whatever the user is
       looking at right now rather than surviving a reload into an unexpected shape. */
    const [openKeys, setOpenKeys] = useState<string[]>([]);
    /* The project list folds away as a whole, and the group header is the control that does it. The
       fold keeps `openKeys`, so unfolding shows the same projects expanded as before. */
    const [treeOpen, setTreeOpen] = useState(true);
    const listId = useId();
    if (!contexts.length)
        return null;
    return <>
      <div className="nav-section-head">
        <button type="button" className="nav-section-toggle" aria-expanded={treeOpen} aria-controls={listId}
          title={treeOpen ? '收起项目列表' : '展开项目列表'} onClick={() => setTreeOpen(open => !open)}>
          {treeOpen ? <FolderOpenOutlined/> : <FolderOutlined/>}
          <Typography.Text className="nav-section-title" type="secondary">项目 · {contexts.length}</Typography.Text>
          {treeOpen ? <DownOutlined className="caret"/> : <RightOutlined className="caret"/>}
        </button>
      </div>
      {treeOpen && <ul className="project-tree" id={listId} aria-label="已注册项目">{contexts.map(context => <ProjectRow key={context.context_key}
        context={context} expanded={openKeys.includes(context.context_key)} selected={context.context_key === selectedKey}
        selectedTask={selectedTask} revision={revision}
        onToggle={() => setOpenKeys(old => old.includes(context.context_key)
            ? old.filter(key => key !== context.context_key)
            : [...old, context.context_key])}
        onOpenProject={() => onOpenProject(context.context_key)}
        onOpenTask={taskId => onOpenTask(context.context_key, taskId)}/>)}</ul>}
    </>;
}
