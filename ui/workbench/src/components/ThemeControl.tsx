import { Button, Dropdown } from 'antd';
import { CheckOutlined, DesktopOutlined, MoonOutlined, SunOutlined } from '@ant-design/icons';
import { useAppearance } from '../theme';
import { normalizeTheme } from '../appearance';
const labels = { system: '跟随系统', light: '亮色', dark: '暗色' } as const;
export function ThemeControl() {
    const { preference, resolved, setPreference } = useAppearance();
    const icon = preference === 'system' ? <DesktopOutlined/> : resolved === 'dark' ? <MoonOutlined/> : <SunOutlined/>;
    return <Dropdown trigger={['click']} placement="bottomRight" menu={{ selectable: true, selectedKeys: [preference],
        onClick: ({ key }) => setPreference(normalizeTheme(key)),
        items: Object.entries(labels).map(([key, label]) => ({ key, label, icon: key === preference ? <CheckOutlined/> : <span className="theme-check-space"/> })) }}>
      <Button type="text" className="theme-toggle" icon={icon} title={`主题：${labels[preference]}`}
        aria-label={`主题设置：${labels[preference]}（当前${labels[resolved]}）`}/>
    </Dropdown>;
}
