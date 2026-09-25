import { createRoot } from 'react-dom/client';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './App';
import { AppearanceContext, useWorkbenchTheme } from './theme';
import './styles/tokens.css';
import './styles/workbench.css';

function Root() {
    const { theme, appearance } = useWorkbenchTheme();
    return <AppearanceContext.Provider value={appearance}><ConfigProvider locale={zhCN} theme={theme}><App /></ConfigProvider></AppearanceContext.Provider>;
}

const root = document.getElementById('root');
if (!root) throw new Error('工作台挂载点不存在');
createRoot(root).render(<Root />);
