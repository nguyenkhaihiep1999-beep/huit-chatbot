/**
 * Public Hook Facade - Common & Shared Hooks
 * Re-exports shared utility hooks and global application state hooks.
 */
export { useDebounce } from '../src/shared/hooks/useDebounce';
export { useLocalStorage } from '../src/shared/hooks/useLocalStorage';
export { useTheme } from '../src/features/theme/hooks/useTheme';
export { useChatHistory } from '../src/features/history/hooks/useChatHistory';
export { useVisualLightbox } from '../src/features/admission-visuals/hooks/useVisualLightbox';
