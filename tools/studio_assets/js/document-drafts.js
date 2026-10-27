/** Browser-only recovery, scoped to a project, work, document and server version. */
export class DocumentDraftStore {
  constructor(storage = () => globalThis.localStorage) { this.storage = storage; }

  key(identity) {
    const parts = [identity?.projectRoot, identity?.novelId, identity?.path];
    if (parts.some(value => typeof value !== "string" || !value.trim())) {
      throw new Error("恢复草稿需要完整的作品与文档标识");
    }
    return `openwrite-document-draft-v1:${JSON.stringify(parts)}`;
  }

  records(identity) {
    const raw = this.storage().getItem(this.key(identity));
    if (!raw) return [];
    let parsed;
    try { parsed = JSON.parse(raw); } catch { return []; }
    const records = Array.isArray(parsed) ? parsed : [parsed];
    return records.filter(record => record && record.format === 1
      && record.projectRoot === identity.projectRoot && record.novelId === identity.novelId
      && record.path === identity.path && typeof record.version === "string"
      && typeof record.content === "string" && typeof record.updatedAt === "number"
      && Number.isFinite(record.updatedAt));
  }

  load(identity, version) {
    const records = this.records(identity);
    // An unresolved conflict stays available even after a newer version is
    // edited and saved. Prefer the current server version when it has a draft.
    return records.find(record => record.version === String(version)) ?? records[0] ?? null;
  }

  save(identity, version, content) {
    if (typeof content !== "string") throw new Error("恢复草稿内容无效");
    const record = { ...identity, format: 1, version: String(version), content, updatedAt: Date.now() };
    const remaining = this.records(identity).filter(item => item.version !== record.version);
    this.storage().setItem(this.key(identity), JSON.stringify([record, ...remaining]));
    return record;
  }

  removeIfContent(identity, version, content) {
    const records = this.records(identity);
    const remaining = records.filter(record => record.version !== String(version) || record.content !== content);
    if (remaining.length === records.length) return false;
    if (remaining.length) this.storage().setItem(this.key(identity), JSON.stringify(remaining));
    else this.storage().removeItem(this.key(identity));
    return true;
  }
}
