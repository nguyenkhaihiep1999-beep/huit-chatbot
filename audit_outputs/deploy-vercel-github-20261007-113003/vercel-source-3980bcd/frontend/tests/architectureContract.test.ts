import { describe, expect, it } from 'vitest';
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, relative, resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const sourceRoot = resolve(frontendRoot, 'src');
const facadeRoot = resolve(frontendRoot, 'hooks');

function sourceFiles(root: string): string[] {
  return readdirSync(root).flatMap((name) => {
    const path = resolve(root, name);
    return statSync(path).isDirectory() ? sourceFiles(path) : /\.tsx?$/.test(path) ? [path] : [];
  });
}

function rel(path: string): string {
  return relative(frontendRoot, path).replaceAll('\\', '/');
}

function violations(files: string[], forbidden: RegExp): string[] {
  return files
    .filter((path) => forbidden.test(readFileSync(path, 'utf8')))
    .map(rel);
}

describe('LTX frontend dependency contract', () => {
  const files = sourceFiles(sourceRoot);
  const facadeFiles = sourceFiles(facadeRoot);
  const components = files.filter((path) => rel(path).includes('/components/'));
  const hooks = [...files.filter((path) => rel(path).includes('/hooks/')), ...facadeFiles];
  const featureApis = files.filter((path) => /src\/features\/[^/]+\/api\//.test(rel(path)));

  it('keeps endpoints and transports out of components', () => {
    expect(violations(components, /\bfetch\s*\(|\bapiClient\b|["'`]\/api\/|from\s+["'][^"']*\/api\//)).toEqual([]);
  });

  it('keeps endpoints and shared transport out of hooks and facades', () => {
    expect(violations(hooks, /\bfetch\s*\(|\bapiClient\b|["'`]\/api\/|from\s+["'][^"']*shared\/api/)).toEqual([]);
  });

  it('ensures public hook facade contains only pure re-exports and no stateful logic or direct transports', () => {
    expect(facadeFiles.length).toBeGreaterThanOrEqual(7);
    // Facade tuyệt đối không chứa hook implementation (useState, useEffect, ...) hay fetch
    expect(violations(facadeFiles, /\buseState\s*\(|\buseEffect\s*\(|\buseReducer\s*\(|\buseRef\s*\(/)).toEqual([]);
    for (const path of facadeFiles) {
      const content = readFileSync(path, 'utf8');
      expect(content).toMatch(/export\s+(?:\{|\*)/);
    }
  });

  it('allows fetch only in the shared HTTP client', () => {
    const offenders = files
      .filter((path) => rel(path) !== 'src/shared/api/httpClient.ts')
      .filter((path) => /\bfetch\s*\(/.test(readFileSync(path, 'utf8')))
      .map(rel);
    expect(offenders).toEqual([]);
  });

  it('keeps feature API modules free of React and UI imports', () => {
    expect(violations(featureApis, /from\s+["']react["']|\/components\/|\/hooks\//)).toEqual([]);
  });

  it('prevents shared code from importing features', () => {
    const shared = files.filter((path) => rel(path).startsWith('src/shared/'));
    expect(violations(shared, /from\s+["'][^"']*features\//)).toEqual([]);
  });

  it('forces session, chat request and NDJSON boundaries through canonical schema validators', () => {
    const sessionApi = readFileSync(resolve(sourceRoot, 'features/session/api/sessionApi.ts'), 'utf8');
    const chatApi = readFileSync(resolve(sourceRoot, 'features/chat/api/chatApi.ts'), 'utf8');
    const parser = readFileSync(resolve(sourceRoot, 'features/chat/utils/ndjsonParser.ts'), 'utf8');
    const hook = readFileSync(resolve(sourceRoot, 'features/chat/hooks/useChatStream.ts'), 'utf8');
    expect(sessionApi).toContain('parseSessionBootstrapResponse');
    expect(chatApi).toContain('assertChatRequest');
    expect(parser).toContain('parseChatStreamEvent');
    expect(hook).toContain('parseNDJSONStream');
  });

  it('keeps frontend schema copies byte-semantically synchronized with backend canonical schemas', () => {
    const backendRoot = resolve(frontendRoot, '../backend/json_schemas');
    const registry = JSON.parse(readFileSync(resolve(backendRoot, 'registry.json'), 'utf8')) as {
      contracts: Array<{ schema_id: string; version: string; file: string; frontend: boolean }>;
    };
    const generatedRoot = resolve(sourceRoot, 'shared/contracts/schemas');
    const generatedManifest = JSON.parse(readFileSync(resolve(generatedRoot, 'manifest.json'), 'utf8')) as {
      contracts: Array<{ schema_id: string; version: string; file: string; sha256: string }>;
    };

    const canonicalize = (value: unknown): unknown => {
      if (Array.isArray(value)) return value.map(canonicalize);
      if (value && typeof value === 'object') {
        return Object.fromEntries(
          Object.entries(value as Record<string, unknown>)
            .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
            .map(([key, item]) => [key, canonicalize(item)])
        );
      }
      return value;
    };

    const exposed = registry.contracts.filter((entry) => entry.frontend);
    expect(generatedManifest.contracts).toHaveLength(exposed.length);
    for (const entry of exposed) {
      const generated = generatedManifest.contracts.find(
        (item) => item.schema_id === entry.schema_id && item.version === entry.version
      );
      expect(generated).toBeDefined();
      const canonicalDocument = JSON.parse(readFileSync(resolve(backendRoot, entry.file), 'utf8'));
      const generatedDocument = JSON.parse(readFileSync(resolve(generatedRoot, generated!.file), 'utf8'));
      expect(generatedDocument).toEqual(canonicalDocument);
      const semanticJson = JSON.stringify(canonicalize(canonicalDocument));
      expect(createHash('sha256').update(semanticJson, 'utf8').digest('hex')).toBe(generated!.sha256);
    }
  });

  describe('Public Hook Facade Architecture Contract (Phase 3 & Phase 4)', () => {
    it('1. ensures frontend/hooks exists strictly outside src', () => {
      expect(existsSync(facadeRoot)).toBe(true);
      expect(facadeRoot.startsWith(sourceRoot)).toBe(false);
    });

    it('2. ensures no public hook facade is created at frontend/src/hooks', () => {
      expect(existsSync(resolve(sourceRoot, 'hooks'))).toBe(false);
    });

    it('3. ensures files in frontend/hooks contain only pure re-exports and type exports', () => {
      for (const file of facadeFiles) {
        const code = readFileSync(file, 'utf8')
          .replace(/\/\*[\s\S]*?\*\//g, '')
          .replace(/\/\/.*/g, '');
        const statements = code
          .split(';')
          .map((s) => s.trim())
          .filter(Boolean);
        for (const statement of statements) {
          expect(statement).toMatch(/^(?:export|import)\b/);
        }
      }
    });

    it('4. ensures frontend/hooks does not contain transports, URLs, endpoints, MongoDB, or components', () => {
      const forbidden = /\bfetch\s*\(|["'`]\/api\/|\bapiClient\b|\bendpoint\b|\bmongo(?:db)?\b|\bJSX\b|\bReact\.FC\b|<\/[a-zA-Z]+>/i;
      expect(violations(facadeFiles, forbidden)).toEqual([]);
    });

    it('5. ensures frontend/src/shared does not reverse-import from features or hooks', () => {
      const shared = files.filter((path) => rel(path).startsWith('src/shared/'));
      const forbidden = /from\s+["'][^"']*(?:features\/|(?:\.\.\/)+hooks\/)|["']@hooks(?:|\/[^"']*)["']/i;
      expect(violations(shared, forbidden)).toEqual([]);
    });

    it('6. ensures feature implementations do not depend backwards on facade to prevent cycles', () => {
      const featureImpls = files.filter((path) => /src\/features\/[^/]+\/(?:hooks|api)\//.test(rel(path)));
      const forbidden = /from\s+["'][^"']*(?:\.\.\/)+hooks\/(?:index|chat|session|artifacts|admin|voice|common)|["']@hooks["']/i;
      expect(violations(featureImpls, forbidden)).toEqual([]);
    });

    it('7. ensures all designated public hooks are exported from frontend/hooks/index.ts', async () => {
      const indexExports = await import('@hooks');
      const expectedHooks = [
        'useChatStream',
        'useConversation',
        'useSessionBootstrap',
        'useArtifactWorkflow',
        'useArtifactExport',
        'useArtifactUpscale',
        'useArtifactActions',
        'useAdminAuth',
        'useAdminDashboard',
        'useAdminOps',
        'useSpeechRecognition',
        'useSpeechSynthesis',
        'useDebounce',
        'useLocalStorage',
        'useTheme',
        'useChatHistory',
        'useVisualLightbox',
      ];
      for (const hookName of expectedHooks) {
        expect(typeof (indexExports as Record<string, unknown>)[hookName]).toBe('function');
      }
    });

    it('8. verifies TypeScript and Vite resolve @hooks alias correctly', () => {
      const rawTsConfig = readFileSync(resolve(frontendRoot, 'tsconfig.app.json'), 'utf8')
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/\/\/.*/g, '');
      const tsconfig = JSON.parse(rawTsConfig);
      expect(tsconfig.compilerOptions.paths?.['@hooks']).toContain('./hooks/index.ts');
      expect(tsconfig.include).toContain('hooks');

      const viteConfig = readFileSync(resolve(frontendRoot, 'vite.config.ts'), 'utf8');
      expect(viteConfig).toContain("'@hooks'");
    });

    it('9. verifies import graph between facade and features is strictly acyclic (no cycles)', () => {
      for (const file of facadeFiles) {
        const isIndex = rel(file) === 'hooks/index.ts';
        const content = readFileSync(file, 'utf8');
        const imports = [...content.matchAll(/from\s+['"]([^'"]+)['"]/g)].map((m) => m[1]);
        for (const imp of imports) {
          if (isIndex) {
            expect(imp).toMatch(/^\.\/(?:chat|session|artifacts|admin|voice|common)$/);
          } else {
            expect(imp).toMatch(/^\.\.\/src\/(?:features|shared)\//);
          }
        }
      }
    });

    it('10. enforces backend/json_schemas as the sole authoritative contract core', () => {
      const backendRoot = resolve(frontendRoot, '../backend/json_schemas');
      const registryPath = resolve(backendRoot, 'registry.json');
      expect(existsSync(registryPath)).toBe(true);

      const generatedRoot = resolve(sourceRoot, 'shared/contracts/schemas');
      const generatedManifest = JSON.parse(readFileSync(resolve(generatedRoot, 'manifest.json'), 'utf8')) as {
        generated_from: string;
        contracts: Array<{ schema_id: string; version: string; file: string; sha256: string }>;
      };

      // Provable single source of truth guarantee
      expect(generatedManifest.generated_from).toBe('backend/json_schemas/registry.json');
      expect(generatedManifest.contracts.length).toBeGreaterThanOrEqual(4);
    });

    it('11. (Gate 13) ensures public chat & session hooks utilize DTOs based directly on canonical contracts', () => {
      const ndjsonParserContent = readFileSync(
        resolve(sourceRoot, 'features/chat/utils/ndjsonParser.ts'),
        'utf8'
      );
      const sessionApiContent = readFileSync(
        resolve(sourceRoot, 'features/session/api/sessionApi.ts'),
        'utf8'
      );
      // ndjsonParser imports and validates parseChatStreamEvent from shared/contracts
      expect(ndjsonParserContent).toMatch(/import\s+.*parseChatStreamEvent.*from\s+['"].*shared\/contracts['"]/);
      // sessionApi imports and validates parseSessionBootstrapResponse from shared/contracts
      expect(sessionApiContent).toMatch(/import\s+.*parseSessionBootstrapResponse.*from\s+['"].*shared\/contracts['"]/);
    });
  });
});
