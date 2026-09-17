import { useEffect } from 'react';
import { useLocalStorage } from '../../../shared/hooks/useLocalStorage';
import { ThemeMode } from '../../../shared/types/common.types';

export function useTheme() {
  const [theme, setTheme] = useLocalStorage<ThemeMode>('huit_theme_mode', 'light');

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme((prev) => (prev === 'light' ? 'dark' : 'light'));
  };

  return { theme, toggleTheme, setTheme };
}
