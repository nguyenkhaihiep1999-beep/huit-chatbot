export type JsonSchema = Record<string, unknown>;

export interface ContractValidationResult {
  valid: boolean;
  errors: string[];
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function sameValue(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function resolveRef(root: JsonSchema, ref: string): JsonSchema | null {
  if (!ref.startsWith('#/')) return null;
  let current: unknown = root;
  for (const rawPart of ref.slice(2).split('/')) {
    const part = rawPart.replaceAll('~1', '/').replaceAll('~0', '~');
    if (!isObject(current) || !(part in current)) return null;
    current = current[part];
  }
  return isObject(current) ? current : null;
}

function matchesType(type: string, value: unknown): boolean {
  switch (type) {
    case 'null': return value === null;
    case 'object': return isObject(value);
    case 'array': return Array.isArray(value);
    case 'string': return typeof value === 'string';
    case 'number': return typeof value === 'number' && Number.isFinite(value);
    case 'integer': return typeof value === 'number' && Number.isInteger(value);
    case 'boolean': return typeof value === 'boolean';
    default: return false;
  }
}

function validateNode(schema: JsonSchema, value: unknown, root: JsonSchema, path: string): string[] {
  const errors: string[] = [];

  if (typeof schema.$ref === 'string') {
    const resolved = resolveRef(root, schema.$ref);
    return resolved ? validateNode(resolved, value, root, path) : [`${path}: unresolved $ref`];
  }

  if (Array.isArray(schema.allOf)) {
    for (const part of schema.allOf) {
      if (isObject(part)) errors.push(...validateNode(part, value, root, path));
    }
  }

  if (Array.isArray(schema.anyOf)) {
    const matched = schema.anyOf.some((part) => isObject(part) && validateNode(part, value, root, path).length === 0);
    if (!matched) errors.push(`${path}: does not match any allowed schema`);
    return errors;
  }

  if (Array.isArray(schema.oneOf)) {
    const matches = schema.oneOf.filter(
      (part) => isObject(part) && validateNode(part, value, root, path).length === 0
    ).length;
    if (matches !== 1) errors.push(`${path}: must match exactly one schema`);
    return errors;
  }

  if ('const' in schema && !sameValue(value, schema.const)) {
    errors.push(`${path}: unexpected constant value`);
  }
  if (Array.isArray(schema.enum) && !schema.enum.some((item) => sameValue(item, value))) {
    errors.push(`${path}: value is not in enum`);
  }

  const allowedTypes = typeof schema.type === 'string'
    ? [schema.type]
    : Array.isArray(schema.type)
      ? schema.type.filter((item): item is string => typeof item === 'string')
      : [];
  if (allowedTypes.length > 0 && !allowedTypes.some((type) => matchesType(type, value))) {
    errors.push(`${path}: invalid type`);
    return errors;
  }

  if (typeof value === 'string') {
    if (typeof schema.minLength === 'number' && value.length < schema.minLength) {
      errors.push(`${path}: shorter than minLength`);
    }
    if (typeof schema.maxLength === 'number' && value.length > schema.maxLength) {
      errors.push(`${path}: longer than maxLength`);
    }
    if (typeof schema.pattern === 'string' && !(new RegExp(schema.pattern).test(value))) {
      errors.push(`${path}: pattern mismatch`);
    }
  }

  if (typeof value === 'number') {
    if (typeof schema.minimum === 'number' && value < schema.minimum) errors.push(`${path}: below minimum`);
    if (typeof schema.maximum === 'number' && value > schema.maximum) errors.push(`${path}: above maximum`);
  }

  if (Array.isArray(value) && isObject(schema.items)) {
    value.forEach((item, index) => errors.push(...validateNode(schema.items as JsonSchema, item, root, `${path}[${index}]`)));
  }

  const hasObjectRules = isObject(schema.properties) || Array.isArray(schema.required) || schema.additionalProperties !== undefined;
  if (isObject(value) && hasObjectRules) {
    const properties = isObject(schema.properties) ? schema.properties : {};
    const required = Array.isArray(schema.required)
      ? schema.required.filter((item): item is string => typeof item === 'string')
      : [];
    for (const key of required) {
      if (!(key in value)) errors.push(`${path}.${key}: required`);
    }
    for (const [key, child] of Object.entries(value)) {
      const childSchema = properties[key];
      if (isObject(childSchema)) {
        errors.push(...validateNode(childSchema, child, root, `${path}.${key}`));
      } else if (schema.additionalProperties === false) {
        errors.push(`${path}.${key}: additional property`);
      }
    }
  }

  return errors;
}

export function validateJsonSchema(schema: JsonSchema, value: unknown): ContractValidationResult {
  const errors = validateNode(schema, value, schema, '$');
  return { valid: errors.length === 0, errors };
}

export function assertJsonSchema(schema: JsonSchema, value: unknown, contractName: string): void {
  const result = validateJsonSchema(schema, value);
  if (!result.valid) {
    throw new Error(`CONTRACT_VIOLATION:${contractName}:${result.errors.slice(0, 3).join('|')}`);
  }
}
