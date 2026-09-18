import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, relative, resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const sourceRoot = resolve(frontendRoot, 'src');

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
  const components = files.filter((path) => rel(path).includes('/components/'));
  const hooks = files.filter((path) => rel(path).includes('/hooks/'));
  const featureApis = files.filter((path) => /src\/features\/[^/]+\/api\//.test(rel(path)));

  it('keeps endpoints and transports out of components', () => {
    expect(violations(components, /\bfetch\s*\(|\bapiClient\b|["'`]\/api\/|from\s+["'][^"']*\/api\//)).toEqual([]);
  });

  it('keeps endpoints and shared transport out of hooks', () => {
    expect(violations(hooks, /\bfetch\s*\(|\bapiClient\b|["'`]\/api\/|from\s+["'][^"']*shared\/api/)).toEqual([]);
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
});
