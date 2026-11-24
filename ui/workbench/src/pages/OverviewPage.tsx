import { ArrowRightOutlined, CompassOutlined, DatabaseOutlined, DeploymentUnitOutlined, FolderOpenOutlined, ReadOutlined, SearchOutlined, SettingOutlined } from '@ant-design/icons';
import { Button } from 'antd';
import { record, records, text } from '../facts';
import type { Context, Envelope, GlobalData, Health, ReadState } from '../types';

export function OverviewPage({ global, health, contexts, activeContext, onNavigate, onOpenProject, onTriggerSearch }: {
    global: ReadState<Envelope<GlobalData>>;
    health: ReadState<Health>;
    contexts: Context[];
    activeContext?: Context;
    onNavigate: (page: 'project' | 'task' | 'global' | 'wiki' | 'knowledge') => void;
    onOpenProject: (key: string) => void;
    onTriggerSearch: () => void;
}) {
    const data = global.data?.data;
    const base = record(data?.base);
    const wiki = record(data?.wiki);
    const knowledge = record(data?.knowledge);
    const registered = records(data?.registered_projects);
    const availableCount = registered.filter(p => p.runtime_status === undefined || p.runtime_status === 'available').length;
    const firstContext = activeContext ?? contexts[0];
    const baseVersion = text(base.base_version) || text(health.data?.version) || '—';

    const cards = [
        {
            key: 'project',
            icon: <FolderOpenOutlined/>,
            title: '项目总览',
            subtitle: '单项目任务池与运行体检',
            desc: '查看项目运行态、单行可展开环境异常提示与全量任务表，备注与责任人同屏可读，点击任一任务进入任务工作区。',
            footer: firstContext ? `${firstContext.name} · 共 ${contexts.length} 个已注册项目（可用 ${availableCount}）` : `共 ${contexts.length} 个已注册项目`,
            action: () => firstContext ? onOpenProject(firstContext.context_key) : onNavigate('project'),
        },
        {
            key: 'task',
            icon: <DeploymentUnitOutlined/>,
            title: '任务工作区',
            subtitle: '卡点横幅 + 生命周期步骤 + 角色卡片',
            desc: '以紧凑卡点横幅聚焦阻塞与解除条件，横向按生命周期排布步骤与角色卡片，点选后右侧抽屉核对活动与证据。',
            footer: activeContext ? `当前上下文：${activeContext.name}` : '从项目总览或左侧任务树打开任一任务',
            action: () => onNavigate('task'),
        },
        {
            key: 'wiki',
            icon: <ReadOutlined/>,
            title: 'Wiki',
            subtitle: '仓库状态与文档检索',
            desc: '按项目与仓库筛选，并列呈现可用仓库与暂不可读仓库来源，支持右侧正文阅读与短指纹核对。',
            footer: `状态：${text(wiki.status) === 'available' ? '可用' : text(wiki.status) || '未读取'}`,
            action: () => onNavigate('wiki'),
        },
        {
            key: 'knowledge',
            icon: <DatabaseOutlined/>,
            title: '知识库',
            subtitle: '检索命中、采用统计与口径边界',
            desc: '汇聚跨项目复盘与工程经验，严格区分「未取得（—）」与「真实的 0（有效空结果）」。',
            footer: `状态：${text(knowledge.status) === 'available' ? '可用' : text(knowledge.status) || '未读取'}`,
            action: () => onNavigate('knowledge'),
        },
        {
            key: 'global',
            icon: <SettingOutlined/>,
            title: '全局配置',
            subtitle: '安装基座信息与能力归属',
            desc: '同屏平铺本地安装路径、基座版本、Wiki/知识库入口与能力定义父子表，清晰区分管理归属与用途关联。',
            footer: `基座版本：${baseVersion}`,
            action: () => onNavigate('global'),
        },
        {
            key: 'search',
            icon: <SearchOutlined/>,
            title: '跨项目搜索 (Ctrl+K)',
            subtitle: '全站快速跳转任务',
            desc: '一键打开全站任务搜索面板，按 TASK ID 或标题检索所有已注册项目并直达任务工作区。',
            footer: `覆盖 ${contexts.length} 个已注册项目`,
            action: onTriggerSearch,
        },
    ];

    return <div className="page overview-page">
      <div className="overview-header">
        <div>
          <span className="eyebrow">TP-Spec 本地工作台 · 统一导航与视图总览</span>
          <h2>全站总览</h2>
          <p className="overview-subtitle">统一左侧全局入口与项目树、顶栏跨项目搜索与五页职责边界。所有数据均来自本地只读 Runtime 与配置文件。</p>
        </div>
        <div className="overview-header-actions">
          <Button icon={<SearchOutlined/>} onClick={onTriggerSearch}>打开跨项目搜索 (Ctrl+K)</Button>
          {firstContext && <Button type="primary" onClick={() => onOpenProject(firstContext.context_key)}>
            进入 {firstContext.name} <ArrowRightOutlined/>
          </Button>}
        </div>
      </div>

      <section className="overview-section" aria-label="五页职责与核心入口">
        <div className="overview-section-head">
          <h3><CompassOutlined/> 五页职责与核心入口</h3>
          <span className="muted">点击任一卡片直接切换至对应视图</span>
        </div>
        <div className="overview-card-grid">
          {cards.map(card => (
            <button type="button" key={card.key} className="overview-card" onClick={card.action}>
              <div className="overview-card-top">
                <span className="overview-card-icon">{card.icon}</span>
                <div className="overview-card-titles">
                  <strong>{card.title}</strong>
                  <span>{card.subtitle}</span>
                </div>
                <ArrowRightOutlined className="overview-card-arrow"/>
              </div>
              <p className="overview-card-desc">{card.desc}</p>
              <div className="overview-card-footer">{card.footer}</div>
            </button>
          ))}
        </div>
      </section>
    </div>;
}
