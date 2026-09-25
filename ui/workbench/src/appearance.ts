export type ThemePreference = 'system' | 'light' | 'dark';
export type ResolvedTheme = 'light' | 'dark';
export const THEME_KEY = 'tp-spec.workbench.theme';
export function normalizeTheme(value: unknown): ThemePreference {
    return value === 'light' || value === 'dark' ? value : 'system';
}
export function resolveTheme(preference: ThemePreference, systemDark: boolean): ResolvedTheme {
    return preference === 'system' ? systemDark ? 'dark' : 'light' : preference;
}
