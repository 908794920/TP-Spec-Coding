import { Alert, Card, Tabs } from 'antd';
import { record, text } from '../facts';
import { Disclosure, Fields, Problems, ReadStatus } from '../components/Facts';
import { SkillTopology } from '../components/SkillTopology';
import type { Envelope, GlobalData, Health, ReadState } from '../types';

const groups = [['base', '安装与基座'], ['wiki', 'Wiki'], ['knowledge', 'Knowledge'], ['skill_topology', '能力定义与来源']] as const;
const carriedLabels = { path: '注册表路径', status: '解析器状态', user_root: '用户根目录', python_executable: '本机 Python 解释器' };

export function GlobalConfigPage({ read, health }: {
    read: ReadState<Envelope<GlobalData>>;
    health: ReadState<Health>;
}) {
    const data = read.data?.data;
    const base = record(data?.base), resolver = record(data?.resolver);
    const configError = text(base.configuration_error);
    const installed = text(base.base_version), current = text(base.contract_version);
    const mismatch = base.configured === true && !!(installed && current && installed !== current);
    const { workspaces: _records, count: _count, configured: _configured, error: workspaceError, ...workspaceFacts } = record(data?.workspace);
    const { configuration_error: _error, ...baseValues } = base;
    const baseFacts = { ...baseValues, ...workspaceFacts, status: resolver.status, path: record(data?.registry).path,
        user_root: data?.user_root, python_executable: health.data?.python_executable,
        ...(configError ? { configuration_error: configError } : {}), ...(workspaceError ? { error: workspaceError } : {}) };
    const baseStatus = base.configured === false ? '安装配置未声明 Base'
        : base.valid === true && resolver.status === 'healthy' ? 'Base 可用，解析器正常' : 'Base 状态待核实';
    return <div className="page config-page">
      <div className="page-heading"><div><span className="eyebrow">全局配置</span><h2>配置值与来源</h2></div></div>
      <ReadStatus {...read}/>
      {data && <>
        {configError && <Alert type="error" showIcon title="安装配置未取得" description={configError}/>}
        {mismatch && <Alert type="warning" showIcon title="Base 版本与当前工作台不一致"
          description={<>Base {installed} · 工作台 {current}</>}/>}
        <Problems items={data.problems.filter(problem => !(configError && ['INSTALLATION_INVALID', 'INSTALLATION_MISSING'].includes(problem.code)) &&
          !(mismatch && problem.code === 'BASE_VERSION_MISMATCH'))}/>
        <Tabs className="config-tabs" defaultActiveKey={groups[0][0]} items={groups.map(([key, label]) => {
          const source = record(data[key]);
          return { key, label, children: <Card size="small">{key === 'skill_topology'
            ? <SkillTopology value={data.skill_topology} loading={read.loading} readError={read.error}/>
            : key === 'base' ? <div className="config-base">
                <section className="config-base-group">
                  {!configError && <h3>{baseStatus}</h3>}
                  {!mismatch && base.configured === true && installed && installed === current && <span>版本一致 · {current}</span>}
                  {base.configured !== true && current && <span>当前工作台 {current}</span>}
                  {base.configured === true && (!installed || !current) && <span>版本未取得</span>}
                </section>
                <Disclosure label="路径与来源等详细信息" className="config-base-details">
                  <Fields value={baseFacts} labels={carriedLabels}/>
                </Disclosure>
              </div> : <Fields value={{ ...source,
                path: configError ? '未取得' : source.configured === false ? '未声明' : source.path,
                configured: configError ? '未取得' : source.configured === false ? '未声明' : source.configured,
                ...(configError ? { exists: '未取得', status: '未取得' } : {}) }}/>}</Card> };
        })}/>
      </>}
    </div>;
}
