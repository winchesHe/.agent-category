// 零依赖 JSON Schema 子集校验器。
// 只实现本项目 schema 用到的关键字，避免为单个 skill 引入 Ajv。
// 支持：type / const / enum / pattern / required / properties / items /
//       additionalProperties / minItems / minLength / minimum / maximum / $ref

function typeOf(value) {
  if (value === null) return 'null';
  if (Array.isArray(value)) return 'array';
  if (Number.isInteger(value)) return 'integer';
  return typeof value;
}

function matchesType(value, expected) {
  const actual = typeOf(value);
  const list = Array.isArray(expected) ? expected : [expected];
  return list.some((type) => {
    if (type === 'number') return actual === 'number' || actual === 'integer';
    if (type === 'integer') return actual === 'integer';
    return actual === type;
  });
}

function resolveRef(ref, root) {
  if (!ref.startsWith('#/')) throw new Error(`unsupported $ref: ${ref}`);
  let node = root;
  for (const rawSegment of ref.slice(2).split('/')) {
    const segment = rawSegment.replace(/~1/g, '/').replace(/~0/g, '~');
    node = node?.[segment];
    if (node === undefined) throw new Error(`unresolvable $ref: ${ref}`);
  }
  return node;
}

export function validateAgainstSchema(data, schema, root = schema, pointer = '') {
  const errors = [];
  if (!schema || typeof schema !== 'object') return errors;

  if (schema.$ref) {
    return validateAgainstSchema(data, resolveRef(schema.$ref, root), root, pointer);
  }

  const at = pointer || '(root)';

  if ('const' in schema && data !== schema.const) {
    errors.push(`${at} must equal ${JSON.stringify(schema.const)}, got ${JSON.stringify(data)}`);
    return errors;
  }

  if (schema.enum && !schema.enum.includes(data)) {
    errors.push(`${at} must be one of ${schema.enum.join(' | ')}, got ${JSON.stringify(data)}`);
    return errors;
  }

  if (schema.type && !matchesType(data, schema.type)) {
    errors.push(`${at} must be type ${Array.isArray(schema.type) ? schema.type.join('|') : schema.type}, got ${typeOf(data)}`);
    return errors;
  }

  if (typeof data === 'string') {
    if (schema.pattern && !new RegExp(schema.pattern).test(data)) {
      errors.push(`${at} must match /${schema.pattern}/, got ${JSON.stringify(data)}`);
    }
    if (typeof schema.minLength === 'number' && data.length < schema.minLength) {
      errors.push(`${at} must have minLength ${schema.minLength}`);
    }
  }

  if (typeof data === 'number') {
    if (typeof schema.minimum === 'number' && data < schema.minimum) {
      errors.push(`${at} must be >= ${schema.minimum}, got ${data}`);
    }
    if (typeof schema.maximum === 'number' && data > schema.maximum) {
      errors.push(`${at} must be <= ${schema.maximum}, got ${data}`);
    }
  }

  if (Array.isArray(data)) {
    if (typeof schema.minItems === 'number' && data.length < schema.minItems) {
      errors.push(`${at} must have at least ${schema.minItems} item(s)`);
    }
    if (schema.items) {
      data.forEach((entry, index) => {
        errors.push(...validateAgainstSchema(entry, schema.items, root, `${at}[${index}]`));
      });
    }
  }

  if (data && typeof data === 'object' && !Array.isArray(data)) {
    for (const key of schema.required || []) {
      if (!(key in data)) errors.push(`${at} missing required field: ${key}`);
    }
    for (const [key, subSchema] of Object.entries(schema.properties || {})) {
      if (key in data) {
        errors.push(...validateAgainstSchema(data[key], subSchema, root, pointer ? `${pointer}.${key}` : key));
      }
    }
    if (schema.additionalProperties && typeof schema.additionalProperties === 'object') {
      const known = new Set(Object.keys(schema.properties || {}));
      for (const [key, value] of Object.entries(data)) {
        if (known.has(key)) continue;
        errors.push(
          ...validateAgainstSchema(value, schema.additionalProperties, root, pointer ? `${pointer}.${key}` : key),
        );
      }
    }
  }

  return errors;
}
