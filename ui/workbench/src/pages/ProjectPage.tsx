import { Card, Collapse, Tag } from 'antd';
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

function systemPresentation(value: unknown): { label: string; color: string; raw: string; source: string } {
    const system = record(value), raw = text(system.status).toLowerCase(), identity = record(system.identity);
    const status = raw === 'available' ? { label: '可用', color: 'success' }
        : raw === 'unavailable' || raw === 'unconfigured' ? { label: raw === 'unconfigured' ? '未配置' : '不可用', color: 'warning' }
        : { label: raw ? '状态未确认' : '未记录', color: 'warning' };
    return { ...status, raw, source: text(system.registry) || text(identity.source) || '来源未记录' };
}

function ProjectSystemSummary({ name, value }: { name: string; value: unknown }) {
    const presentation = systemPresentation(value);
    return <section className="project-system-summary" aria-label={`${name}可用性`}>
      <div className="project-system-summary-heading"><h3>{name}</h3><Tag color={presentation.color} title={presentation.raw || '未记录'}>{presentation.label}</Tag></div>
      <p className="muted">来源：{presentation.source}</p>
      <Collapse className="project-system-details" size="small" items={[{ key: 'fields', label: `查看${name}全部字段`, children: <Fields value={value}/> }]}/>
    </section>;
}

export function ProjectPage({ context, read, onSelectTask }: {
    context?: Context;
    read: ReadState<Envelope<ProjectData>>;
    onSelectTask: (id: string) => void;
}) {
    if (!context)
        return <div className="page project-page"><div className="page-heading"><div><span className="eyebrow">项目总览</span><h2>尚未选择项目</h2></div></div>
        <Empty title="先选择项目与工作区">从左侧项目列表展开一个项目，或点它的「项目总览」。只展示已注册的真实上下文；工作台不会创建项目、任务或 Runtime。</Empty></div>;
    const data = read.data?.data;
    const project = record(data?.project);
    const projectId = text(project.project_id) || context.project_id;
    const runtime = runtimePresentation(project.runtime_status);
    const version = versionPresentation(project);
    const taskIndexAvailable = !!data && runtime.raw === 'available' && Array.isArray(data.task_index);
    return <div className="page project-page">
      <div className="page-heading project-overview-heading">
        <div><span className="eyebrow">项目总览</span><h2>{text(project.name) || context.name} {projectId && <small className="project-id"><code>{projectId}</code></small>}</h2>
          <div className="project-overview-status" aria-label="项目状态">
            <span>Runtime <Tag color={runtime.color} title={runtime.raw || '未记录'}>{runtime.label}</Tag></span>
            <span>版本 <Tag color={version.color}>{version.label}</Tag></span>
          </div>
        </div>
      </div>
      <ReadStatus {...read}/>
      {data && <>
        <Problems items={data.problems}/>
        <Card className="project-task-progress" size="small" title="任务进展">
          <TaskIndex key={context.context_key} rows={taskIndexAvailable ? data.task_index : []} available={taskIndexAvailable} onSelect={onSelectTask}/>
          <Collapse className="compact-details project-statistics" size="small" items={[{ key: 'statistics', label: '已记录状态统计', children: <>{!!text(data.summary) && <p className="project-task-summary muted">{text(data.summary)}</p>}<Fields value={data.task_statistics}/></> }]}/>
        </Card>
        <Card className="project-details" size="small" title="项目资料与环境详情">
          <Collapse className="project-identity-details" size="small" items={[{ key: 'identity', label: '身份、Binding、数据库与注册表', children: <Fields value={{ ...project, registry: data.registry }}/> }]}/>
          <div className="project-system-summaries">
            <ProjectSystemSummary name="Wiki" value={data.wiki}/>
            <ProjectSystemSummary name="Knowledge" value={data.knowledge}/>
          </div>
        </Card>
      </>}
    </div>;
}
