/** IndexedDB-backed recovery drafts for manuscript documents. */

export const MANUSCRIPT_DRAFT_FORMAT_VERSION = 1 as const

const DATABASE_NAME = 'dsh-novel-manuscript-drafts'
const DATABASE_VERSION = 1
const OBJECT_STORE = 'drafts'

export interface ManuscriptDraftIdentity {
  workspaceId: string
  novelId: string
  path: string
}

export interface ManuscriptDraftRecord extends ManuscriptDraftIdentity {
  key: string
  formatVersion: typeof MANUSCRIPT_DRAFT_FORMAT_VERSION
  baseRevision: string
  content: string
  updatedAt: number
}

export interface ManuscriptDraftStore {
  load: (identity: ManuscriptDraftIdentity) => Promise<ManuscriptDraftRecord | null>
  save: (record: ManuscriptDraftRecord) => Promise<void>
  remove: (identity: ManuscriptDraftIdentity) => Promise<void>
  removeIfContent: (identity: ManuscriptDraftIdentity, content: string) => Promise<boolean>
}

export class ManuscriptDraftStorageError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options)
    this.name = 'ManuscriptDraftStorageError'
  }
}

export function manuscriptDraftKey(identity: ManuscriptDraftIdentity): string {
  const parts = [identity.workspaceId, identity.novelId, identity.path]
  if (parts.some(part => part.trim() === '')) {
    throw new ManuscriptDraftStorageError('Workspace, work and document identities are required')
  }
  return `v${String(MANUSCRIPT_DRAFT_FORMAT_VERSION)}:${JSON.stringify(parts)}`
}

export function manuscriptNovelId(workspacePayload: unknown, path: string): string {
  if (workspacePayload !== null && typeof workspacePayload === 'object') {
    const snapshot = (workspacePayload as Record<string, unknown>)['snapshot']
    if (snapshot !== null && typeof snapshot === 'object') {
      const value = (snapshot as Record<string, unknown>)['novel_id']
      if (typeof value === 'string' && value.trim() !== '') return value.trim()
    }
  }
  return /(?:^|\/)data\/novels\/([^/]+)\//.exec(path)?.[1] ?? ''
}

function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new ManuscriptDraftStorageError('IndexedDB request failed'))
  })
}

function transactionDone(transaction: IDBTransaction): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    transaction.oncomplete = () => resolve()
    transaction.onabort = () => reject(transaction.error ?? new ManuscriptDraftStorageError('IndexedDB transaction aborted'))
    transaction.onerror = () => reject(transaction.error ?? new ManuscriptDraftStorageError('IndexedDB transaction failed'))
  })
}

function validRecord(value: unknown, expectedKey: string): ManuscriptDraftRecord | null {
  if (value === null || typeof value !== 'object') return null
  const item = value as Partial<ManuscriptDraftRecord>
  if (
    item.key !== expectedKey ||
    item.formatVersion !== MANUSCRIPT_DRAFT_FORMAT_VERSION ||
    typeof item.workspaceId !== 'string' ||
    typeof item.novelId !== 'string' ||
    typeof item.path !== 'string' ||
    typeof item.baseRevision !== 'string' ||
    typeof item.content !== 'string' ||
    typeof item.updatedAt !== 'number' ||
    !Number.isFinite(item.updatedAt)
  ) return null
  return item as ManuscriptDraftRecord
}

class IndexedDbManuscriptDraftStore implements ManuscriptDraftStore {
  private databasePromise: Promise<IDBDatabase> | null = null

  private database(): Promise<IDBDatabase> {
    if (this.databasePromise !== null) return this.databasePromise
    this.databasePromise = new Promise<IDBDatabase>((resolve, reject) => {
      if (typeof indexedDB === 'undefined') {
        reject(new ManuscriptDraftStorageError('IndexedDB is unavailable'))
        return
      }
      const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION)
      request.onupgradeneeded = () => {
        if (!request.result.objectStoreNames.contains(OBJECT_STORE)) {
          request.result.createObjectStore(OBJECT_STORE, { keyPath: 'key' })
        }
      }
      request.onsuccess = () => {
        const database = request.result
        database.onversionchange = () => {
          database.close()
          this.databasePromise = null
        }
        resolve(database)
      }
      request.onerror = () => {
        this.databasePromise = null
        reject(request.error ?? new ManuscriptDraftStorageError('Unable to open IndexedDB'))
      }
      request.onblocked = () => {
        this.databasePromise = null
        reject(new ManuscriptDraftStorageError('IndexedDB upgrade is blocked'))
      }
    })
    return this.databasePromise
  }

  async load(identity: ManuscriptDraftIdentity): Promise<ManuscriptDraftRecord | null> {
    const key = manuscriptDraftKey(identity)
    const database = await this.database()
    const transaction = database.transaction(OBJECT_STORE, 'readonly')
    const done = transactionDone(transaction)
    const value = await requestResult(transaction.objectStore(OBJECT_STORE).get(key) as IDBRequest<unknown>)
    await done
    return validRecord(value, key)
  }

  async save(record: ManuscriptDraftRecord): Promise<void> {
    const key = manuscriptDraftKey(record)
    if (record.key !== key || record.formatVersion !== MANUSCRIPT_DRAFT_FORMAT_VERSION) {
      throw new ManuscriptDraftStorageError('Draft identity or format is invalid')
    }
    const database = await this.database()
    const transaction = database.transaction(OBJECT_STORE, 'readwrite')
    const done = transactionDone(transaction)
    transaction.objectStore(OBJECT_STORE).put(record)
    await done
  }

  async remove(identity: ManuscriptDraftIdentity): Promise<void> {
    const database = await this.database()
    const transaction = database.transaction(OBJECT_STORE, 'readwrite')
    const done = transactionDone(transaction)
    transaction.objectStore(OBJECT_STORE).delete(manuscriptDraftKey(identity))
    await done
  }

  async removeIfContent(identity: ManuscriptDraftIdentity, content: string): Promise<boolean> {
    const key = manuscriptDraftKey(identity)
    const database = await this.database()
    const transaction = database.transaction(OBJECT_STORE, 'readwrite')
    const done = transactionDone(transaction)
    const store = transaction.objectStore(OBJECT_STORE)
    const value = await requestResult(store.get(key) as IDBRequest<unknown>)
    const current = validRecord(value, key)
    const removed = current?.content === content
    if (removed) store.delete(key)
    await done
    return removed
  }
}

export const manuscriptDraftStore: ManuscriptDraftStore = new IndexedDbManuscriptDraftStore()
