/**
 * Public Hook Facade - Artifacts Feature
 * Re-exports artifact lifecycle hooks and contract types.
 */
export {
  useArtifactWorkflow,
  type UseArtifactWorkflowOptions,
  type UseArtifactWorkflowReturn,
} from '../src/features/artifacts/hooks/useArtifactWorkflow';

export {
  useArtifactExport,
  type UseArtifactExportReturn,
} from '../src/features/artifacts/hooks/useArtifactExport';

export {
  useArtifactUpscale,
  type UseArtifactUpscaleOptions,
  type UseArtifactUpscaleReturn,
} from '../src/features/artifacts/hooks/useArtifactUpscale';

export { useArtifactActions } from '../src/features/artifacts/hooks/useArtifactActions';
