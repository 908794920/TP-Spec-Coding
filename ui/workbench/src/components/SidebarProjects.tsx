import { useId, useState } from 'react';
import { Alert, Button, Skeleton, Typography } from 'antd';
import { DownOutlined, ExclamationCircleOutlined, FolderOpenOutlined, FolderOutlined, RightOutlined } from '@ant-design/icons';
import { api } from '../api';
import { useRead } from '../useRead';
import { explainValue, stateLabel, stateTone, text, timestampText } from '../facts';
import type { Context, Envelope, ProjectData, TaskIndexRow } from '../types';

function folderName(context: Context): string {
    const path = context.workspace_root || context.project_root || '';
    const parts = path.split(/[\\/]/).filter(Boolean);
    return parts.length ? parts[parts.length - 1] : context.name;
}
function taskStagePill(row: TaskIndexRow): { label: string; tone: string } {
    const phaseRaw = text(row.phase);
    const shortPhase = phaseRaw ? (explainValue('phase', phaseRaw) || phaseRaw).split('（')[0].replace(/确认|阶段|审查/g, s => s === '审查' ? '审' : '') : '';
    const state = text(row.state).trim().toUpperCase();
    const label = shortPhase || stateLabel('task', state).split(' · ')[0];
    return { label: label.slice(0, 4), tone: stateTone('task', state) };
}
const PREVIEW_COUNT = 5;

function ProjectRow({ context, expanded, selected, selectedTask, hasIssue, revision, onToggle, onOpenProject, onOpenTask }: {
    context: Context;
    expanded: boolean;
    selected: boolean;
    selectedTask: string;
    hasIssue?: boolean;
    revision: number;
    onToggle: () => void;
    onOpenProject: () => void;
    onOpenTask: (taskId: string) => void;
}) {
    const listId = useId();
    const [showAll, setShowAll] = useState(false);
    const name = folderName(context);
    const read = useRead<Envelope<ProjectData>>(expanded ? context.context_key : '', revision,
        signal => api.project(context.context_key, signal));
    const rows: TaskIndexRow[] = read.data?.data.task_index ?? [];
    const shown = showAll ? rows : rows.slice(0, PREVIEW_COUNT);
    const hidden = rows.length - shown.length;
    return <li className={selected ? 'project-row selected' : 'project-row'}>
      <div className="project-head">
        {/* Clicking the project name opens its Project Overview directly; the chevron independently toggles the task tree. */}
        <button type="button" className="project-toggle"
          title={`${name} · 点击打开项目总览 (${context.workspace_root || ''})`} onClick={onOpenProject}>
          {expanded ? <FolderOpenOutlined className="folder"/> : <FolderOutlined className="folder"/>}
          <span className="project-name">{name}</span>
          {hasIssue && <ExclamationCircleOutlined className="project-issue-dot" title="该项目运行环境存在异常提示"/>}
        </button>
        <span className="project-actions">
          <Button size="small" type="text" className="project-open"
            icon={expanded ? <DownOutlined/> : <RightOutlined/>}
            aria-expanded={expanded} aria-controls={listId}
            aria-label={expanded ? `收起 ${name} 的任务列表` : `展开 ${name} 的任务列表`}
            title={expanded ? '收起任务列表' : '展开任务列表'} onClick={onToggle}/>
        </span>
      </div>
      {expanded && <div className="project-tasks" id={listId}>
        {read.loading && <Skeleton active title={false} paragraph={{ rows: 3 }}/>}
        {read.error && <Alert type="error" showIcon title={read.error}/>}
        {!read.loading && !read.error && !rows.length && <p className="muted">当前项目没有已取得的任务。</p>}
        {!!rows.length && <ul className="project-task-list">{shown.map(row => {
          const pill = taskStagePill(row);
          return <li key={row.task_id}>
          <button type="button" className={selected && selectedTask === row.task_id ? 'task-link selected' : 'task-link'}
            aria-current={selected && selectedTask === row.task_id ? 'page' : undefined}
            title={`${row.task_id} · ${stateLabel('task', row.state)}${row.retired ? ' · 已退休' : ''} · ${timestampText(row.updated_at)}`}
            onClick={() => onOpenTask(row.task_id)}>
            <span className="task-link-title">{row.title || row.task_id}</span>
            <small className={`task-link-stage is-${pill.tone}`}>{pill.label}</small>
          </button></li>;
        })}</ul>}
        {hidden > 0 && <button type="button" className="see-more" onClick={() => setShowAll(true)}>查看全部 {rows.length} 单</button>}
        {!hidden && rows.length > PREVIEW_COUNT && <button type="button" className="see-more" onClick={() => setShowAll(false)}>收起</button>}
      </div>}
    </li>;
}
export function SidebarProjects({ contexts, selectedKey, selectedTask, issueProjectIds, revision, onOpenProject, onOpenTask }: {
    contexts: Context[];
    selectedKey: string;
    selectedTask: string;
    issueProjectIds?: Set<string>;
    revision: number;
    onOpenProject: (contextKey: string) => void;
    onOpenTask: (contextKey: string, taskId: string) => void;
}) {
    const [openKeys, setOpenKeys] = useState<string[]>([]);
    const [treeOpen, setTreeOpen] = useState(true);
    const listId = useId();
    if (!contexts.length)
        return null;
    return <>
      <div className="nav-section-head">
        <button type="button" className="nav-section-toggle" aria-expanded={treeOpen} aria-controls={listId}
          title={treeOpen ? '收起项目列表' : '展开项目列表'} onClick={() => setTreeOpen(open => !open)}>
          <Typography.Text className="nav-section-title" type="secondary">项目列表</Typography.Text>
          <span className="nav-section-count">{contexts.length}</span>
        </button>
      </div>
      {treeOpen && <ul className="project-tree" id={listId} aria-label="已注册项目">{contexts.map(context => <ProjectRow key={context.context_key}
        context={context} expanded={openKeys.includes(context.context_key)} selected={context.context_key === selectedKey}
        selectedTask={selectedTask} hasIssue={issueProjectIds?.has(context.project_id)} revision={revision}
        onToggle={() => setOpenKeys(old => old.includes(context.context_key)
            ? old.filter(key => key !== context.context_key)
            : [...old, context.context_key])}
        onOpenProject={() => onOpenProject(context.context_key)}
        onOpenTask={taskId => onOpenTask(context.context_key, taskId)}/>)}</ul>}
    </>;
}
