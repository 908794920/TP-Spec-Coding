import { Alert, Button, Tag } from 'antd';
import { DatabaseOutlined, ReadOutlined } from '@ant-design/icons';
import { explainValue, record, text } from '../facts';
import { Disclosure, Fields, Problems } from '../components/Facts';
import { SkillTopology } from '../components/SkillTopology';
import type { Envelope, GlobalData, Health, ReadState } from '../types';

const carriedLabels = { path: '注册表路径', status: '解析器状态', user_root: '用户根目录', python_executable: '本机 Python 解释器' };

export function GlobalConfigPage({ read, health, onNavigate }: {
    read: ReadState<Envelope<GlobalData>>;
    health: ReadState<Health>;
    onNavigate?: (page: 'wiki' | 'knowledge') => void;
}) {
    const data = read.data?.data;
    const base = record(data?.base), resolver = record(data?.resolver);
    const wiki = record(data?.wiki), knowledge = record(data?.knowledge);
    const configError = text(base.configuration_error);
    const installed = text(base.base_version), current = text(base.contract_version);
    const mismatch = base.configured === true && !!(installed && current && installed !== current);
    const { workspaces: _records, count: _count, configured: _configured, error: workspaceError, ...workspaceFacts } = record(data?.workspace);
    const { configuration_error: _error, ...baseValues } = base;
    const baseFacts = { ...baseValues, ...workspaceFacts, status: resolver.status, path: record(data?.registry).path,
        user_root: data?.user_root, python_executable: health.data?.python_executable,
        ...(configError ? { configuration_error: configError } : {}), ...(workspaceError ? { error: workspaceError } : {}) };
    const baseStatus = base.configured === false ? '安装配置未声明 Base'
        : base.valid === true && resolver.status === 'healthy' ? '本地配置读取正常' : 'Base 状态待核实';
    const baseOk = !configError && !mismatch && base.valid === true && resolver.status === 'healthy';
    return <div className="page config-page">
      <div className="page-heading config-flat-heading">
        <div>
          <h2>全局配置</h2>
          <p className="muted">查看本地安装基座路径、Wiki 与知识库配置入口，以及能力定义的父子归属与用途映射。</p>
        </div>
      </div>
      {data && <>
        {configError && <Alert type="error" showIcon title="安装配置未取得" description={configError}/>}
        {mismatch && <Alert type="warning" showIcon title="Base 版本与当前工作台不一致"
          description={<>Base {installed} · 工作台 {current}</>}/>}
        <Problems items={data.problems.filter(problem => !(configError && ['INSTALLATION_INVALID', 'INSTALLATION_MISSING'].includes(problem.code)) &&
          !(mismatch && problem.code === 'BASE_VERSION_MISMATCH'))}/>

        <div className="config-base">
          <section className="config-base-flat">
            <div className="config-base-head">
              <div><h3>安装与基座</h3></div>
              <span className={`project-inline-status is-${baseOk ? 'success' : 'warning'}`}>{baseStatus}</span>
            </div>
            <dl className="config-flat-grid">
              <div><dt>安装路径</dt><dd><code>{text(base.root) || text(health.data?.source_root) || '未记录'}</code></dd></div>
              <div><dt>基座版本</dt><dd><code>{!mismatch && base.configured === true && installed ? `TP-Spec Core ${installed}` : current || '版本未取得'}</code></dd></div>
              <div><dt>用户根目录</dt><dd><code>{text(data.user_root) || '未记录'}</code></dd></div>
              <div><dt>来源</dt><dd><code>{text(base.source) || explainValue('source', base.source) || '未声明'}</code> · {explainValue('status', resolver.status) || text(resolver.status) || '未记录'}</dd></div>
            </dl>
          </section>

          <div className="config-system-cards">
            <section className="config-system-card">
              <div className="config-system-head">
                <strong><ReadOutlined/> Wiki 配置</strong>
                <Tag color={wiki.status === 'available' ? 'success' : 'warning'}>{explainValue('status', wiki.status) || text(wiki.status) || '未声明'}</Tag>
              </div>
              <p className="muted">路径：<code>{configError ? '未取得' : wiki.configured === false ? '未声明' : text(wiki.path) || '未记录'}</code></p>
              <div className="config-system-links">
                {onNavigate && <Button size="small" type="link" onClick={() => onNavigate('wiki')}>前往 Wiki →</Button>}
              </div>
            </section>
            <section className="config-system-card">
              <div className="config-system-head">
                <strong><DatabaseOutlined/> 知识库配置</strong>
                <Tag color={knowledge.status === 'available' ? 'success' : 'warning'}>{explainValue('status', knowledge.status) || text(knowledge.status) || '未声明'}</Tag>
              </div>
              <p className="muted">路径：<code>{configError ? '未取得' : knowledge.configured === false ? '未声明' : text(knowledge.path) || '未记录'}</code></p>
              <div className="config-system-links">
                {onNavigate && <Button size="small" type="link" onClick={() => onNavigate('knowledge')}>前往知识库 →</Button>}
              </div>
            </section>
          </div>

          <section className="config-skills-section">
            <div className="config-skills-head">
              <h3>能力定义与来源</h3>
              <span className="muted">展开父行查看直属下级；点击稳定 ID 可高亮同名外部包在不同父节点下的归属与用途关系。</span>
            </div>
            <SkillTopology value={data.skill_topology} loading={read.loading} readError={read.error}/>
          </section>

          <Disclosure label="完整基座与工作区环境字段" className="config-base-details">
            <Fields value={baseFacts} labels={carriedLabels}/>
          </Disclosure>
        </div>
      </>}
    </div>;
}
