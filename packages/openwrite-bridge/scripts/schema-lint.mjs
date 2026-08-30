/**
 * Minimal JSON Schema subset validator mirroring OpenWrite
 * `tools/schema_lint.py` (type/const/enum/required/properties/items/
 * minProperties/minimum/maximum/pattern/minLength/disallowed/
 * additionalProperties:false). Keep both sides in lockstep.
 */

const TYPES = {
  object: 'object',
  array: 'array',
  string: 'string',
  number: 'number',
  integer: 'integer',
  boolean: 'boolean',
  null: 'null',
}

function typeOk(value, name) {
  if (name === 'array') return Array.isArray(value)
  if (name === 'null') return value === null
  if (name === 'integer') return Number.isInteger(value) && typeof value !== 'boolean'
  if (name === 'number') return typeof value === 'number' && !Number.isNaN(value)
  return typeof value === TYPES[name]
}

export function validateSchema(value, schema, path = '$') {
  const errors = []
  const fail = message => errors.push(`${path}: ${message}`)

  if (schema.type !== undefined) {
    const names = Array.isArray(schema.type) ? schema.type : [schema.type]
    if (!names.some(name => typeOk(value, name))) {
      fail(`expected type ${names.join('/')}, got ${typeof value}`)
      return errors
    }
  }

  if (schema.const !== undefined && value !== schema.const) {
    fail(`expected const ${JSON.stringify(schema.const)}, got ${JSON.stringify(value)}`)
  }

  if (schema.enum !== undefined && !schema.enum.includes(value)) {
    fail(`${JSON.stringify(value)} not in enum ${JSON.stringify(schema.enum)}`)
  }

  if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
    for (const key of schema.required ?? []) {
      if (!(key in value)) fail(`missing required property '${key}'`)
    }
    for (const key of schema.disallowed ?? []) {
      if (key in value) fail(`forbidden credential-like property '${key}' must not appear`)
    }
    const properties = schema.properties ?? {}
    for (const [key, sub] of Object.entries(value)) {
      if (key in properties) {
        errors.push(...validateSchema(sub, properties[key], `${path}.${key}`))
      } else if (schema.additionalProperties === false) {
        fail(`unexpected property '${key}'`)
      } else if (schema.additionalProperties !== undefined && typeof schema.additionalProperties === 'object') {
        errors.push(...validateSchema(sub, schema.additionalProperties, `${path}.${key}`))
      }
    }
    if (schema.minProperties !== undefined && Object.keys(value).length < schema.minProperties) {
      fail(`expected at least ${schema.minProperties} properties, got ${Object.keys(value).length}`)
    }
  }

  if (Array.isArray(value) && schema.items !== undefined) {
    value.forEach((item, index) => {
      errors.push(...validateSchema(item, schema.items, `${path}[${index}]`))
    })
  }

  if (typeof value === 'number' && !Number.isNaN(value)) {
    if (schema.minimum !== undefined && value < schema.minimum) fail(`${value} is less than minimum ${schema.minimum}`)
    if (schema.maximum !== undefined && value > schema.maximum) fail(`${value} is greater than maximum ${schema.maximum}`)
  }

  if (typeof value === 'string') {
    if (schema.minLength !== undefined && value.length < schema.minLength) fail(`string shorter than minLength ${schema.minLength}`)
    if (schema.pattern !== undefined && new RegExp(schema.pattern).test(value) === false) {
      fail(`'${value}' does not match pattern '${schema.pattern}'`)
    }
  }

  return errors
}

export function validateOrRaise(value, schema) {
  const errors = validateSchema(value, schema)
  if (errors.length > 0) throw new Error(errors.join('; '))
}
