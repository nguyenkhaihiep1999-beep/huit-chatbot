import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, relative, resolve } from 'node:path';
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
});
