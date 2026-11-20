function typeOk(value, name) {
    switch (name) {
        case 'object': return value !== null && typeof value === 'object' && !Array.isArray(value);
        case 'array': return Array.isArray(value);
        case 'null': return value === null;
        case 'integer': return Number.isInteger(value);
        case 'number': return typeof value === 'number' && !Number.isNaN(value);
        default: return typeof value === name;
    }
}
/** Minimal JSON Schema subset validator mirroring OpenWrite
 * `tools/schema_lint.py` and `scripts/schema-lint.mjs`. */
export function validateSchema(value, schema, path = '$', root = schema) {
    const errors = [];
    const fail = (message) => errors.push(`${path}: ${message}`);
    const ref = schema['$ref'];
    if (typeof ref === 'string' && ref.startsWith('#/')) {
        let resolved = root;
        for (const part of ref.slice(2).split('/'))
            resolved = resolved?.[part];
        if (resolved && typeof resolved === 'object')
            return validateSchema(value, resolved, path, root);
    }
    const rawType = schema['type'];
    if (rawType !== undefined) {
        const names = Array.isArray(rawType) ? rawType.map(String) : [String(rawType)];
        if (!names.some(name => typeOk(value, name))) {
            const got = value === null ? 'null' : Array.isArray(value) ? 'array' : typeof value;
            fail(`expected type ${names.join('/')}, got ${got}`);
            return errors;
        }
    }
    if (schema['const'] !== undefined && value !== schema['const']) {
        fail(`expected const ${JSON.stringify(schema['const'])}, got ${JSON.stringify(value)}`);
    }
    const enumValues = schema['enum'];
    if (Array.isArray(enumValues) && !enumValues.includes(value)) {
        fail(`${JSON.stringify(value)} not in enum ${JSON.stringify(enumValues)}`);
    }
    if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
        const record = value;
        for (const key of schema['required'] ?? []) {
            if (!(key in record))
                fail(`missing required property '${key}'`);
        }
        for (const key of schema['disallowed'] ?? []) {
            if (key in record)
                fail(`forbidden credential-like property '${key}' must not appear`);
        }
        const properties = schema['properties'] ?? {};
        const additional = schema['additionalProperties'];
        for (const [key, sub] of Object.entries(record)) {
            if (key in properties) {
                errors.push(...validateSchema(sub, properties[key], `${path}.${key}`, root));
            }
            else if (additional === false) {
                fail(`unexpected property '${key}'`);
            }
            else if (additional !== undefined && typeof additional === 'object') {
                errors.push(...validateSchema(sub, additional, `${path}.${key}`, root));
            }
        }
        const minProperties = schema['minProperties'];
        if (typeof minProperties === 'number' && Object.keys(record).length < minProperties) {
            fail(`expected at least ${minProperties} properties, got ${Object.keys(record).length}`);
        }
    }
    const items = schema['items'];
    if (Array.isArray(value) && items !== undefined && typeof items === 'object') {
        value.forEach((item, index) => {
            errors.push(...validateSchema(item, items, `${path}[${index}]`, root));
        });
    }
    if (typeof value === 'number' && !Number.isNaN(value)) {
        const minimum = schema['minimum'];
        if (typeof minimum === 'number' && value < minimum) {
            fail(`${value} is less than minimum ${minimum}`);
        }
        const maximum = schema['maximum'];
        if (typeof maximum === 'number' && value > maximum) {
            fail(`${value} is greater than maximum ${maximum}`);
        }
    }
    if (typeof value === 'string') {
        const minLength = schema['minLength'];
        if (typeof minLength === 'number' && value.length < minLength) {
            fail(`string shorter than minLength ${minLength}`);
        }
        const pattern = schema['pattern'];
        if (typeof pattern === 'string' && new RegExp(pattern).test(value) === false) {
            fail(`'${value}' does not match pattern '${pattern}'`);
        }
    }
    return errors;
}
const SCHEMAS = {
    "delivery_manifest_v2": {
        "$id": "https://openwrite.dev/schemas/delivery-manifest-v2.schema.json",
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": true,
        "properties": {
            "chapterId": {
                "pattern": "^ch_\\d+$",
                "type": "string"
            },
            "decisionSource": {
                "enum": [
                    "v2",
                    "v1-adapter"
                ]
            },
            "novelId": {
                "minLength": 1,
                "type": "string"
            },
            "readyForDelivery": {
                "type": "boolean"
            },
            "recordType": {
                "const": "chapter-delivery"
            },
            "schemaVersion": {
                "const": "dsh-novel.delivery.manifest.v2"
            },
            "stages": {
                "additionalProperties": {
                    "additionalProperties": true,
                    "properties": {
                        "chapterId": {
                            "pattern": "^ch_\\d+$",
                            "type": "string"
                        },
                        "evidence": {
                            "type": "object"
                        },
                        "recordType": {
                            "const": "delivery-stage"
                        },
                        "schemaVersion": {
                            "const": "dsh-novel.delivery.stage.v2"
                        },
                        "stage": {
                            "minLength": 1,
                            "type": "string"
                        },
                        "status": {
                            "minLength": 1,
                            "type": "string"
                        },
                        "verdict": {
                            "enum": [
                                "pass",
                                "fail",
                                "inconclusive"
                            ]
                        }
                    },
                    "required": [
                        "schemaVersion",
                        "recordType",
                        "chapterId",
                        "stage",
                        "verdict",
                        "status",
                        "evidence"
                    ],
                    "type": "object"
                },
                "minProperties": 1,
                "type": "object"
            },
            "threshold": {
                "maximum": 100,
                "minimum": 0,
                "type": "integer"
            }
        },
        "required": [
            "schemaVersion",
            "recordType",
            "chapterId",
            "stages"
        ],
        "title": "dsh-novel delivery manifest v2",
        "type": "object"
    },
    "delivery_stage_v2": {
        "$id": "https://openwrite.dev/schemas/delivery-stage-v2.schema.json",
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": true,
        "properties": {
            "chapterId": {
                "pattern": "^ch_\\d+$",
                "type": "string"
            },
            "evidence": {
                "type": "object"
            },
            "recordType": {
                "const": "delivery-stage"
            },
            "schemaVersion": {
                "const": "dsh-novel.delivery.stage.v2"
            },
            "stage": {
                "minLength": 1,
                "type": "string"
            },
            "status": {
                "minLength": 1,
                "type": "string"
            },
            "verdict": {
                "enum": [
                    "pass",
                    "fail",
                    "inconclusive"
                ]
            }
        },
        "required": [
            "schemaVersion",
            "recordType",
            "chapterId",
            "stage",
            "verdict",
            "status",
            "evidence"
        ],
        "title": "dsh-novel delivery stage v2",
        "type": "object"
    },
    "model_benchmark_v1": {
        "$id": "https://openwrite.dev/schemas/model-benchmark-v1.schema.json",
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": true,
        "properties": {
            "candidates": {
                "items": {
                    "additionalProperties": true,
                    "disallowed": [
                        "api_key",
                        "embedding_api_key",
                        "secret"
                    ],
                    "properties": {
                        "candidate_id": {
                            "minLength": 1,
                            "type": "string"
                        },
                        "cost_reported": {
                            "type": "boolean"
                        },
                        "cost_usd": {
                            "type": [
                                "number",
                                "null"
                            ]
                        },
                        "error": {
                            "additionalProperties": true,
                            "properties": {
                                "code": {
                                    "minLength": 1,
                                    "type": "string"
                                },
                                "message": {
                                    "type": "string"
                                }
                            },
                            "required": [
                                "code",
                                "message"
                            ],
                            "type": [
                                "object",
                                "null"
                            ]
                        },
                        "latency_ms": {
                            "type": [
                                "integer",
                                "null"
                            ]
                        },
                        "outline_chapter_count": {
                            "maximum": 20,
                            "minimum": 1,
                            "type": "integer"
                        },
                        "outline_chapters": {
                            "items": {
                                "type": "object"
                            },
                            "type": "array"
                        },
                        "outline_end_chapter": {
                            "maximum": 100000,
                            "minimum": 1,
                            "type": "integer"
                        },
                        "outline_start_chapter": {
                            "maximum": 100000,
                            "minimum": 1,
                            "type": "integer"
                        },
                        "reliability_status": {
                            "enum": [
                                "completed",
                                "failed"
                            ]
                        },
                        "task_type": {
                            "enum": [
                                "chapter",
                                "outline"
                            ]
                        },
                        "usage": {
                            "additionalProperties": true,
                            "properties": {
                                "completion_tokens": {
                                    "type": [
                                        "integer",
                                        "null"
                                    ]
                                },
                                "prompt_tokens": {
                                    "type": [
                                        "integer",
                                        "null"
                                    ]
                                },
                                "reasoning_tokens": {
                                    "type": [
                                        "integer",
                                        "null"
                                    ]
                                },
                                "total_tokens": {
                                    "type": [
                                        "integer",
                                        "null"
                                    ]
                                }
                            },
                            "type": [
                                "object",
                                "null"
                            ]
                        },
                        "writer_profile": {
                            "type": "object"
                        }
                    },
                    "required": [
                        "candidate_id",
                        "writer_profile",
                        "reliability_status"
                    ],
                    "type": "object"
                },
                "type": "array"
            },
            "config": {
                "additionalProperties": true,
                "properties": {
                    "blind_review": {
                        "type": "boolean"
                    },
                    "concurrency": {
                        "maximum": 4,
                        "minimum": 1,
                        "type": "integer"
                    },
                    "execution_mode": {
                        "enum": [
                            "framework",
                            "creative"
                        ]
                    },
                    "outline_chapter_count": {
                        "maximum": 20,
                        "minimum": 1,
                        "type": "integer"
                    },
                    "outline_end_chapter": {
                        "maximum": 100000,
                        "minimum": 1,
                        "type": "integer"
                    },
                    "outline_start_chapter": {
                        "maximum": 100000,
                        "minimum": 1,
                        "type": "integer"
                    },
                    "pipeline": {
                        "properties": {
                            "execution_mode": {
                                "enum": [
                                    "framework",
                                    "creative"
                                ]
                            },
                            "id": {
                                "type": "string"
                            },
                            "nodes": {
                                "items": {
                                    "properties": {
                                        "depends_on": {
                                            "items": {
                                                "type": "string"
                                            },
                                            "type": "array"
                                        },
                                        "id": {
                                            "type": "string"
                                        },
                                        "label": {
                                            "type": "string"
                                        }
                                    },
                                    "required": [
                                        "id",
                                        "label",
                                        "depends_on"
                                    ],
                                    "type": "object"
                                },
                                "type": "array"
                            },
                            "review_domains": {
                                "items": {
                                    "properties": {
                                        "id": {
                                            "type": "string"
                                        },
                                        "label": {
                                            "type": "string"
                                        }
                                    },
                                    "type": "object"
                                },
                                "type": "array"
                            }
                        },
                        "type": "object"
                    },
                    "repeats": {
                        "maximum": 5,
                        "minimum": 1,
                        "type": "integer"
                    },
                    "reviewer_profile_ids": {
                        "items": {
                            "type": "string"
                        },
                        "type": "array"
                    },
                    "run_scoped_profiles": {
                        "type": "boolean"
                    },
                    "target_words": {
                        "maximum": 12000,
                        "minimum": 200,
                        "type": "integer"
                    },
                    "task_type": {
                        "enum": [
                            "chapter",
                            "outline"
                        ]
                    },
                    "writer_profile_ids": {
                        "items": {
                            "type": "string"
                        },
                        "type": "array"
                    }
                },
                "required": [
                    "writer_profile_ids",
                    "reviewer_profile_ids"
                ],
                "type": "object"
            },
            "context_hash": {
                "minLength": 1,
                "type": "string"
            },
            "evaluations": {
                "items": {
                    "additionalProperties": true,
                    "disallowed": [
                        "api_key",
                        "embedding_api_key",
                        "secret"
                    ],
                    "properties": {
                        "candidate_id": {
                            "minLength": 1,
                            "type": "string"
                        },
                        "cost_reported": {
                            "type": "boolean"
                        },
                        "cost_usd": {
                            "type": [
                                "number",
                                "null"
                            ]
                        },
                        "error": {
                            "additionalProperties": true,
                            "properties": {
                                "code": {
                                    "minLength": 1,
                                    "type": "string"
                                },
                                "message": {
                                    "type": "string"
                                }
                            },
                            "required": [
                                "code",
                                "message"
                            ],
                            "type": [
                                "object",
                                "null"
                            ]
                        },
                        "execution_status": {
                            "enum": [
                                "completed",
                                "partial",
                                "failed"
                            ]
                        },
                        "latency_ms": {
                            "type": [
                                "integer",
                                "null"
                            ]
                        },
                        "reviewer_profile": {
                            "type": "object"
                        },
                        "usage": {
                            "additionalProperties": true,
                            "properties": {
                                "completion_tokens": {
                                    "type": [
                                        "integer",
                                        "null"
                                    ]
                                },
                                "prompt_tokens": {
                                    "type": [
                                        "integer",
                                        "null"
                                    ]
                                },
                                "reasoning_tokens": {
                                    "type": [
                                        "integer",
                                        "null"
                                    ]
                                },
                                "total_tokens": {
                                    "type": [
                                        "integer",
                                        "null"
                                    ]
                                }
                            },
                            "type": [
                                "object",
                                "null"
                            ]
                        }
                    },
                    "required": [
                        "candidate_id",
                        "reviewer_profile",
                        "execution_status"
                    ],
                    "type": "object"
                },
                "type": "array"
            },
            "run_id": {
                "pattern": "^bench_[A-Za-z0-9_-]+$",
                "type": "string"
            },
            "schema_version": {
                "const": "openwrite.model-benchmark.v1"
            },
            "started_at": {
                "minLength": 1,
                "type": "string"
            },
            "status": {
                "enum": [
                    "completed",
                    "partial",
                    "failed",
                    "running",
                    "cancelling",
                    "cancelled"
                ]
            },
            "summary": {
                "additionalProperties": true,
                "properties": {
                    "failed_candidates": {
                        "minimum": 0,
                        "type": "integer"
                    },
                    "latency_ms_total": {
                        "type": [
                            "integer",
                            "null"
                        ]
                    }
                },
                "type": "object"
            },
            "task_id": {
                "minLength": 1,
                "type": "string"
            },
            "task_type": {
                "enum": [
                    "chapter",
                    "outline"
                ]
            }
        },
        "required": [
            "schema_version",
            "run_id",
            "status",
            "context_hash",
            "config",
            "candidates",
            "evaluations"
        ],
        "title": "OpenWrite model benchmark v1 artifact",
        "type": "object"
    },
    "model_connection_test_v1": {
        "$id": "https://openwrite.dev/schemas/model-connection-test-v1.schema.json",
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": true,
        "disallowed": [
            "api_key",
            "embedding_api_key",
            "secret",
            "credential"
        ],
        "properties": {
            "base_url": {
                "type": "string"
            },
            "dimension": {
                "minimum": 1,
                "type": "integer"
            },
            "latency_ms": {
                "minimum": 0,
                "type": "integer"
            },
            "max_tokens": {
                "minimum": 1,
                "type": "integer"
            },
            "model": {
                "minLength": 1,
                "type": "string"
            },
            "ok": {
                "const": true
            },
            "provider": {
                "minLength": 1,
                "type": "string"
            },
            "provider_label": {
                "type": "string"
            },
            "reply": {
                "type": "string"
            },
            "status": {
                "const": "ok"
            },
            "tested_at": {
                "minLength": 1,
                "type": "string"
            },
            "vectors": {
                "minimum": 1,
                "type": "integer"
            }
        },
        "required": [
            "ok",
            "status",
            "provider",
            "model",
            "latency_ms",
            "tested_at"
        ],
        "title": "OpenWrite model connection test v1 success payload (chat and embedding variants)",
        "type": "object"
    },
    "model_profile_surface_v1": {
        "$defs": {
            "chat_profile": {
                "additionalProperties": true,
                "disallowed": [
                    "api_key",
                    "embedding_api_key",
                    "secret"
                ],
                "properties": {
                    "auth_source": {
                        "enum": [
                            "api_key",
                            "opencode_console",
                            "host_relay"
                        ]
                    },
                    "capabilities": {
                        "properties": {
                            "chat": {
                                "const": true
                            }
                        },
                        "required": [
                            "chat"
                        ],
                        "type": "object"
                    },
                    "configured": {
                        "type": "boolean"
                    },
                    "id": {
                        "type": "string"
                    },
                    "label": {
                        "type": "string"
                    },
                    "last_test": {
                        "$ref": "#/$defs/test"
                    },
                    "model": {
                        "type": "string"
                    },
                    "provider": {
                        "type": "string"
                    },
                    "schema_version": {
                        "const": "openwrite.model-profile.v1"
                    },
                    "used_by_routes": {
                        "items": {
                            "enum": [
                                "goethe",
                                "dante",
                                "chapter_write",
                                "review",
                                "source_extract",
                                "revision",
                                "search",
                                "research"
                            ]
                        },
                        "type": "array"
                    },
                    "workspace_id": {
                        "type": "string"
                    }
                },
                "required": [
                    "id",
                    "label",
                    "provider",
                    "model",
                    "configured",
                    "schema_version",
                    "capabilities",
                    "used_by_routes",
                    "last_test"
                ],
                "type": "object"
            },
            "embedding_profile": {
                "additionalProperties": true,
                "disallowed": [
                    "api_key",
                    "embedding_api_key",
                    "secret"
                ],
                "properties": {
                    "active": {
                        "type": "boolean"
                    },
                    "base_url": {
                        "type": "string"
                    },
                    "configured": {
                        "type": "boolean"
                    },
                    "dimension": {
                        "minimum": 1,
                        "type": "integer"
                    },
                    "id": {
                        "type": "string"
                    },
                    "label": {
                        "type": "string"
                    },
                    "last_test": {
                        "$ref": "#/$defs/test"
                    },
                    "max_tokens": {
                        "minimum": 1,
                        "type": "integer"
                    },
                    "model": {
                        "type": "string"
                    },
                    "provider": {
                        "type": "string"
                    },
                    "schema_version": {
                        "const": "openwrite.embedding-profile.v1"
                    }
                },
                "required": [
                    "id",
                    "label",
                    "provider",
                    "model",
                    "dimension",
                    "max_tokens",
                    "configured",
                    "active",
                    "schema_version",
                    "last_test"
                ],
                "type": "object"
            },
            "test": {
                "additionalProperties": true,
                "disallowed": [
                    "api_key",
                    "secret",
                    "credential"
                ],
                "properties": {
                    "error_code": {
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "failed_stage": {
                        "type": "null"
                    },
                    "latency_ms": {
                        "minimum": 0,
                        "type": "integer"
                    },
                    "provider": {
                        "type": "string"
                    },
                    "resolved_model": {
                        "type": "string"
                    },
                    "status": {
                        "enum": [
                            "ok",
                            "failed"
                        ]
                    },
                    "tested_at": {
                        "type": "string"
                    }
                },
                "required": [
                    "status",
                    "tested_at",
                    "latency_ms",
                    "provider",
                    "resolved_model",
                    "error_code",
                    "failed_stage"
                ],
                "type": [
                    "object",
                    "null"
                ]
            }
        },
        "$id": "https://openwrite.dev/schemas/model-profile-surface-v1.schema.json",
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": true,
        "properties": {
            "active_embedding_profile_id": {
                "type": "string"
            },
            "default_profile_id": {
                "minLength": 1,
                "type": "string"
            },
            "embedding_profiles": {
                "items": {
                    "$ref": "#/$defs/embedding_profile"
                },
                "type": "array"
            },
            "profiles": {
                "items": {
                    "$ref": "#/$defs/chat_profile"
                },
                "type": "array"
            },
            "routes": {
                "additionalProperties": {
                    "type": "string"
                },
                "type": "object"
            },
            "schema_version": {
                "const": "openwrite.model-profile.v1"
            }
        },
        "required": [
            "schema_version",
            "profiles",
            "routes",
            "default_profile_id",
            "embedding_profiles",
            "active_embedding_profile_id"
        ],
        "title": "OpenWrite independent chat and embedding model surface v1",
        "type": "object"
    },
    "research_surface_v1": {
        "$id": "https://openwrite.dev/schemas/research-surface-v1.schema.json",
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": true,
        "disallowed": [
            "api_key",
            "credential",
            "secret"
        ],
        "properties": {
            "available": {
                "type": "boolean"
            },
            "dependencies_ready": {
                "type": "boolean"
            },
            "model_route": {
                "additionalProperties": true,
                "disallowed": [
                    "api_key",
                    "credential",
                    "secret"
                ],
                "properties": {
                    "compatible": {
                        "type": "boolean"
                    },
                    "configured": {
                        "type": "boolean"
                    },
                    "label": {
                        "type": "string"
                    },
                    "model": {
                        "type": "string"
                    },
                    "profile_id": {
                        "type": "string"
                    },
                    "provider": {
                        "type": "string"
                    }
                },
                "required": [
                    "profile_id",
                    "label",
                    "model",
                    "provider",
                    "configured",
                    "compatible"
                ],
                "type": "object"
            },
            "node_ready": {
                "type": "boolean"
            },
            "package_ready": {
                "type": "boolean"
            },
            "pnpm_ready": {
                "type": "boolean"
            },
            "reports": {
                "items": {
                    "additionalProperties": true,
                    "disallowed": [
                        "api_key",
                        "credential",
                        "secret"
                    ],
                    "properties": {
                        "bytes": {
                            "minimum": 0,
                            "type": "integer"
                        },
                        "completed_at": {
                            "type": [
                                "string",
                                "null"
                            ]
                        },
                        "cost_usd": {
                            "additionalProperties": true,
                            "properties": {
                                "reported": {
                                    "type": "boolean"
                                },
                                "value": {
                                    "minimum": 0,
                                    "type": [
                                        "number",
                                        "null"
                                    ]
                                }
                            },
                            "required": [
                                "value",
                                "reported"
                            ],
                            "type": "object"
                        },
                        "created_at": {
                            "type": [
                                "string",
                                "null"
                            ]
                        },
                        "episode_id": {
                            "type": [
                                "string",
                                "null"
                            ]
                        },
                        "failure": {
                            "additionalProperties": true,
                            "disallowed": [
                                "api_key",
                                "credential",
                                "secret"
                            ],
                            "properties": {
                                "code": {
                                    "minLength": 1,
                                    "type": "string"
                                },
                                "message": {
                                    "type": "string"
                                }
                            },
                            "required": [
                                "code",
                                "message"
                            ],
                            "type": [
                                "object",
                                "null"
                            ]
                        },
                        "id": {
                            "minLength": 1,
                            "type": "string"
                        },
                        "latency_ms": {
                            "minimum": 0,
                            "type": [
                                "integer",
                                "null"
                            ]
                        },
                        "metrics": {
                            "type": "object"
                        },
                        "model_profile": {
                            "additionalProperties": true,
                            "disallowed": [
                                "api_key",
                                "credential",
                                "secret"
                            ],
                            "properties": {
                                "id": {
                                    "type": [
                                        "string",
                                        "null"
                                    ]
                                },
                                "label": {
                                    "type": [
                                        "string",
                                        "null"
                                    ]
                                },
                                "model": {
                                    "type": [
                                        "string",
                                        "null"
                                    ]
                                },
                                "provider": {
                                    "type": [
                                        "string",
                                        "null"
                                    ]
                                }
                            },
                            "required": [
                                "id",
                                "label",
                                "model",
                                "provider"
                            ],
                            "type": [
                                "object",
                                "null"
                            ]
                        },
                        "path": {
                            "minLength": 1,
                            "type": "string"
                        },
                        "search_provider": {
                            "type": [
                                "string",
                                "null"
                            ]
                        },
                        "source_count": {
                            "minimum": 0,
                            "type": [
                                "integer",
                                "null"
                            ]
                        },
                        "sources": {
                            "items": {
                                "additionalProperties": true,
                                "properties": {
                                    "cited": {
                                        "type": "boolean"
                                    },
                                    "source_type": {
                                        "type": "string"
                                    },
                                    "title": {
                                        "type": "string"
                                    },
                                    "url": {
                                        "type": "string"
                                    }
                                },
                                "required": [
                                    "title",
                                    "url",
                                    "source_type",
                                    "cited"
                                ],
                                "type": "object"
                            },
                            "type": [
                                "array",
                                "null"
                            ]
                        },
                        "sources_status": {
                            "enum": [
                                "ok",
                                "unavailable"
                            ]
                        },
                        "status": {
                            "enum": [
                                "succeeded",
                                "failed",
                                "needs_human_review",
                                "unknown"
                            ]
                        },
                        "task_id": {
                            "type": [
                                "string",
                                "null"
                            ]
                        },
                        "title": {
                            "type": "string"
                        },
                        "usage": {
                            "additionalProperties": true,
                            "properties": {
                                "reported": {
                                    "type": "boolean"
                                },
                                "total_tokens": {
                                    "minimum": 0,
                                    "type": [
                                        "integer",
                                        "null"
                                    ]
                                }
                            },
                            "required": [
                                "total_tokens",
                                "reported"
                            ],
                            "type": "object"
                        },
                        "word_count": {
                            "minimum": 0,
                            "type": [
                                "integer",
                                "null"
                            ]
                        }
                    },
                    "required": [
                        "id",
                        "title",
                        "status",
                        "episode_id",
                        "task_id",
                        "created_at",
                        "completed_at",
                        "model_profile",
                        "search_provider",
                        "sources",
                        "sources_status",
                        "source_count",
                        "word_count",
                        "latency_ms",
                        "usage",
                        "cost_usd",
                        "failure",
                        "metrics",
                        "path",
                        "bytes"
                    ],
                    "type": "object"
                },
                "type": "array"
            },
            "schema_version": {
                "const": "openwrite.research-surface.v1"
            },
            "settings": {
                "additionalProperties": true,
                "disallowed": [
                    "api_key",
                    "credential",
                    "secret"
                ],
                "properties": {
                    "search_provider": {
                        "enum": [
                            "bocha",
                            "bing",
                            "jina",
                            "none"
                        ]
                    },
                    "search_providers": {
                        "items": {
                            "additionalProperties": true,
                            "disallowed": [
                                "api_key",
                                "credential",
                                "secret"
                            ],
                            "properties": {
                                "configured": {
                                    "type": "boolean"
                                },
                                "credential_configured": {
                                    "type": "boolean"
                                },
                                "id": {
                                    "enum": [
                                        "bocha",
                                        "bing",
                                        "jina",
                                        "none"
                                    ]
                                },
                                "label": {
                                    "minLength": 1,
                                    "type": "string"
                                },
                                "requires_api_key": {
                                    "type": "boolean"
                                }
                            },
                            "required": [
                                "id",
                                "label",
                                "requires_api_key",
                                "configured",
                                "credential_configured"
                            ],
                            "type": "object"
                        },
                        "type": "array"
                    }
                },
                "required": [
                    "search_provider",
                    "search_providers"
                ],
                "type": "object"
            },
            "setup_hint": {
                "type": "string"
            }
        },
        "required": [
            "schema_version",
            "available",
            "node_ready",
            "pnpm_ready",
            "package_ready",
            "dependencies_ready",
            "setup_hint",
            "settings",
            "reports",
            "model_route"
        ],
        "title": "OpenWrite research surface v1 (credential-free)",
        "type": "object"
    },
    "review_manifest_v2": {
        "$id": "https://openwrite.dev/schemas/review-manifest-v2.schema.json",
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": true,
        "properties": {
            "chapterId": {
                "pattern": "^ch_\\d+$",
                "type": "string"
            },
            "coverage": {
                "maximum": 1,
                "minimum": 0,
                "type": "number"
            },
            "decisionSource": {
                "enum": [
                    "v2",
                    "v1-adapter"
                ]
            },
            "qualityScore": {
                "maximum": 100,
                "minimum": 0,
                "type": [
                    "number",
                    "null"
                ]
            },
            "recordType": {
                "const": "review"
            },
            "schemaVersion": {
                "const": "dsh-novel.review.manifest.v2"
            },
            "threshold": {
                "maximum": 100,
                "minimum": 0,
                "type": "integer"
            },
            "verdict": {
                "enum": [
                    "pass",
                    "fail",
                    "inconclusive"
                ]
            }
        },
        "required": [
            "schemaVersion",
            "recordType",
            "chapterId",
            "verdict"
        ],
        "title": "dsh-novel review manifest v2",
        "type": "object"
    },
    "review_v2_decision": {
        "$id": "https://openwrite.dev/schemas/review-v2-decision.schema.json",
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": true,
        "properties": {
            "coverage": {
                "maximum": 1,
                "minimum": 0,
                "type": "number"
            },
            "delivery_status": {
                "enum": [
                    "pass",
                    "revise",
                    "blocked",
                    "inconclusive",
                    "stale"
                ]
            },
            "execution_status": {
                "enum": [
                    "completed",
                    "partial",
                    "failed"
                ]
            },
            "gate_status": {
                "enum": [
                    "pass",
                    "blocked",
                    "inconclusive"
                ]
            },
            "production_gate_status": {
                "enum": [
                    "pass",
                    "revise",
                    "blocked",
                    "inconclusive",
                    "stale",
                    "disabled",
                    "disabled_uncalibrated"
                ]
            },
            "quality_score": {
                "maximum": 100,
                "minimum": 0,
                "type": [
                    "number",
                    "null"
                ]
            },
            "schema_version": {
                "const": "openwrite.review.v2"
            }
        },
        "required": [
            "schema_version",
            "execution_status",
            "quality_score",
            "coverage",
            "gate_status",
            "delivery_status"
        ],
        "title": "OpenWrite review v2 decision",
        "type": "object"
    },
    "task_surface_v1": {
        "$id": "https://openwrite.dev/schemas/task-surface-v1.schema.json",
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": true,
        "properties": {
            "counts": {
                "type": "object"
            },
            "phase_order": {
                "items": {
                    "enum": [
                        "queued",
                        "reading",
                        "preparing",
                        "model",
                        "validating",
                        "committing",
                        "complete"
                    ]
                },
                "type": "array"
            },
            "schema_version": {
                "const": "openwrite.task-surface.v1"
            },
            "tasks": {
                "items": {
                    "additionalProperties": true,
                    "disallowed": [
                        "api_key",
                        "credential",
                        "secret"
                    ],
                    "properties": {
                        "attempt": {
                            "minimum": 1,
                            "type": "integer"
                        },
                        "chapter_id": {
                            "type": [
                                "string",
                                "null"
                            ]
                        },
                        "completed_at": {
                            "type": [
                                "string",
                                "null"
                            ]
                        },
                        "created_at": {
                            "type": [
                                "string",
                                "null"
                            ]
                        },
                        "error": {
                            "additionalProperties": true,
                            "properties": {
                                "code": {
                                    "minLength": 1,
                                    "type": "string"
                                },
                                "failed_stage": {
                                    "type": [
                                        "string",
                                        "null"
                                    ]
                                },
                                "message": {
                                    "type": "string"
                                },
                                "recoverable": {
                                    "type": "boolean"
                                }
                            },
                            "required": [
                                "code",
                                "message",
                                "recoverable"
                            ],
                            "type": [
                                "object",
                                "null"
                            ]
                        },
                        "input_summary": {
                            "type": [
                                "string",
                                "null"
                            ]
                        },
                        "phase": {
                            "enum": [
                                "queued",
                                "reading",
                                "preparing",
                                "model",
                                "validating",
                                "committing",
                                "complete",
                                null
                            ]
                        },
                        "phase_index": {
                            "type": [
                                "integer",
                                "null"
                            ]
                        },
                        "progress": {
                            "additionalProperties": true,
                            "properties": {
                                "completed_units": {
                                    "minimum": 0,
                                    "type": "integer"
                                },
                                "ratio": {
                                    "maximum": 1,
                                    "minimum": 0,
                                    "type": [
                                        "number",
                                        "null"
                                    ]
                                },
                                "total_units": {
                                    "minimum": 0,
                                    "type": "integer"
                                },
                                "unit_kind": {
                                    "enum": [
                                        "candidates",
                                        "evaluations",
                                        "chapters",
                                        "files"
                                    ]
                                }
                            },
                            "required": [
                                "completed_units",
                                "total_units",
                                "ratio",
                                "unit_kind"
                            ],
                            "type": [
                                "object",
                                "null"
                            ]
                        },
                        "result_ref": {
                            "additionalProperties": true,
                            "properties": {
                                "id": {
                                    "minLength": 1,
                                    "type": "string"
                                },
                                "type": {
                                    "enum": [
                                        "chapter",
                                        "review",
                                        "revision",
                                        "research_report",
                                        "benchmark_run",
                                        "import",
                                        "archive"
                                    ]
                                }
                            },
                            "required": [
                                "type",
                                "id"
                            ],
                            "type": [
                                "object",
                                "null"
                            ]
                        },
                        "retryable": {
                            "type": "boolean"
                        },
                        "schema_version": {
                            "minLength": 1,
                            "type": "string"
                        },
                        "started_at": {
                            "type": [
                                "string",
                                "null"
                            ]
                        },
                        "status": {
                            "enum": [
                                "pending",
                                "running",
                                "awaiting_confirmation",
                                "completed",
                                "failed",
                                "cancelled",
                                "interrupted"
                            ]
                        },
                        "task_id": {
                            "minLength": 1,
                            "type": "string"
                        },
                        "type": {
                            "minLength": 1,
                            "type": "string"
                        },
                        "updated_at": {
                            "type": [
                                "string",
                                "null"
                            ]
                        }
                    },
                    "required": [
                        "task_id",
                        "type",
                        "status",
                        "phase",
                        "phase_index",
                        "progress",
                        "attempt",
                        "retryable",
                        "created_at",
                        "updated_at",
                        "started_at",
                        "completed_at",
                        "error",
                        "result_ref",
                        "input_summary",
                        "chapter_id",
                        "schema_version"
                    ],
                    "type": "object"
                },
                "type": "array"
            }
        },
        "required": [
            "schema_version",
            "phase_order",
            "tasks",
            "counts"
        ],
        "title": "OpenWrite task surface v1 (credential-free)",
        "type": "object"
    }
};
function validateContract(value, key, label) {
    const errors = validateSchema(value, SCHEMAS[key]);
    if (errors.length > 0) {
        throw new Error(`CONTRACT_INVALID: ${label} violates ${key}: ${errors.join('; ')}`);
    }
    return value;
}
/** Validate `value` against the review_v2_decision schema; throw on failure. */
export function validateReviewV2Decision(value) {
    return validateContract(value, 'review_v2_decision', 'review_v2');
}
/** Validate `value` against the review_manifest_v2 schema; throw on failure. */
export function validateReviewManifestV2(value) {
    return validateContract(value, 'review_manifest_v2', 'review manifest');
}
/** Validate `value` against the delivery_manifest_v2 schema; throw on failure. */
export function validateDeliveryManifestV2(value) {
    return validateContract(value, 'delivery_manifest_v2', 'delivery manifest');
}
/** Validate `value` against the delivery_stage_v2 schema; throw on failure. */
export function validateDeliveryStageV2(value) {
    return validateContract(value, 'delivery_stage_v2', 'delivery stage');
}
/** Validate `value` against the model_benchmark_v1 schema; throw on failure. */
export function validateModelBenchmarkV1(value) {
    return validateContract(value, 'model_benchmark_v1', 'benchmark');
}
/** Validate `value` against the model_profile_surface_v1 schema; throw on failure. */
export function validateModelProfileSurfaceV1(value) {
    return validateContract(value, 'model_profile_surface_v1', 'model profile surface');
}
/** Validate `value` against the task_surface_v1 schema; throw on failure. */
export function validateTaskSurfaceV1(value) {
    return validateContract(value, 'task_surface_v1', 'task surface');
}
/** Validate `value` against the research_surface_v1 schema; throw on failure. */
export function validateResearchSurfaceV1(value) {
    return validateContract(value, 'research_surface_v1', 'research surface');
}
/** Validate `value` against the model_connection_test_v1 schema; throw on failure. */
export function validateModelConnectionTestV1(value) {
    return validateContract(value, 'model_connection_test_v1', 'model connection test');
}
