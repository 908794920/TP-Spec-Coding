import { useRef } from 'react';
import { Alert, Button, Card, Tag } from 'antd';
import { Fields, Empty, Problems, ReadStatus } from '../components/Facts';
import { TaskIndex } from '../components/TaskIndex';
import { record, text } from '../facts';
import type { Context, Envelope, ProjectData, ReadState } from '../types';

function runtimePresentation(value: unknown): { label: string; color: string; raw: string } {
    const raw = text(value).toLowerCase();
    if (raw === 'available')
        return { label: '可用', color: 'success', raw };
    if (raw === 'unavailable' || raw === 'unreadable')
        return { label: raw === 'unreadable' ? '不可读取' : '不可用', color: 'error', raw };
    if (raw === 'unconfigured')
        return { label: '未配置', color: 'warning', raw };
    return { label: raw ? '状态未确认' : '未记录', color: 'warning', raw };
}

function versionPresentation(project: Record<string, unknown>): { label: string; color: string } {
    const base = text(project.base_version), contract = text(project.contract_version);
    if (!base || !contract)
        return { label: '版本未确认', color: 'warning' };
    return base === contract
        ? { label: `版本一致 · ${base}`, color: 'success' }
        : { label: `版本不一致 · ${base} / ${contract}`, color: 'error' };
}

function systemAvailability(value: unknown): string {
    const raw = text(record(value).status).toLowerCase();
    if (raw === 'available') return '可用';
    if (raw === 'unavailable') return '不可用';
    if (raw === 'unconfigured') return '未配置';
    return raw ? '状态未确认' : '未记录';
}

function uniqueContextFields(context: Context | null | undefined, project: Record<string, unknown>, registry: unknown): Record<string, string> {
    if (!context) return {};
    const same = (left: string, right: unknown) => left.replaceAll('\\', '/').toLowerCase() === text(right).replaceAll('\\', '/').toLowerCase();
    const result: Record<string, string> = { context_key: context.context_key };
    if (context.project_id && !same(context.project_id, project.project_id)) result.context_project_id = context.project_id;
    if (context.name && !same(context.name, project.name)) result.context_name = context.name;
    if (context.project_root && !same(context.project_root, project.root_path)) result.context_project_root = context.project_root;
    if (context.workspace_root && !same(context.workspace_root, project.root_path) && !same(context.workspace_root, context.project_root)) result.context_workspace_root = context.workspace_root;
    if (context.db_path && !same(context.db_path, project.runtime_db)) result.context_db_path = context.db_path;
    if (context.registry_path && !same(context.registry_path, record(registry).path)) result.context_registry_path = context.registry_path;
    if (context.source && !same(context.source, project.identity_source)) result.context_source = context.source;
    return result;
}

const environmentImpact: Record<string, string> = {
    REGISTRY_INVALID: '项目注册信息不可读取。',
    RUNTIME_UNAVAILABLE: 'Runtime 不可用，任务列表未取得。',
    RUNTIME_READ_ERROR: 'Runtime 读取失败，任务列表未取得。',
    RUNTIME_UNREGISTERED: '当前项目未确认 Runtime，任务列表未取得。',
    PROJECT_VERSION_MISMATCH: '项目 Base 与当前工作台的版本不一致。',
    WIKI_RESOLVER_ERROR: 'Wiki 项目归属未取得。',
    KNOWLEDGE_RESOLVER_ERROR: '知识库项目范围未取得。',
    CONTENT_RESOLVER_ERROR: 'Wiki 与知识库的项目范围未取得。',
};

export function ProjectPage({ context, read, notesWritable, onSelectTask, onNoteSaved }: {
    context?: Context;
    read: ReadState<Envelope<ProjectData>>;
    notesWritable: boolean;
    onSelectTask: (id: string) => void;
    onNoteSaved: () => void;
}) {
    const environment = useRef<HTMLDetailsElement>(null);
    if (!context)
        return <div className="page project-page"><div className="page-heading"><div><span className="eyebrow">项目总览</span><h2>尚未选择项目</h2></div></div>
        <Empty title="先选择项目与工作区">从左侧项目列表打开项目总览。</Empty></div>;
    const data = read.data?.data;
    const project = record(data?.project);
    const projectId = text(project.project_id) || context.project_id;
    const runtime = runtimePresentation(project.runtime_status);
    const version = versionPresentation(project);
    const taskIndexAvailable = !!data && runtime.raw === 'available' && Array.isArray(data.task_index);
    const issues = data?.problems ?? [];
    const environmentIssues = issues.filter(problem => environmentImpact[problem.code]);
    function showEnvironment() {
        const details = environment.current;
        if (!details) return;
        details.open = true;
        const summary = details.querySelector('summary');
        summary?.focus({ preventScroll: true });
        summary?.scrollIntoView({ block: 'center' });
    }
    return <div className="page project-page">
      <div className="page-heading project-overview-heading">
        <div><span className="eyebrow">项目总览</span><h2>{text(project.name) || context.name} {projectId && <small className="project-id"><code>{projectId}</code></small>}</h2>
          <div className="project-overview-status" aria-label="项目状态">
            <span>Runtime <Tag color={runtime.color} title={runtime.raw || '未记录'}>{runtime.label}</Tag></span>
            <span>版本 <Tag color={version.color}>{version.label}</Tag></span>
          </div>
        </div>
        <ReadStatus {...read} showDetails={false}/>
      </div>
      {data && <>
        {environmentIssues.length > 0 && <Alert type="warning" showIcon title="项目环境异常"
          description={<ul>{environmentIssues.map(({ code }) => <li key={code}>{environmentImpact[code]} <Button size="small" type="link" onClick={showEnvironment}>查看环境详情</Button></li>)}</ul>}/>}
        <Problems items={issues.filter(problem => !environmentImpact[problem.code])}/>
        <Card className="project-task-progress" size="small" title="任务进展">
          <TaskIndex key={context.context_key} contextKey={context.context_key} rows={taskIndexAvailable ? data.task_index : []}
            available={taskIndexAvailable} notesWritable={notesWritable} onSelect={onSelectTask} onNoteSaved={onNoteSaved}/>
        </Card>
        <details className="project-details" key={context.context_key} ref={environment}>
          <summary>环境详情</summary>
          {environmentIssues.length > 0 && <Problems items={environmentIssues}/>}
          <Fields value={{ ...project, registry: data.registry, wiki: systemAvailability(data.wiki), knowledge: systemAvailability(data.knowledge),
            ...uniqueContextFields(read.data?.context, project, data.registry),
            ...(read.data?.read.note ? { read_note: read.data.read.note } : {}),
            ...(read.data?.read.consistency ? { read_consistency: read.data.read.consistency } : {}),
            ...(read.data?.read.task_revision ? { read_task_revision: read.data.read.task_revision } : {}) }}
            labels={{ context_project_id: '上下文项目 ID', context_name: '上下文名称', context_project_root: '上下文项目根',
              context_workspace_root: '上下文工作区', context_db_path: '上下文 Runtime', context_registry_path: '上下文注册表',
              context_source: '上下文来源', read_note: '读取说明', read_consistency: '一致性边界', read_task_revision: '账本观察标识' }}/>
        </details>
      </>}
    </div>;
}
