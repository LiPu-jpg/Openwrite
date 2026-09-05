/** `studio-panel` namespace dictionaries (view tab labels + panel states). */

/** Dictionary namespace owned by this plugin. */
export const NS = 'studio-panel'

/** The studio-panel dictionary key set (the source of truth for both locales). */
export type StudioPanelKey =
  | 'view.overview'
  | 'view.writing'
  | 'view.studio'
  | 'view.reviewWs'
  | 'view.outline'
  | 'view.assets'
  | 'view.tasks'
  | 'view.benchmark'
  | 'view.models'
  | 'view.graph'
  | 'view.research'
  | 'view.search'
  | 'view.creation'
  | 'view.library'
  | 'view.operations'
  | 'creation.chapters'
  | 'creation.searchChapters'
  | 'creation.clearSearch'
  | 'creation.chaptersEmpty'
  | 'creation.previousChapter'
  | 'creation.nextChapter'
  | 'creation.jumpChapter'
  | 'creation.chapterDuplicate'
  | 'creation.order.loading'
  | 'creation.order.unavailable'
  | 'creation.order.refresh'
  | 'creation.order.invalid'
  | 'creation.order.missingCount'
  | 'creation.order.move'
  | 'creation.order.volume'
  | 'creation.order.position'
  | 'creation.order.positionHelp'
  | 'creation.order.applyMove'
  | 'creation.order.blocked'
  | 'creation.order.moveComplete'
  | 'creation.order.conflict'
  | 'creation.mode.edit'
  | 'creation.mode.reader'
  | 'creation.writing.bookProgress'
  | 'creation.writing.chapterTarget'
  | 'creation.writing.chapterProgress'
  | 'creation.reader.title'
  | 'creation.reader.readOnly'
  | 'creation.reader.loading'
  | 'creation.reader.refresh'
  | 'creation.reader.openEditor'
  | 'creation.reader.path'
  | 'creation.reader.documentId'
  | 'creation.reader.revision'
  | 'creation.reader.revisionUnavailable'
  | 'creation.showChapters'
  | 'creation.hideChapters'
  | 'creation.inspector'
  | 'creation.showInspector'
  | 'creation.hideInspector'
  | 'creation.editorLoading'
  | 'creation.documentLoading'
  | 'creation.inspectorLoading'
  | 'creation.inspectorLoadingSlow'
  | 'creation.empty'
  | 'creation.acceptance.title'
  | 'creation.acceptance.loading'
  | 'creation.acceptance.current'
  | 'creation.acceptance.pending'
  | 'creation.acceptance.drift'
  | 'creation.acceptance.baselinePending'
  | 'creation.acceptance.needsReview'
  | 'creation.acceptance.failed'
  | 'creation.acceptance.unknown'
  | 'creation.acceptance.unavailable'
  | 'creation.acceptance.currentRevision'
  | 'creation.acceptance.acceptedRevision'
  | 'creation.acceptance.operation'
  | 'creation.acceptance.stale'
  | 'creation.acceptance.refresh'
  | 'creation.acceptance.baseline'
  | 'creation.acceptance.external'
  | 'creation.acceptance.resume'
  | 'creation.acceptance.acknowledge'
  | 'creation.acceptance.confirmBaseline'
  | 'creation.acceptance.confirmExternal'
  | 'creation.acceptance.confirmAcknowledge'
  | 'creation.context'
  | 'creation.review'
  | 'creation.revisions'
  | 'creation.activity'
  | 'creation.activity.loading'
  | 'creation.activity.unavailable'
  | 'creation.activity.invalid'
  | 'creation.activity.target'
  | 'creation.activity.remaining'
  | 'creation.activity.identity'
  | 'creation.activity.recent'
  | 'creation.activity.empty'
  | 'creation.contextEmpty'
  | 'creation.context.packet'
  | 'creation.context.current'
  | 'creation.context.stale'
  | 'creation.context.previousStale'
  | 'creation.context.requestBudget'
  | 'creation.context.sessionBudget'
  | 'creation.context.outputReserve'
  | 'creation.context.actualUsage'
  | 'creation.context.reported'
  | 'creation.context.unavailable'
  | 'creation.context.sessionSeparate'
  | 'creation.context.retrieval'
  | 'creation.context.sources'
  | 'creation.context.protected'
  | 'creation.context.noSnippet'
  | 'creation.context.reason'
  | 'creation.context.missing'
  | 'creation.context.excluded'
  | 'creation.context.fullText'
  | 'creation.reviewEmpty'
  | 'creation.review.stale'
  | 'creation.review.casUnavailable'
  | 'creation.review.refreshRequired'
  | 'creation.review.closure'
  | 'creation.review.closureProposal'
  | 'creation.review.closureRevision'
  | 'creation.review.outcome.resolved'
  | 'creation.review.outcome.retained'
  | 'creation.review.outcome.regressed'
  | 'creation.review.selectionSummary'
  | 'creation.review.instruction'
  | 'creation.review.createRevision'
  | 'creation.review.rereview'
  | 'creation.review.revisionStarted'
  | 'creation.review.rereviewStarted'
  | 'creation.revisionsEmpty'
  | 'creation.history.title'
  | 'creation.history.snapshot'
  | 'creation.history.snapshotName'
  | 'creation.history.snapshotCreated'
  | 'creation.history.empty'
  | 'creation.history.units'
  | 'creation.history.loading'
  | 'creation.history.compare'
  | 'creation.history.restorePreview'
  | 'creation.history.closePreview'
  | 'creation.history.noChanges'
  | 'creation.history.restore'
  | 'creation.history.restoreConfirm'
  | 'creation.history.restored'
  | 'creation.history.previewFailed'
  | 'creation.history.reason.autosave'
  | 'creation.history.reason.manual'
  | 'creation.history.reason.aiRevision'
  | 'creation.history.reason.fullRewrite'
  | 'creation.history.reason.restore'
  | 'creation.proposals.title'
  | 'creation.proposals.noRationale'
  | 'creation.proposals.range'
  | 'creation.proposals.evidence'
  | 'creation.proposals.reviewRevision'
  | 'creation.proposals.sourceRevision'
  | 'creation.proposals.noHunks'
  | 'creation.proposals.originalCandidate'
  | 'creation.proposals.reject'
  | 'creation.proposals.regenerate'
  | 'creation.proposals.applySelected'
  | 'creation.proposals.appliedNeedsReview'
  | 'creation.issues'
  | 'creation.changedElsewhere'
  | 'creation.conflict'
  | 'creation.reload'
  | 'creation.overwrite'
  | 'creation.discardConfirm'
  | 'creation.overwriteConfirm'
  | 'creation.closePanel'
  | 'creation.draft.available'
  | 'creation.draft.conflict'
  | 'creation.draft.updated'
  | 'creation.draft.preview'
  | 'creation.draft.restore'
  | 'creation.draft.dismiss'
  | 'creation.draft.unavailable'
  | 'creation.status.idle'
  | 'creation.status.loading'
  | 'creation.status.saved'
  | 'creation.status.dirty'
  | 'creation.status.saving'
  | 'creation.status.conflict'
  | 'creation.status.offline'
  | 'operations.transfer'
  | 'operations.transferHint'
  | 'operations.project'
  | 'operations.create.new'
  | 'operations.create.id'
  | 'operations.create.title'
  | 'operations.create.submit'
  | 'operations.create.done'
  | 'operations.create.failed'
  | 'operations.create.pickHint'
  | 'operations.init.hint'
  | 'operations.init.submit'
  | 'operations.cancel'
  | 'workspace.unbound'
  | 'workspace.notInitialized'
  | 'workspace.bind.hint'
  | 'workspace.bind.pick'
  | 'workspace.bind.failed'
  | 'operations.create.titleHint'
  | 'tool.family.status'
  | 'tool.family.context'
  | 'tool.family.manuscript'
  | 'tool.family.revision'
  | 'tool.family.task'
  | 'tool.family.search'
  | 'tool.family.asset'
  | 'tool.family.outline'
  | 'tool.running'
  | 'tool.failed'
  | 'tool.succeeded'
  | 'tool.openChapter'
  | 'turn.changed'
  | 'turn.partial'
  | 'turn.failed'
  | 'turn.refreshFailed'
  | 'turn.history'
  | 'turn.proposed'
  | 'turn.rejected'
  | 'turn.entityChanges'
  | 'turn.before'
  | 'turn.after'
  | 'turn.missing'
  | 'turn.truncated'
  | 'turn.sourceRevision'
  | 'turn.resultRevision'
  | 'turn.committed'
  | 'turn.trace'
  | 'turn.modelCalls'
  | 'turn.days'
  | 'turn.accept'
  | 'turn.reject'
  | 'turn.retry'
  | 'turn.undo'
  | 'turn.applied'
  | 'turn.retried'
  | 'turn.undone'
  | 'resolving'
  | 'loading'
  | 'unreachable'
  | 'retry'
  | 'refresh'
  | 'openExternal'
  | 'outline.empty'
  | 'outline.drafted'
  | 'outline.planned'
  | 'outline.draftedCount'
  | 'outline.addChild'
  | 'outline.addAfter'
  | 'outline.addVolume'
  | 'outline.expandAll'
  | 'outline.collapseAll'
  | 'outline.del'
  | 'outline.confirmDelete'
  | 'outline.newTitlePlaceholder'
  | 'outline.opConflict'
  | 'outline.opFailed'
  | 'outline.summaryEmpty'
  | 'tools.title'
  | 'tools.export'
  | 'tools.export.done'
  | 'tools.export.failed'
  | 'tools.export.purpose'
  | 'tools.export.purpose.backup'
  | 'tools.export.purpose.delivery'
  | 'tools.export.format'
  | 'tools.export.preflight'
  | 'tools.export.loading'
  | 'tools.export.unavailable'
  | 'tools.export.refresh'
  | 'tools.export.revision'
  | 'tools.export.ready'
  | 'tools.export.blocked'
  | 'tools.export.download'
  | 'tools.export.order'
  | 'tools.export.orderEmpty'
  | 'tools.export.units'
  | 'tools.export.structure'
  | 'tools.export.structure.duplicates'
  | 'tools.export.structure.missing'
  | 'tools.export.structure.empty'
  | 'tools.export.structure.unreadable'
  | 'tools.export.clear'
  | 'tools.export.writingUnits'
  | 'tools.export.total'
  | 'tools.export.bookTarget'
  | 'tools.export.chapterTarget'
  | 'tools.export.completion'
  | 'tools.export.metadata'
  | 'tools.export.metadata.title'
  | 'tools.export.metadata.author'
  | 'tools.export.metadata.language'
  | 'tools.export.reviews'
  | 'tools.export.reviews.missing'
  | 'tools.export.reviews.current'
  | 'tools.export.reviews.stale'
  | 'tools.export.reviews.approved'
  | 'tools.export.reviews.notApproved'
  | 'tools.export.acceptance'
  | 'tools.export.acceptance.blocking'
  | 'tools.export.acceptance.blockingState'
  | 'tools.export.acceptance.needsReview'
  | 'tools.export.status'
  | 'tools.export.blockers'
  | 'tools.export.warnings'
  | 'tools.export.none'
  | 'tools.export.stale'
  | 'tools.sync'
  | 'tools.sync.done'
  | 'tools.sync.failed'
  | 'tools.import'
  | 'tools.import.empty'
  | 'tools.import.failed'
  | 'tools.import.done'
  | 'tools.import.choose'
  | 'tools.import.noFile'
  | 'tools.import.start'
  | 'tools.import.startAuto'
  | 'tools.import.preview'
  | 'tools.import.plan'
  | 'tools.import.conflicts'
  | 'tools.import.force'
  | 'tools.import.confirm'
  | 'tools.import.workspace.title'
  | 'tools.import.workspace.ownHint'
  | 'tools.import.workspace.operations'
  | 'tools.import.workspace.empty'
  | 'tools.import.workspace.new'
  | 'tools.import.workspace.file'
  | 'tools.import.workspace.arc'
  | 'tools.import.workspace.prepare'
  | 'tools.import.workspace.prepared'
  | 'tools.import.workspace.select'
  | 'tools.import.workspace.chapters'
  | 'tools.import.workspace.structure'
  | 'tools.import.workspace.chapterId'
  | 'tools.import.workspace.chapterTitle'
  | 'tools.import.workspace.chapterContent'
  | 'tools.import.workspace.moveUp'
  | 'tools.import.workspace.moveDown'
  | 'tools.import.workspace.remove'
  | 'tools.import.workspace.addChapter'
  | 'tools.import.workspace.newChapter'
  | 'tools.import.workspace.saveStructure'
  | 'tools.import.workspace.structureSaved'
  | 'tools.import.workspace.confirmStructure'
  | 'tools.import.workspace.confirmPrompt'
  | 'tools.import.workspace.confirmed'
  | 'tools.import.workspace.run'
  | 'tools.import.workspace.resume'
  | 'tools.import.workspace.taskStarted'
  | 'tools.import.workspace.discard'
  | 'tools.import.workspace.discardPrompt'
  | 'tools.import.workspace.discarded'
  | 'tools.import.workspace.recoverable'
  | 'tools.import.workspace.notRecoverable'
  | 'tools.import.stage.snapshot'
  | 'tools.import.stage.split'
  | 'tools.import.stage.structure_confirmed'
  | 'tools.import.stage.published'
  | 'tools.import.stage.acceptance'
  | 'tools.import.stage.reconcile'
  | 'tools.import.stage.synthesis'
  | 'tools.import.stage.complete'
  | 'tools.archive.title'
  | 'tools.archive.hint'
  | 'tools.archive.failed'
  | 'tools.archive.preflight'
  | 'tools.archive.create'
  | 'tools.archive.created'
  | 'tools.archive.list'
  | 'tools.archive.empty'
  | 'tools.archive.download'
  | 'tools.archive.downloaded'
  | 'tools.archive.files'
  | 'tools.archive.size'
  | 'tools.archive.categories'
  | 'tools.archive.includes'
  | 'tools.archive.excludes'
  | 'tools.archive.missing'
  | 'tools.archive.references'
  | 'tools.archive.referencePlan'
  | 'tools.archive.restore'
  | 'tools.archive.targetRoot'
  | 'tools.archive.pickTarget'
  | 'tools.archive.targetNovelId'
  | 'tools.archive.referencePolicy'
  | 'tools.archive.preserveRelative'
  | 'tools.archive.rewriteNovelId'
  | 'tools.archive.previewRestore'
  | 'tools.archive.restoreReady'
  | 'tools.archive.restoreBlocked'
  | 'tools.archive.conflicts'
  | 'tools.archive.pathRewrites'
  | 'tools.archive.rewrittenFiles'
  | 'tools.archive.rewrittenReferences'
  | 'tools.archive.preservedReferences'
  | 'tools.archive.referenceWarnings'
  | 'tools.archive.referenceConflicts'
  | 'tools.archive.tasksArchived'
  | 'tools.archive.autoResume'
  | 'tools.archive.noAutoResume'
  | 'tools.archive.confirmRestore'
  | 'tools.archive.restoreConfirm'
  | 'tools.archive.restoreStarted'
  | 'tasks.cancel'
  | 'tasks.cancel.title'
  | 'tasks.cancel.confirm'
  | 'tasks.cancel.done'
  | 'tasks.cancel.failed'
  | 'tasks.retry'
  | 'tasks.retry.title'
  | 'tasks.retry.notRecoverable'
  | 'tasks.retry.done'
  | 'tasks.retry.failed'
  | 'tasks.summary.total'
  | 'tasks.summary.updated'
  | 'tasks.filter.type'
  | 'tasks.filter.typeAll'
  | 'tasks.filter.chapter'
  | 'tasks.filter.keyword'
  | 'tasks.sort.newest'
  | 'tasks.sort.oldest'
  | 'tasks.sort.toggle'
  | 'tasks.progress.unknown'
  | 'tasks.phase.unknown'
  | 'tasks.confirm'
  | 'tasks.confirm.title'
  | 'tasks.confirm.done'
  | 'tasks.confirm.failed'
  | 'tasks.cancel.armYes'
  | 'tasks.cancel.armNo'
  | 'tasks.list'
  | 'tasks.detail.open'
  | 'tasks.detail.close'
  | 'tasks.detail.copyId'
  | 'tasks.detail.copied'
  | 'tasks.detail.events'
  | 'tasks.detail.eventsLoading'
  | 'tasks.detail.eventsEmpty'
  | 'tasks.detail.eventsFailed'
  | 'tasks.field.id'
  | 'tasks.field.type'
  | 'tasks.field.status'
  | 'tasks.field.phase'
  | 'tasks.field.chapter'
  | 'tasks.field.progress'
  | 'tasks.field.attempt'
  | 'tasks.field.created'
  | 'tasks.field.started'
  | 'tasks.field.updated'
  | 'tasks.field.completed'
  | 'tasks.field.summary'
  | 'tasks.field.resultRef'
  | 'tasks.field.failedStage'
  | 'tasks.field.errorCode'
  | 'tasks.field.recoverable'
  | 'tasks.field.yes'
  | 'tasks.field.no'
  | 'tasks.failure.cancelled'
  | 'tasks.failure.recoverable'
  | 'tasks.failure.provider'
  | 'tasks.failure.input'
  | 'tasks.failure.system'
  | 'tasks.jump.benchmark'
  | 'tasks.jump.research'
  | 'tasks.jump.chapter'
  | 'tasks.jump.review'
  | 'tasks.jump.unavailable'
  | 'tasks.jump.chapterHint'
  | 'tasks.jump.reviewHint'
  | 'tasks.jump.chapterMissing'
  | 'research.launch'
  | 'research.launch.placeholder'
  | 'research.launch.submit'
  | 'research.launch.submitting'
  | 'research.launch.submitted'
  | 'research.launch.failed'
  | 'research.launch.hint'
  | 'tasks.result.toggle'
  | 'tasks.result.score'
  | 'tasks.result.issues'
  | 'search.preview.back'
  | 'search.preview.openCreation'
  | 'search.preview.jumpReady'
  | 'search.preview.identityMismatch'
  | 'search.preview.locatorCurrent'
  | 'search.preview.locatorStale'
  | 'search.preview.locatorUnverified'
  | 'search.preview.revisionUnavailable'
  | 'search.change.title'
  | 'search.change.serverOwned'
  | 'search.change.unavailable'
  | 'search.change.currentLine'
  | 'search.change.replacement'
  | 'search.change.preview'
  | 'search.change.previewing'
  | 'search.change.sourceRevision'
  | 'search.change.resultRevision'
  | 'search.change.reject'
  | 'search.change.confirmApply'
  | 'search.change.applying'
  | 'search.change.refreshRequired'
  | 'search.change.invalidApply'
  | 'search.change.invalidReject'
  | 'search.change.applied'
  | 'search.change.rejected'
  | 'search.change.refresh'
  | 'assets.empty'
  | 'assets.other'
  | 'assets.stages'
  | 'assets.aliases'
  | 'assets.segment.characters'
  | 'assets.segment.world'
  | 'assets.segment.progression'
  | 'assets.segment.references'
  | 'assets.segment.core'
  | 'assets.segment.empty'
  | 'assets.references.empty'
  | 'assets.core.empty'
  | 'assets.detail.loading'
  | 'assets.detail.relations'
  | 'assets.detail.index'
  | 'assets.list.detail_refs'
  | 'assets.list.taboos'
  | 'assets.edit.linesHint'
  | 'assets.relation.confirmed'
  | 'assets.relation.registered'
  | 'assets.relation.incoming'
  | 'assets.searchPlaceholder'
  | 'assets.edit.open'
  | 'assets.edit.name'
  | 'assets.edit.summary'
  | 'assets.edit.tags'
  | 'assets.edit.listHint'
  | 'assets.edit.save'
  | 'assets.edit.saving'
  | 'assets.edit.cancel'
  | 'assets.edit.conflict'
  | 'assets.edit.conflictRefresh'
  | 'assets.edit.addRelation'
  | 'assets.edit.removeRelation'
  | 'assets.edit.relationTarget'
  | 'assets.edit.relationNote'
  | 'assets.edit.derivedRelations'
  | 'assets.edit.body'
  | 'assets.edit.liveLoading'
  | 'assets.edit.optional'
  | 'assets.field.tier'
  | 'assets.field.personality'
  | 'assets.field.goal'
  | 'assets.field.fear'
  | 'assets.field.appearance'
  | 'assets.field.voice'
  | 'assets.field.current_state'
  | 'assets.field.organization'
  | 'assets.field.progression_system'
  | 'assets.field.progression_stage'
  | 'assets.field.status'
  | 'assets.field.kind'
  | 'assets.field.type'
  | 'assets.field.subtype'
  | 'assets.field.state_updated_at'
  | 'assets.field.role'
  | 'assets.edit.liveFailed'
  | 'assets.selectHint'
  | 'assets.create.open'
  | 'assets.create.submit'
  | 'assets.create.idHint'
  | 'assets.create.tier'
  | 'assets.create.type'
  | 'assets.create.progressionKind'
  | 'assets.create.stages'
  | 'assets.create.stageId'
  | 'assets.create.stageName'
  | 'assets.create.addStage'
  | 'tasks.empty'
  | 'tasks.filter.all'
  | 'tasks.attempt'
  | 'tasks.status.pending'
  | 'tasks.status.running'
  | 'tasks.status.awaiting_confirmation'
  | 'tasks.status.completed'
  | 'tasks.status.failed'
  | 'tasks.status.cancelled'
  | 'tasks.status.interrupted'
  | 'tasks.phase.queued'
  | 'tasks.phase.reading'
  | 'tasks.phase.preparing'
  | 'tasks.phase.model'
  | 'tasks.phase.validating'
  | 'tasks.phase.committing'
  | 'tasks.phase.complete'
  | 'tasks.type.chapter_write'
  | 'tasks.type.chapter_review'
  | 'tasks.type.continuous_write'
  | 'tasks.type.revision'
  | 'tasks.type.source_operation'
  | 'tasks.type.reference_operation'
  | 'tasks.type.manuscript_import'
  | 'tasks.type.project_restore'
  | 'tasks.type.research'
  | 'tasks.type.model_benchmark'
  | 'graph.foreshadowing'
  | 'graph.relationships'
  | 'graph.nodes'
  | 'graph.connections'
  | 'graph.relayout'
  | 'graph.weight'
  | 'graph.target'
  | 'graph.truncated'
  | 'graph.validation.errors'
  | 'graph.empty.foreshadowing'
  | 'graph.empty.relationships'
  | 'graph.entityType'
  | 'graph.entityStatus'
  | 'graph.search'
  | 'graph.connectedOnly'
  | 'graph.neighbors'
  | 'graph.edgeType'
  | 'graph.origin'
  | 'graph.source'
  | 'graph.confirmed'
  | 'dag.quality'
  | 'dag.coverage'
  | 'dag.gate'
  | 'dag.delivery'
  | 'dag.current'
  | 'dag.stale'
  | 'dag.toRevision'
  | 'dag.toRevisionDone'
  | 'dag.toRevisionFailed'
  | 'graph.unresolved'
  | 'graph.kind.character'
  | 'graph.kind.faction'
  | 'graph.kind.place'
  | 'graph.kind.concept'
  | 'graph.kind.other'
  | 'graph.truth'
  | 'graph.truth.currentState'
  | 'graph.truth.ledger'
  | 'graph.truth.relationships'
  | 'graph.workflows'
  | 'graph.workflow.currentStage'
  | 'graph.empty.truth'
  | 'graph.empty.truthDoc'
  | 'graph.empty.workflows'
  | 'graph.reviewDag'
  | 'graph.reviewFramework'
  | 'graph.reviewDomains'
  | 'graph.reviewChecks'
  | 'graph.reviewCriteria'
  | 'graph.deliveryDag'
  | 'graph.filter.all'
  | 'graph.filter.anomaly'
  | 'graph.filter.blocker'
  | 'graph.expandChecks'
  | 'graph.collapseChecks'
  | 'graph.empty.dag'
  | 'benchmark.title'
  | 'benchmark.task'
  | 'benchmark.mode'
  | 'benchmark.mode.framework'
  | 'benchmark.mode.creative'
  | 'benchmark.mode.unknown'
  | 'benchmark.reviewer'
  | 'benchmark.chapter'
  | 'benchmark.repeats'
  | 'benchmark.words'
  | 'benchmark.concurrency'
  | 'benchmark.run'
  | 'benchmark.empty'
  | 'benchmark.select'
  | 'benchmark.averageScore'
  | 'benchmark.output'
  | 'benchmark.candidate'
  | 'benchmark.candidates'
  | 'benchmark.evaluations'
  | 'benchmark.writer'
  | 'benchmark.path'
  | 'benchmark.status'
  | 'benchmark.actualWords'
  | 'benchmark.finishReason'
  | 'benchmark.error'
  | 'benchmark.coverage'
  | 'benchmark.gate'
  | 'benchmark.delivery'
  | 'benchmark.productionGate'
  | 'benchmark.productionGateMissing'
  | 'benchmark.domains'
  | 'benchmark.latency'
  | 'benchmark.usage'
  | 'benchmark.cost'
  | 'benchmark.inputTokens'
  | 'benchmark.outputTokens'
  | 'benchmark.reasoningTokens'
  | 'benchmark.totalTokens'
  | 'benchmark.actualCost'
  | 'benchmark.costCoverage'
  | 'benchmark.effectiveRate'
  | 'benchmark.runs'
  | 'benchmark.sameInputGroup'
  | 'benchmark.comparisonIncomplete'
  | 'benchmark.inputProvenance'
  | 'benchmark.runPhases'
  | 'benchmark.phase.created'
  | 'benchmark.phase.started'
  | 'benchmark.phase.completed'
  | 'benchmark.contextHash'
  | 'benchmark.comparisonKey'
  | 'benchmark.promptVersion'
  | 'benchmark.rubricVersion'
  | 'benchmark.blindReview'
  | 'benchmark.contextStrategy'
  | 'benchmark.manifestVersion'
  | 'benchmark.tokenEstimator'
  | 'benchmark.packetRevision'
  | 'benchmark.sourceRevision'
  | 'benchmark.estimatedTokens'
  | 'benchmark.characters'
  | 'benchmark.contextSources'
  | 'benchmark.sourcePresent'
  | 'benchmark.sourceMissing'
  | 'benchmark.responseIdentity'
  | 'models.title'
  | 'models.list'
  | 'models.editor'
  | 'models.new'
  | 'models.empty'
  | 'models.id'
  | 'models.label'
  | 'models.provider'
  | 'models.protocol.openai'
  | 'models.protocol.anthropic'
  | 'models.modelId'
  | 'models.baseUrl'
  | 'models.apiFormat'
  | 'models.context'
  | 'models.output'
  | 'models.credential'
  | 'models.embeddingProvider'
  | 'models.embeddingModel'
  | 'models.embeddingCredential'
  | 'models.credentialHint'
  | 'models.remember'
  | 'models.save'
  | 'models.chatTest'
  | 'models.embeddingTest'
  | 'models.delete'
  | 'models.delete.confirm'
  | 'models.delete.blocked'
  | 'models.delete.wouldFail'
  | 'models.test.untested'
  | 'models.test.ok'
  | 'models.test.failed'
  | 'models.dependencies'
  | 'models.dependenciesHint'
  | 'models.fallback'
  | 'models.chooseFallback'
  | 'models.routes'
  | 'models.routesSave'
  | 'models.saved'
  | 'models.deleted'
  | 'models.chatOk'
  | 'models.embeddingOk'
  | 'models.configured'
  | 'models.missing'
  | 'models.routesSaved'
  | 'models.group.basic'
  | 'models.group.connection'
  | 'models.group.generation'
  | 'models.group.embedding'
  | 'models.group.credentials'
  | 'models.group.routeUsage'
  | 'models.temperature'
  | 'models.timeout'
  | 'models.embeddingBaseUrl'
  | 'models.validation.required'
  | 'models.validation.positive'
  | 'models.validation.temperature'
  | 'models.unsavedChanges'
  | 'models.unsavedDiscard'
  | 'models.unsavedKeep'
  | 'models.test.loading'
  | 'models.usedByRoutes'
  | 'models.noRoutes'
  | 'models.delete.resultingRoutes'
  | 'models.embeddingEmpty'
  | 'models.embeddingConfigured'
  | 'models.embeddingMissing'
  | 'models.active'
  | 'models.inactive'
  | 'models.route.goethe'
  | 'models.route.dante'
  | 'models.route.chapter_write'
  | 'models.route.review'
  | 'models.route.source_extract'
  | 'models.route.revision'
  | 'models.route.search'
  | 'models.route.research'
  | 'models.routesImpact'
  | 'models.routesUnchanged'
  | 'models.routesUnassigned'
  | 'models.embedConfigured'
  | 'models.embedMissing'
  | 'models.capability.chat'
  | 'models.capability.embedding'
  | 'research.reports'
  | 'research.unavailable'
  | 'research.empty'
  | 'research.selectHint'
  | 'research.report.loading'
  | 'research.quality'
  | 'research.language'
  | 'research.filter.keyword'
  | 'research.filter.status'
  | 'research.filter.sources'
  | 'research.filter.all'
  | 'research.status.succeeded'
  | 'research.status.failed'
  | 'research.status.needsReview'
  | 'research.status.unknown'
  | 'research.sourcesAvailable'
  | 'research.sourcesUnavailable'
  | 'research.sourcesEmpty'
  | 'research.sources'
  | 'research.sourceCheck'
  | 'research.source.cited'
  | 'research.source.uncited'
  | 'research.exportMarkdown'
  | 'research.referenceOnly'
  | 'research.prompt'
  | 'research.taskId'
  | 'research.episodeId'
  | 'research.model'
  | 'research.searchProvider'
  | 'research.createdAt'
  | 'research.completedAt'
  | 'research.latency'
  | 'research.wordCount'
  | 'research.tokens'
  | 'research.cost'
  | 'research.sourcesStatus'
  | 'research.metrics'
  | 'search.placeholder'
  | 'search.hint'
  | 'search.empty'
  | 'search.indexed'
  | 'search.timeout'
  | 'search.scope.all'
  | 'search.scope.outline'
  | 'search.scope.core'
  | 'search.scope.characters'
  | 'search.scope.settings'
  | 'search.scope.continuity'
  | 'search.scope.chapters'
  | 'search.scope.sources'
  | 'assets.references'
  | 'reference.intent.reference'
  | 'reference.intent.continuation'
  | 'reference.intent.canon'
  | 'reference.intent.migration'
  | 'reference.structure.awaiting_confirmation'
  | 'reference.structure.confirmed'
  | 'reference.analysis.complete'
  | 'reference.analysis.pending'
  | 'reference.chars'
  | 'reference.content.loading'
  | 'reference.content.full'
  | 'review.running'
  | 'review.passed'
  | 'review.failed'
  | 'review.score'
  | 'review.issues'
  | 'review.suggestion'
  | 'review.quote'
  | 'review.dimension'
  | 'review.coverage'
  | 'review.gate'
  | 'review.delivery'
  | 'review.execution'
  | 'review.priority'
  | 'review.severity.critical'
  | 'review.severity.warning'
  | 'review.severity.info'
  | 'review.severity.blocker'
  | 'review.severity.high'
  | 'review.severity.medium'
  | 'review.severity.low'
  | 'review.priority.blocker'
  | 'review.priority.high'
  | 'review.priority.medium'
  | 'review.priority.low'
  | 'review.status.pass'
  | 'review.status.blocked'
  | 'review.status.inconclusive'
  | 'review.status.revise'
  | 'review.status.completed'
  | 'review.status.partial'
  | 'review.status.failed'
  | 'review.status.stale'
  | 'review.status.unknown'
  | 'review.rawTitle'

declare module '@deepseek-ai/dsh-client-ui-slots' {
  interface LocaleNamespaceMap {
    /** The 稿件/大纲/资产 view tab labels and panel state strings. */
    'studio-panel': StudioPanelKey
  }
}

/** Simplified Chinese dictionary (the key-set source of truth). */
export const zh: Record<StudioPanelKey, string> = {
  'view.overview': '总览',
  'view.writing': '写作',
  'view.studio': '正文',
  'view.reviewWs': '审稿',
  'view.outline': '大纲',
  'view.assets': '资产',
  'view.tasks': '任务',
  'view.benchmark': '模型测试',
  'view.models': '模型',
  'view.graph': '图谱',
  'view.research': '研究',
  'view.search': '搜索',
  'view.creation': '创作',
  'view.library': '资料',
  'view.operations': '任务',
  'creation.chapters': '章节',
  'creation.searchChapters': '搜索章节',
  'creation.clearSearch': '清除章节搜索',
  'creation.chaptersEmpty': '没有匹配的章节。',
  'creation.previousChapter': '上一章',
  'creation.nextChapter': '下一章',
  'creation.jumpChapter': '跳转章节',
  'creation.chapterDuplicate': '重复项，等待稳定文档身份',
  'creation.order.loading': '正在核对章节顺序…',
  'creation.order.unavailable': '规范章节顺序暂不可用；当前显示工作区列表。',
  'creation.order.refresh': '刷新顺序',
  'creation.order.invalid': '章节顺序的身份或 revision 无效，请刷新。',
  'creation.order.missingCount': '规划中、尚无正文的章节：',
  'creation.order.move': '调整章节顺序',
  'creation.order.volume': '目标卷',
  'creation.order.position': '位置',
  'creation.order.positionHelp': '位置按目标卷完整大纲计算（包含尚无正文的规划章），范围',
  'creation.order.applyMove': '移动章节',
  'creation.order.blocked': '章节顺序存在歧义或缺失，修复后才能移动。',
  'creation.order.moveComplete': '章节已移动，并已刷新规范阅读顺序。',
  'creation.order.conflict': '章节顺序已变化，已刷新；请核对后重新移动。',
  'creation.mode.edit': '返回编辑',
  'creation.mode.reader': '连续审读',
  'creation.writing.bookProgress': '全书进度',
  'creation.writing.chapterTarget': '章目标',
  'creation.writing.chapterProgress': '本章进度',
  'creation.reader.title': '连续审读',
  'creation.reader.readOnly': '按服务端章节顺序读取；每章标注当前 revision。',
  'creation.reader.loading': '正在载入全书正文…',
  'creation.reader.refresh': '刷新正文',
  'creation.reader.openEditor': '打开编辑',
  'creation.reader.path': '路径',
  'creation.reader.documentId': '文档身份',
  'creation.reader.revision': '正文 revision',
  'creation.reader.revisionUnavailable': '服务端未提供',
  'creation.showChapters': '展开章节栏',
  'creation.hideChapters': '收起章节栏',
  'creation.inspector': '检查器',
  'creation.showInspector': '展开检查器',
  'creation.hideInspector': '收起检查器',
  'creation.editorLoading': '正在准备编辑器…',
  'creation.documentLoading': '正在载入正文…',
  'creation.inspectorLoading': '正在整理本章上下文…',
  'creation.inspectorLoadingSlow': '上下文仍在整理，正文编辑不受影响。',
  'creation.empty': '尚无章节',
  'creation.acceptance.title': '正文接纳状态',
  'creation.acceptance.loading': '正在核对',
  'creation.acceptance.current': '已接纳',
  'creation.acceptance.pending': '处理中，可恢复',
  'creation.acceptance.drift': '检测到外部正文变化',
  'creation.acceptance.baselinePending': '需要建立接纳基线',
  'creation.acceptance.needsReview': '需要作者复核',
  'creation.acceptance.failed': '处理失败，可恢复',
  'creation.acceptance.unknown': '状态未知',
  'creation.acceptance.unavailable': '接纳状态暂不可用',
  'creation.acceptance.currentRevision': '当前正文 revision',
  'creation.acceptance.acceptedRevision': '已接纳 revision',
  'creation.acceptance.operation': '接纳操作',
  'creation.acceptance.stale': '已过期派生结果',
  'creation.acceptance.refresh': '刷新接纳状态',
  'creation.acceptance.baseline': '以当前正文建立基线',
  'creation.acceptance.external': '接纳外部变化',
  'creation.acceptance.resume': '继续未完成操作',
  'creation.acceptance.acknowledge': '确认已复核',
  'creation.acceptance.confirmBaseline': '确认以当前正文建立接纳基线？这会启动分析并刷新受影响的派生结果。',
  'creation.acceptance.confirmExternal': '确认接纳磁盘上的外部正文变化？这会启动分析并刷新受影响的派生结果。',
  'creation.acceptance.confirmAcknowledge': '确认你已复核本次正文接纳及其影响？',
  'creation.context': '上下文',
  'creation.review': '审稿',
  'creation.revisions': '修订',
  'creation.activity': '动态',
  'creation.activity.loading': '正在读取本章工作动态…',
  'creation.activity.unavailable': '本章工作动态暂不可用。',
  'creation.activity.invalid': '本章工作摘要身份或版本不匹配，请刷新。',
  'creation.activity.target': '本章字数目标',
  'creation.activity.remaining': '尚余',
  'creation.activity.identity': '当前身份与版本',
  'creation.activity.recent': '最近修改',
  'creation.activity.empty': '本章还没有修改记录。',
  'creation.contextEmpty': '本章暂无可用上下文。',
  'creation.context.packet': '实际写章包 revision',
  'creation.context.current': '当前',
  'creation.context.stale': '已过期',
  'creation.context.previousStale': '来源已变化，旧上下文包已过期：',
  'creation.context.requestBudget': 'OpenWrite 写章请求预算',
  'creation.context.sessionBudget': 'dsh 会话预算',
  'creation.context.outputReserve': '输出预留',
  'creation.context.actualUsage': '真实用量',
  'creation.context.reported': '已报告',
  'creation.context.unavailable': '不可用',
  'creation.context.sessionSeparate': '由 dsh 会话运行时独立计量，不与写章请求相加。',
  'creation.context.retrieval': '语义检索',
  'creation.context.sources': '实际来源与选择结果',
  'creation.context.protected': '受保护',
  'creation.context.noSnippet': '无可显示片段',
  'creation.context.reason': '选择原因',
  'creation.context.missing': '缺失',
  'creation.context.excluded': '已排除',
  'creation.context.fullText': '查看最终渲染文本',
  'creation.reviewEmpty': '本章暂无审稿结果。',
  'creation.review.stale': '审稿基于旧正文。请先复评，旧问题不可直接生成修订。',
  'creation.review.casUnavailable': '尚未取得可校验的审稿与正文 revision，刷新后才能生成修订。',
  'creation.review.refreshRequired': '审稿或正文已变化。请刷新本章摘要，重新选择问题后再生成修订。',
  'creation.review.closure': '最近复评结论',
  'creation.review.closureProposal': '修订提案',
  'creation.review.closureRevision': '复评 revision',
  'creation.review.outcome.resolved': '已解决',
  'creation.review.outcome.retained': '仍保留',
  'creation.review.outcome.regressed': '新增回归',
  'creation.review.selectionSummary': '选择要修复的问题；未选问题会保留',
  'creation.review.instruction': '补充修订要求（可选）',
  'creation.review.createRevision': '生成所选问题的修订',
  'creation.review.rereview': '启动复评',
  'creation.review.revisionStarted': '修订生成任务已启动；完成后在“修订”页检查 diff。',
  'creation.review.rereviewStarted': '复评任务已启动；任务完成后会刷新审稿状态。',
  'creation.revisionsEmpty': '本章暂无修订提案。',
  'creation.history.title': '正文历史',
  'creation.history.snapshot': '命名快照',
  'creation.history.snapshotName': '为当前正文快照命名：',
  'creation.history.snapshotCreated': '正文快照已创建。',
  'creation.history.empty': '本章还没有可恢复的历史版本。',
  'creation.history.units': '字',
  'creation.history.loading': '读取中…',
  'creation.history.compare': '比较',
  'creation.history.restorePreview': '恢复预览：当前正文 → 旧版本',
  'creation.history.closePreview': '关闭恢复预览',
  'creation.history.noChanges': '当前正文与该版本相同。',
  'creation.history.restore': '恢复此版本',
  'creation.history.restoreConfirm': '确认恢复此版本？恢复前的当前正文会自动保存为新版本。',
  'creation.history.restored': '旧版本已恢复，恢复前正文已保留。',
  'creation.history.previewFailed': '无法读取版本比较结果。',
  'creation.history.reason.autosave': '自动保存批次',
  'creation.history.reason.manual': '手动保存',
  'creation.history.reason.aiRevision': 'AI 修订前',
  'creation.history.reason.fullRewrite': '整章重写前',
  'creation.history.reason.restore': '历史恢复前',
  'creation.proposals.title': '修订提案',
  'creation.proposals.noRationale': '未提供修改原因。',
  'creation.proposals.range': '原文范围：',
  'creation.proposals.evidence': '评审证据：',
  'creation.proposals.reviewRevision': '评审 revision：',
  'creation.proposals.sourceRevision': '提案来源 revision：',
  'creation.proposals.noHunks': '无关联差异块',
  'creation.proposals.originalCandidate': '查看原文与候选',
  'creation.proposals.reject': '拒绝',
  'creation.proposals.regenerate': '重新生成',
  'creation.proposals.applySelected': '应用所选差异',
  'creation.proposals.appliedNeedsReview': '所选差异已应用；请启动复评确认问题是否闭环。',
  'creation.issues': '个问题',
  'creation.changedElsewhere': '正文已在其他位置变化；当前草稿未被覆盖。',
  'creation.conflict': '保存冲突：服务端正文已变化，当前草稿仍保留。',
  'creation.reload': '载入服务端版本',
  'creation.overwrite': '覆盖保存',
  'creation.discardConfirm': '当前草稿尚未保存，确认放弃并载入其他内容？',
  'creation.overwriteConfirm': '确认以当前草稿覆盖服务端的较新版本？此操作会创建检查点。',
  'creation.closePanel': '关闭面板',
  'creation.draft.available': '发现未保存的本地恢复稿。',
  'creation.draft.conflict': '本地恢复稿基于较旧正文，恢复后需确认如何处理冲突。',
  'creation.draft.updated': '本地保存时间：',
  'creation.draft.preview': '查看恢复稿',
  'creation.draft.restore': '恢复到编辑器',
  'creation.draft.dismiss': '忽略并删除',
  'creation.draft.unavailable': '本地恢复保护不可用；当前编辑器内容仍会保留到本页关闭前。',
  'creation.status.idle': '未打开',
  'creation.status.loading': '载入中',
  'creation.status.saved': '已保存',
  'creation.status.dirty': '未保存',
  'creation.status.saving': '保存中',
  'creation.status.conflict': '有冲突',
  'creation.status.offline': '离线',
  'operations.transfer': '导入与导出',
  'operations.transferHint': '在当前作品范围内执行导出、同步和章节导入。',
  'operations.project': '当前 Workspace',
  'operations.create.new': '+ 新建作品',
  'operations.create.id': '小说 ID',
  'operations.create.title': '书名',
  'operations.create.titleHint': '书名',
  'operations.create.submit': '创建作品',
  'operations.create.done': '「{title}」已创建',
  'operations.create.failed': '创建失败',
  'operations.create.pickHint': '将在系统目录选择器中选择项目目录',
  'operations.init.hint': '当前 Workspace 尚未初始化为小说项目，填写小说 ID 与书名完成初始化。',
  'operations.init.submit': '初始化项目',
  'operations.cancel': '取消',
  'workspace.unbound': '未选择 Workspace',
  'workspace.notInitialized': '待初始化',
  'workspace.bind.hint': '当前会话没有关联工作区。选择一个目录作为工作区后，即可初始化小说项目。',
  'workspace.bind.pick': '选择目录作为工作区',
  'workspace.bind.failed': '关联工作区失败',
  'tool.family.status': '作品状态',
  'tool.family.context': '章节上下文',
  'tool.family.manuscript': '正文',
  'tool.family.revision': '修订',
  'tool.family.task': '任务',
  'tool.family.search': '搜索',
  'tool.family.asset': '资料',
  'tool.family.outline': '大纲',
  'tool.running': '执行中',
  'tool.failed': '执行失败',
  'tool.succeeded': '已完成',
  'tool.openChapter': '打开章节',
  'turn.changed': '本轮已更新',
  'turn.partial': '本轮部分更新',
  'turn.failed': '本轮写入失败',
  'turn.refreshFailed': '写入成功，界面刷新失败',
  'turn.history': '历史版本',
  'turn.proposed': '本轮提出待确认变更',
  'turn.rejected': '本轮已拒绝变更',
  'turn.entityChanges': '项实体变更',
  'turn.before': '修改前',
  'turn.after': '修改后',
  'turn.missing': '不存在',
  'turn.truncated': '节选，完整值过长',
  'turn.sourceRevision': '来源版本',
  'turn.resultRevision': '结果版本',
  'turn.committed': '已提交',
  'turn.trace': 'Trace',
  'turn.modelCalls': '次模型调用',
  'turn.days': '天保留',
  'turn.accept': '接受并应用',
  'turn.reject': '拒绝',
  'turn.retry': '按当前版本重试',
  'turn.undo': '安全撤销',
  'turn.applied': '变更已按预览内容提交。',
  'turn.retried': '已根据当前源文件生成新预览。',
  'turn.undone': '变更已安全撤销。',
  resolving: '正在读取 Studio 配置…',
  loading: '正在载入…',
  unreachable: '无法连接 OpenWrite Studio。请确认 Studio 已启动（默认 http://127.0.0.1:4567）。',
  retry: '重试',
  refresh: '刷新',
  openExternal: '在新标签页打开',
  'outline.empty': '大纲为空。在 Studio 中创建 src/outline.md 后刷新。',
  'outline.drafted': '已成稿',
  'outline.planned': '待写',
  'outline.draftedCount': '已成稿章节',
  'outline.addChild': '新增下级',
  'outline.addAfter': '新增同级',
  'outline.addVolume': '新增卷',
  'outline.expandAll': '展开全部',
  'outline.collapseAll': '收起全部',
  'outline.del': '删',
  'outline.confirmDelete': '确认删除以下节点及其全部下级：',
  'outline.newTitlePlaceholder': '新标题（章需含章节号，如“第12章：转折”）',
  'outline.opConflict': '大纲已在其他位置变化，已刷新结构，请重试操作。',
  'outline.opFailed': '操作失败',
  'outline.summaryEmpty': '（空）',
  'tools.title': '工具箱',
  'tools.export': '导出',
  'tools.export.done': '已导出 {name}',
  'tools.export.failed': '导出失败',
  'tools.export.purpose': '导出用途',
  'tools.export.purpose.backup': '完整备份',
  'tools.export.purpose.delivery': '交付成品',
  'tools.export.format': '格式',
  'tools.export.preflight': '导出预检',
  'tools.export.loading': '正在核对当前正文…',
  'tools.export.unavailable': '无法读取有效的导出预检',
  'tools.export.refresh': '重新预检',
  'tools.export.revision': '预检版本',
  'tools.export.ready': '可以导出',
  'tools.export.blocked': '存在阻断项',
  'tools.export.download': '按当前预检导出',
  'tools.export.order': '实际章节顺序',
  'tools.export.orderEmpty': '没有可导出的章节',
  'tools.export.units': '写作单元',
  'tools.export.structure': '结构检查',
  'tools.export.structure.duplicates': '重复章节号',
  'tools.export.structure.missing': '缺失章节',
  'tools.export.structure.empty': '空章节',
  'tools.export.structure.unreadable': '无法读取',
  'tools.export.clear': '未发现问题',
  'tools.export.writingUnits': '篇幅与目标',
  'tools.export.total': '当前总量',
  'tools.export.bookTarget': '全书目标',
  'tools.export.chapterTarget': '单章目标',
  'tools.export.completion': '完成度',
  'tools.export.metadata': '书籍元数据',
  'tools.export.metadata.title': '书名',
  'tools.export.metadata.author': '作者',
  'tools.export.metadata.language': '语言',
  'tools.export.reviews': '复核新鲜度',
  'tools.export.reviews.missing': '缺少复核',
  'tools.export.reviews.current': '当前有效',
  'tools.export.reviews.stale': '已过期',
  'tools.export.reviews.approved': '已通过',
  'tools.export.reviews.notApproved': '未通过',
  'tools.export.acceptance': '正文接纳状态',
      'tools.export.acceptance.blocking': '阻断章节',
      'tools.export.acceptance.blockingState': '接纳阻断',
      'tools.export.acceptance.needsReview': '待复核领域',
  'tools.export.status': '状态',
  'tools.export.blockers': '阻断项',
  'tools.export.warnings': '警告',
  'tools.export.none': '无',
  'tools.export.stale': '正文已变化，导出预检已自动刷新，请核对后重试。',
  'tools.sync': '同步项目',
  'tools.sync.done': '项目已同步',
  'tools.sync.failed': '同步失败',
  'tools.import': '导入章节',
  'tools.import.empty': '导入内容为空',
  'tools.import.failed': '导入失败',
  'tools.import.done': '已导入 {count} 章（起始 ch_{start}），刷新大纲/正文可见',
  'tools.import.choose': '选择文件',
  'tools.import.noFile': '未选择文件',
  'tools.import.start': '起始章节号',
  'tools.import.startAuto': '自动',
  'tools.import.preview': '预览',
  'tools.import.plan': '将导入 {count} 章 / {units} 写作单元，起始 ch_{start}（{arc}）。',
  'tools.import.conflicts': '冲突：{ids} 已存在。',
  'tools.import.force': '强制覆盖导入',
  'tools.import.confirm': '确认导入',
  'tools.import.workspace.title': '我的旧稿导入工作区',
  'tools.import.workspace.ownHint': '导入作者自己的小说正文，可保存切分结果并在中断后继续；这里不会把内容加入参考资料库。',
  'tools.import.workspace.operations': '可恢复导入记录',
  'tools.import.workspace.empty': '还没有旧稿导入记录',
  'tools.import.workspace.new': '准备新的旧稿',
  'tools.import.workspace.file': '作者旧稿文件',
  'tools.import.workspace.arc': '目标篇',
  'tools.import.workspace.prepare': '快照并切分',
  'tools.import.workspace.prepared': '旧稿已快照，等待核对章节结构',
  'tools.import.workspace.select': '选择一条导入记录查看详情',
  'tools.import.workspace.chapters': '章',
  'tools.import.workspace.structure': '章节边界与标题',
  'tools.import.workspace.chapterId': '章节 ID',
  'tools.import.workspace.chapterTitle': '章节标题',
  'tools.import.workspace.chapterContent': '章节正文',
  'tools.import.workspace.moveUp': '上移章节',
  'tools.import.workspace.moveDown': '下移章节',
  'tools.import.workspace.remove': '移除章节',
  'tools.import.workspace.addChapter': '增加章节边界',
  'tools.import.workspace.newChapter': '新章节',
  'tools.import.workspace.saveStructure': '保存边界调整',
  'tools.import.workspace.structureSaved': '章节结构已保存，请再次核对后确认',
  'tools.import.workspace.confirmStructure': '确认发布结构',
  'tools.import.workspace.confirmPrompt': '确认以当前章节顺序、边界和标题发布这份旧稿？',
  'tools.import.workspace.confirmed': '章节结构已确认，可以运行导入',
  'tools.import.workspace.run': '运行导入',
  'tools.import.workspace.resume': '继续导入',
  'tools.import.workspace.taskStarted': '导入任务已启动：{id}',
  'tools.import.workspace.discard': '丢弃导入记录',
  'tools.import.workspace.discardPrompt': '确认丢弃这条尚未发布的旧稿导入记录？',
  'tools.import.workspace.discarded': '旧稿导入记录已丢弃',
  'tools.import.workspace.recoverable': '可继续',
  'tools.import.workspace.notRecoverable': '不可继续',
  'tools.import.stage.snapshot': '源文件快照',
  'tools.import.stage.split': '正文切分',
  'tools.import.stage.structure_confirmed': '结构确认',
  'tools.import.stage.published': '正文发布',
  'tools.import.stage.acceptance': '接纳登记',
  'tools.import.stage.reconcile': '派生调和',
  'tools.import.stage.synthesis': '事实综合',
  'tools.import.stage.complete': '完成',
  'tools.archive.title': '完整作品档案',
  'tools.archive.hint': '归档正文、结构、修订、复核和任务记录；敏感配置与缓存不会写入档案。',
  'tools.archive.failed': '作品档案操作失败',
  'tools.archive.preflight': '归档预检版本',
  'tools.archive.create': '按当前预检创建档案',
  'tools.archive.created': '作品档案已创建：{id}',
  'tools.archive.list': '已有档案',
  'tools.archive.empty': '还没有作品档案',
  'tools.archive.download': '下载档案',
  'tools.archive.downloaded': '已下载 {name}',
  'tools.archive.files': '文件',
  'tools.archive.size': '字节',
  'tools.archive.categories': '内容类别',
  'tools.archive.includes': '纳入档案',
  'tools.archive.excludes': '排除内容',
  'tools.archive.missing': '缺失内容',
  'tools.archive.references': '引用计划',
  'tools.archive.referencePlan': '可识别引用 {known} · 原样保留 {preserved} · 警告 {warnings}',
  'tools.archive.restore': '恢复到新 Workspace',
  'tools.archive.targetRoot': '目标绝对路径',
  'tools.archive.pickTarget': '选择目标目录',
  'tools.archive.targetNovelId': '恢复后的小说 ID（可选）',
  'tools.archive.referencePolicy': '引用策略',
  'tools.archive.preserveRelative': '保留相对引用',
  'tools.archive.rewriteNovelId': '随小说 ID 重写引用',
  'tools.archive.previewRestore': '预览恢复',
  'tools.archive.restoreReady': '可以恢复',
  'tools.archive.restoreBlocked': '存在恢复冲突',
  'tools.archive.conflicts': '冲突',
  'tools.archive.pathRewrites': '路径改写',
  'tools.archive.rewrittenFiles': '改写文件',
  'tools.archive.rewrittenReferences': '改写引用',
  'tools.archive.preservedReferences': '保留引用',
  'tools.archive.referenceWarnings': '引用警告',
  'tools.archive.referenceConflicts': '引用冲突',
  'tools.archive.tasksArchived': '旧任务文件 {count} 个将移入任务档案',
  'tools.archive.autoResume': '旧任务将自动继续',
  'tools.archive.noAutoResume': '旧任务不会自动继续',
  'tools.archive.confirmRestore': '确认恢复',
  'tools.archive.restoreConfirm': '确认把档案恢复到预览中的新目录？旧任务只归档，不会自动继续。',
  'tools.archive.restoreStarted': '恢复任务已启动：{id}',
  'tasks.cancel': '取消',
  'tasks.cancel.title': '取消该任务',
  'tasks.cancel.confirm': '确认取消这个正在排队的任务？',
  'tasks.cancel.done': '任务已取消',
  'tasks.cancel.failed': '取消失败',
  'tasks.retry': '重试',
  'tasks.retry.title': '重试该任务',
  'tasks.retry.notRecoverable': '该失败不可恢复，无法重试',
  'tasks.retry.done': '任务已重新排队',
  'tasks.retry.failed': '重试提交失败',
  'tasks.summary.total': '总计',
  'tasks.summary.updated': '更新于 {time}',
  'tasks.filter.type': '类型',
  'tasks.filter.typeAll': '全部类型',
  'tasks.filter.chapter': '章节 / 对象',
  'tasks.filter.keyword': '搜索摘要 / ID / 章节',
  'tasks.sort.newest': '最新在前',
  'tasks.sort.oldest': '最早在前',
  'tasks.sort.toggle': '切换时间排序',
  'tasks.progress.unknown': '进度未知',
  'tasks.phase.unknown': '阶段未知',
  'tasks.confirm': '确认',
  'tasks.confirm.title': '确认该任务',
  'tasks.confirm.done': '任务已确认',
  'tasks.confirm.failed': '确认提交失败',
  'tasks.cancel.armYes': '确认取消',
  'tasks.cancel.armNo': '保留',
  'tasks.list': '任务列表',
  'tasks.detail.open': '展开详情',
  'tasks.detail.close': '收起详情',
  'tasks.detail.copyId': '复制任务 ID',
  'tasks.detail.copied': '已复制',
  'tasks.detail.events': '事件',
  'tasks.detail.eventsLoading': '正在载入事件…',
  'tasks.detail.eventsEmpty': '暂无事件记录。',
  'tasks.detail.eventsFailed': '事件载入失败',
  'tasks.field.id': '任务 ID',
  'tasks.field.type': '类型',
  'tasks.field.status': '状态',
  'tasks.field.phase': '阶段',
  'tasks.field.chapter': '章节/对象',
  'tasks.field.progress': '进度',
  'tasks.field.attempt': '尝试次数',
  'tasks.field.created': '创建时间',
  'tasks.field.started': '开始时间',
  'tasks.field.updated': '更新时间',
  'tasks.field.completed': '完成时间',
  'tasks.field.summary': '输入摘要',
  'tasks.field.resultRef': '结果引用',
  'tasks.field.failedStage': '失败阶段',
  'tasks.field.errorCode': '错误码',
  'tasks.field.recoverable': '可恢复',
  'tasks.field.yes': '是',
  'tasks.field.no': '否',
  'tasks.failure.cancelled': '用户取消',
  'tasks.failure.recoverable': '可恢复失败',
  'tasks.failure.provider': 'Provider 失败',
  'tasks.failure.input': '输入错误',
  'tasks.failure.system': '系统错误',
  'tasks.jump.benchmark': '查看横评结果',
  'tasks.jump.research': '查看研究报告',
  'tasks.jump.chapter': '定位章节',
  'tasks.jump.review': '定位评审章节',
  'tasks.jump.unavailable': '暂无可用跳转',
  'tasks.jump.chapterHint': '已在创作视图中选中该章节，切换到「创作」查看。',
  'tasks.jump.reviewHint': '已在创作视图中选中该章节，评审结果见其检查器。',
  'tasks.jump.chapterMissing': '未找到对应章节',
  'research.launch': '发起研究',
  'research.launch.placeholder': '研究问题（例如：明清漕运制度的运作与衰落）…',
  'research.launch.submit': '提交研究任务',
  'research.launch.submitting': '提交中…',
  'research.launch.submitted': '研究任务已提交，进度见「任务」tab。',
  'research.launch.failed': '提交失败',
  'research.launch.hint': '后台执行（DeepResearch），完成后报告出现在左侧列表。',
  'tasks.result.toggle': '展开或收起评审问题',
  'tasks.result.score': '评分',
  'tasks.result.issues': '问题',
  'search.preview.back': '返回结果',
  'search.preview.openCreation': '设为当前编辑章节',
  'search.preview.jumpReady': '已在“创作”中选中该章节。',
  'search.preview.identityMismatch': '服务端返回了另一个文档，已停止预览。',
  'search.preview.locatorCurrent': '命中位置与当前正文 revision 一致',
  'search.preview.locatorStale': '正文已变化，行号可能过期',
  'search.preview.locatorUnverified': '搜索结果未带 revision，行号新鲜度无法核验',
  'search.preview.revisionUnavailable': 'revision 不可用',
  'search.change.title': '搜索命中改稿计划',
  'search.change.serverOwned': '服务端预览与 revision 校验',
  'search.change.unavailable': '只有同时带稳定文档身份和当前 revision 的搜索命中才能生成安全改稿预览。',
  'search.change.currentLine': '当前命中行',
  'search.change.replacement': '替换为',
  'search.change.preview': '生成替换预览',
  'search.change.previewing': '正在生成预览…',
  'search.change.sourceRevision': '来源 revision',
  'search.change.resultRevision': '预计 revision',
  'search.change.reject': '放弃预览',
  'search.change.confirmApply': '确认应用此预览',
  'search.change.applying': '正在应用…',
  'search.change.refreshRequired': '文档或搜索结果已变化。本预览不可应用，请刷新搜索结果。',
  'search.change.invalidApply': '服务端未返回可验证的已提交结果，未将本次操作标记为完成。',
  'search.change.invalidReject': '服务端未确认预览已放弃。',
  'search.change.applied': '服务端已按预览提交修改。请刷新搜索结果查看新 revision。',
  'search.change.rejected': '已放弃此预览，正文未修改。',
  'search.change.refresh': '刷新搜索结果',
  'assets.empty': '暂无资产。让 agent 用 novel_asset_* 工具创建后刷新。',
  'assets.other': '其他',
  'assets.stages': '阶段',
  'assets.aliases': '别名',
  'assets.segment.characters': '角色',
  'assets.segment.world': '设定',
  'assets.segment.progression': '进阶体系',
  'assets.segment.references': '参考作品',
  'assets.segment.core': '作品核心',
  'assets.segment.empty': '该分类暂无条目。',
  'assets.references.empty': '暂无参考作品。让 agent 用 novel_reference_* 工具导入后刷新。',
  'assets.core.empty': '作品核心为空。让 agent 先完成创作承诺与故事基础。',
  'assets.detail.loading': '加载详情…',
  'assets.detail.relations': '关系',
  'assets.detail.index': '索引',
  'assets.list.detail_refs': '详情引用',
  'assets.list.taboos': '忌讳',
  'assets.edit.linesHint': '每行一条',
  'assets.relation.confirmed': '确认',
  'assets.relation.registered': '注记',
  'assets.relation.incoming': '被关联',
  'assets.searchPlaceholder': '搜索名称 / ID / 类型 / 别名 / 标签 / 摘要…',
  'assets.edit.open': '编辑',
  'assets.edit.name': '名称',
  'assets.edit.summary': '摘要',
  'assets.edit.tags': '标签',
  'assets.edit.listHint': '用逗号或顿号分隔',
  'assets.edit.save': '保存',
  'assets.edit.saving': '保存中…',
  'assets.edit.cancel': '取消',
  'assets.edit.conflict': '资产已在其他位置修改，请重新载入后再改。',
  'assets.edit.conflictRefresh': '刷新重试',
  'assets.edit.addRelation': '添加关系',
  'assets.edit.removeRelation': '移除',
  'assets.edit.relationTarget': '目标资产 ID',
  'assets.edit.relationNote': '关系说明',
  'assets.edit.derivedRelations': '派生关系（只读；请在对方资产上编辑）',
  'assets.edit.body': '正文',
  'assets.edit.liveLoading': '正在加载实时编辑器…',
  'assets.edit.optional': '选填',
  'assets.field.tier': '位阶',
  'assets.field.personality': '性格',
  'assets.field.goal': '目标',
  'assets.field.fear': '恐惧',
  'assets.field.appearance': '外貌',
  'assets.field.voice': '说话风格',
  'assets.field.current_state': '当前状态',
  'assets.field.organization': '所属组织',
  'assets.field.progression_system': '进阶体系',
  'assets.field.progression_stage': '进阶阶段',
  'assets.field.status': '状态',
  'assets.field.kind': '类型',
  'assets.field.type': '类型',
  'assets.field.subtype': '子类型',
  'assets.field.state_updated_at': '状态更新时间',
  'assets.field.role': '角色定位',
  'assets.edit.liveFailed': '实时编辑器加载失败，已回退到纯文本编辑。',
  'assets.selectHint': '选择左侧的条目查看或编辑。',
  'assets.create.open': '新建',
  'assets.create.submit': '创建',
  'assets.create.idHint': '字母或数字开头，可含 _ . -',
  'assets.create.tier': '位阶',
  'assets.create.type': '类型',
  'assets.create.progressionKind': '体系类型',
  'assets.create.stages': '阶段',
  'assets.create.stageId': '阶段 ID',
  'assets.create.stageName': '阶段名称',
  'assets.create.addStage': '添加阶段',
  'review.running': '评审进行中…',
  'review.passed': '通过',
  'review.failed': '未通过',
  'review.score': '得分',
  'review.issues': '问题',
  'review.suggestion': '修改建议',
  'review.quote': '原文引用',
  'review.dimension': '维度',
  'review.coverage': '覆盖率',
  'review.gate': '门禁',
  'review.delivery': '交付',
  'review.execution': '执行',
  'review.priority': '修订优先级',
  'review.severity.critical': '严重',
  'review.severity.warning': '警告',
  'review.severity.info': '提示',
  'review.severity.blocker': '阻塞',
  'review.severity.high': '高',
  'review.severity.medium': '中',
  'review.severity.low': '低',
  'review.priority.blocker': '阻塞',
  'review.priority.high': '高',
  'review.priority.medium': '中',
  'review.priority.low': '低',
  'review.status.pass': '通过',
  'review.status.blocked': '阻塞',
  'review.status.inconclusive': '信息不足',
  'review.status.revise': '需修订',
  'review.status.completed': '完成',
  'review.status.partial': '部分完成',
  'review.status.failed': '失败',
  'review.status.stale': '已过期',
  'review.status.unknown': '未知',
  'review.rawTitle': '原始输出',
  'tasks.empty': '暂无任务。agent 启动写章/评审等后台任务后会出现在这里。',
  'tasks.filter.all': '全部',
  'tasks.attempt': '尝试',
  'tasks.status.pending': '排队',
  'tasks.status.running': '运行中',
  'tasks.status.awaiting_confirmation': '待确认',
  'tasks.status.completed': '已完成',
  'tasks.status.failed': '失败',
  'tasks.status.cancelled': '已取消',
  'tasks.status.interrupted': '已中断',
  'tasks.phase.queued': '排队中',
  'tasks.phase.reading': '读取',
  'tasks.phase.preparing': '准备',
  'tasks.phase.model': '生成',
  'tasks.phase.validating': '校验',
  'tasks.phase.committing': '提交',
  'tasks.phase.complete': '完成',
  'tasks.type.chapter_write': '写章',
  'tasks.type.chapter_review': '评审',
  'tasks.type.continuous_write': '连写',
  'tasks.type.revision': '修订',
  'tasks.type.source_operation': '风格源',
  'tasks.type.reference_operation': '参考库',
  'tasks.type.manuscript_import': '导入',
  'tasks.type.project_restore': '作品恢复',
  'tasks.type.research': '研究',
  'tasks.type.model_benchmark': '模型横评',
  'graph.foreshadowing': '伏笔',
  'graph.relationships': '关系图',
  'graph.nodes': '节点',
  'graph.connections': '连接',
  'graph.relayout': '重新布局',
  'graph.weight': '权重',
  'graph.target': '回收',
  'graph.truncated': '结果已被服务端截断',
  'graph.validation.errors': '伏笔 DAG 校验错误',
  'graph.empty.foreshadowing': '暂无待回收伏笔。让 agent 用 novel_foreshadowing_* 埋设后刷新。',
  'graph.empty.relationships': '暂无关系数据。建立资产关系后刷新（或调整上方类型过滤）。',
  'graph.entityType': '实体类型',
  'graph.entityStatus': '状态',
  'graph.search': '搜索实体、描述或 ID',
  'graph.connectedOnly': '只看有连接节点',
  'graph.neighbors': '邻居节点',
  'graph.edgeType': '边类型',
  'graph.origin': '来源',
  'graph.source': '来源文件',
  'graph.confirmed': '已确认',
  'dag.quality': '质量',
  'dag.coverage': '覆盖率',
  'dag.gate': '硬门',
  'dag.delivery': '交付',
  'dag.current': '评审当前',
  'dag.stale': '评审已过期',
  'dag.toRevision': '问题转修订',
  'dag.toRevisionDone': '已创建修订任务。',
  'dag.toRevisionFailed': '创建修订任务失败',
  'graph.unresolved': '未解析实体',
  'graph.kind.character': '角色',
  'graph.kind.faction': '势力',
  'graph.kind.place': '地点',
  'graph.kind.concept': '概念',
  'graph.kind.other': '其他',
  'graph.truth': '事实账本',
  'graph.truth.currentState': '当前状态',
  'graph.truth.ledger': '资源账本',
  'graph.truth.relationships': '关系矩阵',
  'graph.workflows': '工作流',
  'graph.workflow.currentStage': '当前阶段',
  'graph.empty.truth': '暂无真相文件内容。章节推进后由 agent 更新 data/world/ 下的真相文件。',
  'graph.empty.truthDoc': '（空）',
  'graph.empty.workflows': '暂无活动章节工作流。',
  'graph.reviewDag': '评审 DAG',
  'graph.reviewFramework': '标准审稿框架',
  'graph.reviewDomains': '域',
  'graph.reviewChecks': '检查',
  'graph.reviewCriteria': '准则',
  'graph.deliveryDag': '交付 DAG',
  'graph.filter.all': '全部',
  'graph.filter.anomaly': '异常',
  'graph.filter.blocker': '阻断',
  'graph.expandChecks': '展开 37 项',
  'graph.collapseChecks': '折叠 37 项',
  'graph.empty.dag': '当前章节暂无已物化的 DAG。',
  'benchmark.title': '框架内模型测试台',
  'benchmark.task': '后台任务',
  'benchmark.mode': '执行模式',
  'benchmark.mode.framework': '真实写作框架',
  'benchmark.mode.creative': '裸写诊断',
  'benchmark.mode.unknown': '历史记录（执行模式未记录）',
  'benchmark.reviewer': '评审模型',
  'benchmark.chapter': '章节',
  'benchmark.repeats': '重复',
  'benchmark.words': '目标字数',
  'benchmark.concurrency': '并发',
  'benchmark.run': '开始测试',
  'benchmark.empty': '暂无模型测试记录。',
  'benchmark.select': '选择左侧测试查看交叉评审结果。',
  'benchmark.averageScore': '平均评分',
  'benchmark.output': '成品输出',
  'benchmark.candidate': '写作候选',
  'benchmark.candidates': '候选可靠性',
  'benchmark.evaluations': '独立盲评',
  'benchmark.writer': '写作模型',
  'benchmark.path': '执行路径',
  'benchmark.status': '状态',
  'models.title': '模型配置',
  'models.list': '模型档案列表',
  'models.editor': '模型档案编辑器',
  'models.new': '新增档案',
  'models.empty': '暂无模型档案。',
  'models.id': '档案 ID',
  'models.label': '档案名',
  'models.provider': '协议适配器',
  'models.protocol.openai': 'OpenAI 兼容',
  'models.protocol.anthropic': 'Anthropic',
  'models.modelId': '真实 Model ID',
  'models.baseUrl': 'Base URL',
  'models.apiFormat': '请求格式',
  'models.context': '上下文 Token',
  'models.output': '输出 Token',
  'models.credential': 'Chat',
  'models.embeddingProvider': 'Embedding 协议适配器',
  'models.embeddingModel': 'Embedding Model ID',
  'models.embeddingCredential': 'Embedding',
  'models.credentialHint': '留空保持已有 API Key',
  'models.remember': '本次保存时记住新输入的 API Key（仅写不可读）',
  'models.save': '保存档案',
  'models.chatTest': '聊天测试',
  'models.embeddingTest': 'Embedding 测试',
  'models.delete': '删除档案',
  'models.delete.confirm': '确认删除',
  'models.delete.blocked': '删除受阻',
  'models.delete.wouldFail': '删除后将失效的路由',
  'models.test.untested': '未测试',
  'models.test.ok': '上次测试通过',
  'models.test.failed': '上次测试失败',
  'models.dependencies': '依赖预览',
  'models.dependenciesHint': '以下任务路由当前依赖此档案；删除时必须选择回退档案。',
  'models.fallback': '删除后的回退档案',
  'models.chooseFallback': '选择回退档案',
  'models.routes': '操作路由',
  'models.routesSave': '保存路由',
  'models.saved': '模型档案已保存。',
  'models.deleted': '模型档案已删除。',
  'models.chatOk': '聊天连接测试成功。',
  'models.embeddingOk': 'Embedding 连接测试成功。',
  'models.configured': 'Chat 已配置',
  'models.missing': 'Chat 未配置',
  'models.routesSaved': '操作路由已保存。',
  'models.group.basic': '基本信息',
  'models.group.connection': 'API 连接',
  'models.group.generation': '生成参数',
  'models.group.embedding': 'Embedding 设置',
  'models.group.credentials': 'API Key',
  'models.group.routeUsage': '路由用途',
  'models.temperature': '温度',
  'models.timeout': '超时（秒）',
  'models.embeddingBaseUrl': 'Embedding Base URL',
  'models.validation.required': '必填项缺失：档案 ID、档案名、真实 Model ID。',
  'models.validation.positive': '数值字段必须为合法正数。',
  'models.validation.temperature': '温度必须在 0 到 2 之间。',
  'models.unsavedChanges': '当前档案有未保存的修改。',
  'models.unsavedDiscard': '放弃修改',
  'models.unsavedKeep': '继续编辑',
  'models.test.loading': '测试中…',
  'models.usedByRoutes': '使用此档案的路由',
  'models.noRoutes': '未被任何路由使用。',
  'models.delete.resultingRoutes': '删除后的路由结果',
  'models.embeddingEmpty': '暂无 Embedding 档案，请点击“新增档案”创建。',
  'models.embeddingConfigured': 'Embedding 已配置',
  'models.embeddingMissing': 'Embedding 未配置',
  'models.active': '当前使用',
  'models.inactive': '未使用',
  'models.route.goethe': 'Goethe 对话',
  'models.route.dante': 'Dante 对话',
  'models.route.chapter_write': '章节写作',
  'models.route.review': '章节评审',
  'models.route.source_extract': '素材抽取',
  'models.route.revision': '修订改写',
  'models.route.search': '项目搜索',
  'models.route.research': '研究',
  'models.routesImpact': '路由变更',
  'models.routesUnchanged': '路由无变化。',
  'models.routesUnassigned': '未指派档案',
  'models.embedConfigured': 'Embedding 已配置',
  'models.embedMissing': 'Embedding 未配置',
  'models.capability.chat': 'Chat',
  'models.capability.embedding': 'Embedding',
  'benchmark.actualWords': '实际字数',
  'benchmark.finishReason': '终止原因',
  'benchmark.error': '错误',
  'benchmark.coverage': '覆盖率',
  'benchmark.gate': '质量门槛',
  'benchmark.delivery': '交付建议',
  'benchmark.productionGate': '生产门槛',
  'benchmark.productionGateMissing': '未记录（非生产批准）',
  'benchmark.domains': '未完成评审域',
  'benchmark.latency': '耗时',
  'benchmark.usage': '用量',
  'benchmark.cost': '费用',
  'benchmark.inputTokens': '输入',
  'benchmark.outputTokens': '输出',
  'benchmark.reasoningTokens': '推理',
  'benchmark.totalTokens': '总计',
  'benchmark.actualCost': '实际费用',
  'benchmark.costCoverage': '费用已报告',
  'benchmark.effectiveRate': '综合有效价 / 1M',
  'benchmark.runs': '次运行',
  'benchmark.sameInputGroup': '同一实验条件',
  'benchmark.comparisonIncomplete': '历史产物缺少部分比较依据；仅在当前分组内查看，不与完整条件混算。',
  'benchmark.inputProvenance': '输入与来源',
  'benchmark.runPhases': '真实执行阶段',
  'benchmark.phase.created': '任务创建',
  'benchmark.phase.started': '开始执行',
  'benchmark.phase.completed': '产物完成',
  'benchmark.contextHash': '上下文哈希',
  'benchmark.comparisonKey': '比较组哈希',
  'benchmark.promptVersion': 'Prompt 版本',
  'benchmark.rubricVersion': '评审规则版本',
  'benchmark.blindReview': '独立盲评',
  'benchmark.contextStrategy': '上下文策略',
  'benchmark.manifestVersion': '上下文清单版本',
  'benchmark.tokenEstimator': 'Token 估算器',
  'benchmark.packetRevision': '上下文包 revision',
  'benchmark.sourceRevision': '来源 revision',
  'benchmark.estimatedTokens': '上下文估算 Token',
  'benchmark.characters': '涉及角色',
  'benchmark.contextSources': '上下文来源明细',
  'benchmark.sourcePresent': '存在',
  'benchmark.sourceMissing': '缺失',
  'benchmark.responseIdentity': '实际响应模型',
  'research.reports': '报告',
  'research.unavailable': '深度研究运行环境未就绪，请先在 Studio 中完成初始化。',
  'research.empty': '暂无研究报告。让 agent 发起一次深度研究后刷新。',
  'research.selectHint': '选择左侧的报告查看全文。',
  'research.report.loading': '正在加载报告…',
  'research.quality': '质量',
  'research.language': '语言',
  'research.filter.keyword': '搜索标题、问题、任务或模型…',
  'research.filter.status': '状态',
  'research.filter.sources': '来源',
  'research.filter.all': '全部',
  'research.status.succeeded': '已完成',
  'research.status.failed': '失败',
  'research.status.needsReview': '需要人工核查',
  'research.status.unknown': '历史状态未知',
  'research.sourcesAvailable': '来源索引可核查',
  'research.sourcesUnavailable': '来源索引未记录',
  'research.sourcesEmpty': '来源索引存在，但没有来源条目。',
  'research.sources': '来源',
  'research.sourceCheck': '来源核查',
  'research.source.cited': '正文已引用',
  'research.source.uncited': '正文未引用',
  'research.exportMarkdown': '导出 Markdown',
  'research.referenceOnly': '研究报告是参考材料，不会自动写入正典、大纲或正文。',
  'research.prompt': '研究问题',
  'research.taskId': '任务 ID',
  'research.episodeId': '研究运行 ID',
  'research.model': '模型身份',
  'research.searchProvider': '搜索提供方',
  'research.createdAt': '开始时间',
  'research.completedAt': '完成时间',
  'research.latency': '实际耗时',
  'research.wordCount': '报告字符数',
  'research.tokens': '实际 Token',
  'research.cost': '实际费用',
  'research.sourcesStatus': '来源状态',
  'research.metrics': '原始运行指标',
  'search.placeholder': '搜索项目资料…',
  'search.hint': '输入关键词搜索大纲、正文、角色、设定等项目资料。',
  'search.empty': '没有匹配的结果。',
  'search.indexed': '已索引',
  'search.timeout': '搜索请求超时。请确认 Studio 正在运行后重试。',
  'search.scope.all': '全部',
  'search.scope.outline': '大纲',
  'search.scope.core': '作品核心',
  'search.scope.characters': '角色',
  'search.scope.settings': '设定',
  'search.scope.continuity': '连续性',
  'search.scope.chapters': '正文',
  'search.scope.sources': '参考资料',
  'assets.references': '参考作品',
  'reference.intent.reference': '参考',
  'reference.intent.continuation': '续写',
  'reference.intent.canon': '正典',
  'reference.intent.migration': '迁移',
  'reference.structure.awaiting_confirmation': '结构待确认',
  'reference.structure.confirmed': '结构已确认',
  'reference.analysis.complete': '分析完成',
  'reference.analysis.pending': '分析未完成',
  'reference.chars': '字符',
  'reference.content.loading': '正在载入参考作品正文…',
  'reference.content.full': '全文',
}

/** English dictionary. */
export const en: Record<StudioPanelKey, string> = {
  'view.overview': 'Overview',
  'view.writing': 'Writing',
  'view.studio': 'Manuscript',
  'view.reviewWs': 'Review',
  'view.outline': 'Outline',
  'view.assets': 'Assets',
  'view.tasks': 'Tasks',
  'view.benchmark': 'Model test',
  'view.models': 'Models',
  'view.graph': 'Graph',
  'view.research': 'Research',
  'view.search': 'Search',
  'view.creation': 'Create',
  'view.library': 'Library',
  'view.operations': 'Tasks',
  'creation.chapters': 'Chapters',
  'creation.searchChapters': 'Search chapters',
  'creation.clearSearch': 'Clear chapter search',
  'creation.chaptersEmpty': 'No matching chapters.',
  'creation.previousChapter': 'Previous chapter',
  'creation.nextChapter': 'Next chapter',
  'creation.jumpChapter': 'Jump to chapter',
  'creation.chapterDuplicate': 'Duplicate entry; stable document identity required',
  'creation.order.loading': 'Checking canonical chapter order…',
  'creation.order.unavailable': 'Canonical chapter order is unavailable; showing the Workspace list.',
  'creation.order.refresh': 'Refresh order',
  'creation.order.invalid': 'The reading-order identity or revision is invalid. Refresh it.',
  'creation.order.missingCount': 'Planned chapters without manuscripts:',
  'creation.order.move': 'Move chapter',
  'creation.order.volume': 'Volume',
  'creation.order.position': 'Position',
  'creation.order.positionHelp': 'Position uses the target volume’s full outline, including planned missing chapters. Range',
  'creation.order.applyMove': 'Move chapter',
  'creation.order.blocked': 'Resolve ambiguous or missing chapter order before moving chapters.',
  'creation.order.moveComplete': 'Chapter moved and canonical reading order refreshed.',
  'creation.order.conflict': 'Reading order changed and was refreshed. Review it before moving again.',
  'creation.mode.edit': 'Back to editor',
  'creation.mode.reader': 'Continuous reading',
  'creation.writing.bookProgress': 'Book progress',
  'creation.writing.chapterTarget': 'Chapter target',
  'creation.writing.chapterProgress': 'Chapter progress',
  'creation.reader.title': 'Continuous reading',
  'creation.reader.readOnly': 'Reads the server chapter order and labels every chapter with its current revision.',
  'creation.reader.loading': 'Loading the manuscript…',
  'creation.reader.refresh': 'Refresh manuscript',
  'creation.reader.openEditor': 'Open editor',
  'creation.reader.path': 'Path',
  'creation.reader.documentId': 'Document identity',
  'creation.reader.revision': 'Manuscript revision',
  'creation.reader.revisionUnavailable': 'Not supplied by server',
  'creation.showChapters': 'Show chapter rail',
  'creation.hideChapters': 'Hide chapter rail',
  'creation.inspector': 'Inspector',
  'creation.showInspector': 'Show inspector',
  'creation.hideInspector': 'Hide inspector',
  'creation.editorLoading': 'Preparing editor…',
  'creation.documentLoading': 'Loading manuscript…',
  'creation.inspectorLoading': 'Preparing chapter context…',
  'creation.inspectorLoadingSlow': 'Context is still being prepared. You can keep editing.',
  'creation.empty': 'No chapters',
  'creation.acceptance.title': 'Manuscript acceptance',
  'creation.acceptance.loading': 'Checking',
  'creation.acceptance.current': 'Accepted',
  'creation.acceptance.pending': 'In progress and recoverable',
  'creation.acceptance.drift': 'External manuscript change detected',
  'creation.acceptance.baselinePending': 'Acceptance baseline required',
  'creation.acceptance.needsReview': 'Author review required',
  'creation.acceptance.failed': 'Failed and recoverable',
  'creation.acceptance.unknown': 'Unknown status',
  'creation.acceptance.unavailable': 'Acceptance status is unavailable',
  'creation.acceptance.currentRevision': 'Current manuscript revision',
  'creation.acceptance.acceptedRevision': 'Accepted revision',
  'creation.acceptance.operation': 'Acceptance operation',
  'creation.acceptance.stale': 'Stale derived results',
  'creation.acceptance.refresh': 'Refresh acceptance status',
  'creation.acceptance.baseline': 'Create baseline from current text',
  'creation.acceptance.external': 'Accept external change',
  'creation.acceptance.resume': 'Resume incomplete operation',
  'creation.acceptance.acknowledge': 'Acknowledge review',
  'creation.acceptance.confirmBaseline': 'Create an acceptance baseline from the current manuscript? This starts analysis and refreshes affected derived results.',
  'creation.acceptance.confirmExternal': 'Accept the external manuscript change on disk? This starts analysis and refreshes affected derived results.',
  'creation.acceptance.confirmAcknowledge': 'Confirm that you reviewed this manuscript acceptance and its effects?',
  'creation.context': 'Context',
  'creation.review': 'Review',
  'creation.revisions': 'Revisions',
  'creation.activity': 'Activity',
  'creation.activity.loading': 'Loading chapter activity…',
  'creation.activity.unavailable': 'Chapter activity is unavailable.',
  'creation.activity.invalid': 'The chapter work brief identity or version does not match. Refresh it.',
  'creation.activity.target': 'Chapter writing target',
  'creation.activity.remaining': 'remaining',
  'creation.activity.identity': 'Current identity and revisions',
  'creation.activity.recent': 'Recent edits',
  'creation.activity.empty': 'This chapter has no edit activity yet.',
  'creation.contextEmpty': 'No context is available for this chapter.',
  'creation.context.packet': 'Actual writing packet revision',
  'creation.context.current': 'Current',
  'creation.context.stale': 'Stale',
  'creation.context.previousStale': 'Sources changed; the previous context packet is stale:',
  'creation.context.requestBudget': 'OpenWrite writing request budget',
  'creation.context.sessionBudget': 'dsh session budget',
  'creation.context.outputReserve': 'Output reserve',
  'creation.context.actualUsage': 'Actual usage',
  'creation.context.reported': 'Reported',
  'creation.context.unavailable': 'Unavailable',
  'creation.context.sessionSeparate': 'Measured separately by the dsh session runtime and never added to the writing request.',
  'creation.context.retrieval': 'Semantic retrieval',
  'creation.context.sources': 'Actual sources and selection results',
  'creation.context.protected': 'Protected',
  'creation.context.noSnippet': 'No preview is available',
  'creation.context.reason': 'Selection reason',
  'creation.context.missing': 'Missing',
  'creation.context.excluded': 'Excluded',
  'creation.context.fullText': 'View final rendered text',
  'creation.reviewEmpty': 'This chapter has not been reviewed.',
  'creation.review.stale': 'This review targets an older manuscript. Run review again before creating a revision.',
  'creation.review.casUnavailable': 'Verified review and manuscript revisions are not available yet. Refresh before generating a revision.',
  'creation.review.refreshRequired': 'The review or manuscript changed. Refresh the chapter brief and select issues again.',
  'creation.review.closure': 'Latest re-review outcome',
  'creation.review.closureProposal': 'Revision proposal',
  'creation.review.closureRevision': 'Re-review revision',
  'creation.review.outcome.resolved': 'Resolved',
  'creation.review.outcome.retained': 'Retained',
  'creation.review.outcome.regressed': 'Regressed',
  'creation.review.selectionSummary': 'Select issues to fix; unselected issues stay retained',
  'creation.review.instruction': 'Additional revision instruction (optional)',
  'creation.review.createRevision': 'Generate revision for selected issues',
  'creation.review.rereview': 'Run review again',
  'creation.review.revisionStarted': 'Revision task started. Inspect its diff in Revisions when it completes.',
  'creation.review.rereviewStarted': 'Review task started. Review state will refresh when it completes.',
  'creation.revisionsEmpty': 'No revision proposals for this chapter.',
  'creation.history.title': 'Manuscript history',
  'creation.history.snapshot': 'Named snapshot',
  'creation.history.snapshotName': 'Name this manuscript snapshot:',
  'creation.history.snapshotCreated': 'Manuscript snapshot created.',
  'creation.history.empty': 'This chapter has no recoverable history yet.',
  'creation.history.units': 'units',
  'creation.history.loading': 'Loading…',
  'creation.history.compare': 'Compare',
  'creation.history.restorePreview': 'Restore preview: current → saved version',
  'creation.history.closePreview': 'Close restore preview',
  'creation.history.noChanges': 'The current manuscript matches this version.',
  'creation.history.restore': 'Restore this version',
  'creation.history.restoreConfirm': 'Restore this version? The current manuscript will be saved first.',
  'creation.history.restored': 'Version restored. The previous manuscript remains recoverable.',
  'creation.history.previewFailed': 'The version comparison could not be read.',
  'creation.history.reason.autosave': 'Autosave batch',
  'creation.history.reason.manual': 'Manual save',
  'creation.history.reason.aiRevision': 'Before AI revision',
  'creation.history.reason.fullRewrite': 'Before full rewrite',
  'creation.history.reason.restore': 'Before restore',
  'creation.proposals.title': 'Revision proposals',
  'creation.proposals.noRationale': 'No rationale was provided.',
  'creation.proposals.range': 'Source range:',
  'creation.proposals.evidence': 'Review evidence:',
  'creation.proposals.reviewRevision': 'Review revision:',
  'creation.proposals.sourceRevision': 'Proposal source revision:',
  'creation.proposals.noHunks': 'No linked diff hunks',
  'creation.proposals.originalCandidate': 'View source and candidate',
  'creation.proposals.reject': 'Reject',
  'creation.proposals.regenerate': 'Regenerate',
  'creation.proposals.applySelected': 'Apply selected changes',
  'creation.proposals.appliedNeedsReview': 'Selected changes were applied. Run review again to verify issue closure.',
  'creation.issues': 'issues',
  'creation.changedElsewhere': 'The manuscript changed elsewhere; your draft was preserved.',
  'creation.conflict': 'Save conflict: the server manuscript changed and your draft is preserved.',
  'creation.reload': 'Load server version',
  'creation.overwrite': 'Overwrite',
  'creation.discardConfirm': 'This draft is not saved. Discard it and load other content?',
  'creation.overwriteConfirm': 'Overwrite the newer server version with this draft? A checkpoint will be created.',
  'creation.closePanel': 'Close panel',
  'creation.draft.available': 'An unsaved local recovery draft is available.',
  'creation.draft.conflict': 'This recovery draft is based on older server text. Resolve the conflict after restoring it.',
  'creation.draft.updated': 'Saved locally:',
  'creation.draft.preview': 'Preview recovery draft',
  'creation.draft.restore': 'Restore to editor',
  'creation.draft.dismiss': 'Ignore and delete',
  'creation.draft.unavailable': 'Local recovery protection is unavailable. The editor keeps this text until the page closes.',
  'creation.status.idle': 'Not open',
  'creation.status.loading': 'Loading',
  'creation.status.saved': 'Saved',
  'creation.status.dirty': 'Unsaved',
  'creation.status.saving': 'Saving',
  'creation.status.conflict': 'Conflict',
  'creation.status.offline': 'Offline',
  'operations.transfer': 'Import & export',
  'operations.transferHint': 'Export, sync, or import chapters within the current project.',
  'operations.project': 'Current workspace',
  'operations.create.new': '+ New work',
  'operations.create.id': 'Novel ID',
  'operations.create.title': 'Title',
  'operations.create.titleHint': 'Title',
  'operations.create.submit': 'Create work',
  'operations.create.done': '"{title}" created',
  'operations.create.failed': 'Create failed',
  'operations.create.pickHint': 'You will pick the project directory in the system dialog',
  'operations.init.hint': 'This Workspace is not initialized as a novel project yet. Enter a novel ID and title to initialize it.',
  'operations.init.submit': 'Initialize project',
  'workspace.unbound': 'No workspace selected',
  'workspace.notInitialized': 'Not initialized',
  'workspace.bind.hint': 'This session is not attached to a workspace yet. Pick a directory as the workspace, then initialize the novel project.',
  'workspace.bind.pick': 'Pick a directory as workspace',
  'workspace.bind.failed': 'Failed to attach workspace',
  'operations.cancel': 'Cancel',
  'tool.family.status': 'Project status',
  'tool.family.context': 'Chapter context',
  'tool.family.manuscript': 'Manuscript',
  'tool.family.revision': 'Revision',
  'tool.family.task': 'Task',
  'tool.family.search': 'Search',
  'tool.family.asset': 'Library',
  'tool.family.outline': 'Outline',
  'tool.running': 'Running',
  'tool.failed': 'Failed',
  'tool.succeeded': 'Completed',
  'tool.openChapter': 'Open chapter',
  'turn.changed': 'Updated this turn',
  'turn.partial': 'Partially updated this turn',
  'turn.failed': 'Write failed this turn',
  'turn.refreshFailed': 'Write succeeded; refresh failed',
  'turn.history': 'History version',
  'turn.proposed': 'Changes proposed this turn',
  'turn.rejected': 'Changes rejected this turn',
  'turn.entityChanges': 'entity changes',
  'turn.before': 'Before',
  'turn.after': 'After',
  'turn.missing': 'Missing',
  'turn.truncated': 'excerpt; full value is longer',
  'turn.sourceRevision': 'Source revision',
  'turn.resultRevision': 'Result revision',
  'turn.committed': 'Committed',
  'turn.trace': 'Trace',
  'turn.modelCalls': 'model calls',
  'turn.days': 'days retained',
  'turn.accept': 'Accept and apply',
  'turn.reject': 'Reject',
  'turn.retry': 'Retry on current version',
  'turn.undo': 'Safe undo',
  'turn.applied': 'The exact preview was committed.',
  'turn.retried': 'A new preview was built from the current source.',
  'turn.undone': 'The change was safely undone.',
  resolving: 'Reading Studio configuration…',
  loading: 'Loading…',
  unreachable: 'OpenWrite Studio is unreachable. Make sure Studio is running (default http://127.0.0.1:4567).',
  retry: 'Retry',
  refresh: 'Refresh',
  openExternal: 'Open in new tab',
  'outline.empty': 'The outline is empty. Create src/outline.md in Studio, then refresh.',
  'outline.drafted': 'Drafted',
  'outline.planned': 'Planned',
  'outline.draftedCount': 'Drafted chapters',
  'outline.addChild': 'Add child',
  'outline.addAfter': 'Add sibling',
  'outline.addVolume': 'Add volume',
  'outline.expandAll': 'Expand all',
  'outline.collapseAll': 'Collapse all',
  'outline.del': 'Delete',
  'outline.confirmDelete': 'Delete this node and all of its children:',
  'outline.newTitlePlaceholder': 'New title (chapters need a number, e.g. "Ch.12: Turning Point")',
  'outline.opConflict': 'The outline changed elsewhere. Structure refreshed — please retry.',
  'outline.opFailed': 'Operation failed',
  'outline.summaryEmpty': '(empty)',
  'tools.title': 'Toolbox',
  'tools.export': 'Export',
  'tools.export.done': 'Exported {name}',
  'tools.export.failed': 'Export failed',
  'tools.export.purpose': 'Export purpose',
  'tools.export.purpose.backup': 'Full backup',
  'tools.export.purpose.delivery': 'Delivery copy',
  'tools.export.format': 'Format',
  'tools.export.preflight': 'Export preflight',
  'tools.export.loading': 'Checking the current manuscript…',
  'tools.export.unavailable': 'A valid export preflight is unavailable',
  'tools.export.refresh': 'Refresh preflight',
  'tools.export.revision': 'Preflight revision',
  'tools.export.ready': 'Ready to export',
  'tools.export.blocked': 'Blocked',
  'tools.export.download': 'Export inspected version',
  'tools.export.order': 'Actual chapter order',
  'tools.export.orderEmpty': 'No chapters to export',
  'tools.export.units': 'writing units',
  'tools.export.structure': 'Structure checks',
  'tools.export.structure.duplicates': 'Duplicate numbers',
  'tools.export.structure.missing': 'Missing chapters',
  'tools.export.structure.empty': 'Empty chapters',
  'tools.export.structure.unreadable': 'Unreadable chapters',
  'tools.export.clear': 'No issues found',
  'tools.export.writingUnits': 'Length and targets',
  'tools.export.total': 'Current total',
  'tools.export.bookTarget': 'Book target',
  'tools.export.chapterTarget': 'Chapter target',
  'tools.export.completion': 'Completion',
  'tools.export.metadata': 'Book metadata',
  'tools.export.metadata.title': 'Title',
  'tools.export.metadata.author': 'Author',
  'tools.export.metadata.language': 'Language',
  'tools.export.reviews': 'Review freshness',
  'tools.export.reviews.missing': 'Missing reviews',
  'tools.export.reviews.current': 'Current',
  'tools.export.reviews.stale': 'Stale',
  'tools.export.reviews.approved': 'Approved',
  'tools.export.reviews.notApproved': 'Not approved',
  'tools.export.acceptance': 'Manuscript acceptance',
      'tools.export.acceptance.blocking': 'Blocking chapters',
      'tools.export.acceptance.blockingState': 'Acceptance blocking',
      'tools.export.acceptance.needsReview': 'Domains needing review',
  'tools.export.status': 'Status',
  'tools.export.blockers': 'Blockers',
  'tools.export.warnings': 'Warnings',
  'tools.export.none': 'None',
  'tools.export.stale': 'The manuscript changed. The preflight was refreshed; review it and try again.',
  'tools.sync': 'Sync project',
  'tools.sync.done': 'Project synced',
  'tools.sync.failed': 'Sync failed',
  'tools.import': 'Import chapters',
  'tools.import.empty': 'Import content is empty',
  'tools.import.failed': 'Import failed',
  'tools.import.done': 'Imported {count} chapters (starting ch_{start}); refresh Outline/Manuscript to see them',
  'tools.import.choose': 'Choose file',
  'tools.import.noFile': 'No file chosen',
  'tools.import.start': 'Start number',
  'tools.import.startAuto': 'auto',
  'tools.import.preview': 'Preview',
  'tools.import.plan': 'Will import {count} chapters / {units} writing units, starting ch_{start} ({arc}).',
  'tools.import.conflicts': 'Conflicts: {ids} already exist.',
  'tools.import.force': 'Force overwrite import',
  'tools.import.confirm': 'Confirm import',
  'tools.import.workspace.title': 'My manuscript import workspace',
  'tools.import.workspace.ownHint': 'Import your own novel manuscript with saved chapter boundaries and resumable stages. This does not add content to the reference library.',
  'tools.import.workspace.operations': 'Resumable imports',
  'tools.import.workspace.empty': 'No manuscript imports yet',
  'tools.import.workspace.new': 'Prepare another manuscript',
  'tools.import.workspace.file': 'Your manuscript file',
  'tools.import.workspace.arc': 'Target arc',
  'tools.import.workspace.prepare': 'Snapshot and split',
  'tools.import.workspace.prepared': 'Manuscript snapshotted; review its chapter structure',
  'tools.import.workspace.select': 'Select an import operation to inspect it',
  'tools.import.workspace.chapters': 'chapters',
  'tools.import.workspace.structure': 'Chapter boundaries and titles',
  'tools.import.workspace.chapterId': 'Chapter ID',
  'tools.import.workspace.chapterTitle': 'Chapter title',
  'tools.import.workspace.chapterContent': 'Chapter content',
  'tools.import.workspace.moveUp': 'Move chapter up',
  'tools.import.workspace.moveDown': 'Move chapter down',
  'tools.import.workspace.remove': 'Remove chapter',
  'tools.import.workspace.addChapter': 'Add chapter boundary',
  'tools.import.workspace.newChapter': 'New chapter',
  'tools.import.workspace.saveStructure': 'Save boundary changes',
  'tools.import.workspace.structureSaved': 'Chapter structure saved; review it again before confirming',
  'tools.import.workspace.confirmStructure': 'Confirm publish structure',
  'tools.import.workspace.confirmPrompt': 'Publish this manuscript with the displayed chapter order, boundaries, and titles?',
  'tools.import.workspace.confirmed': 'Chapter structure confirmed; the import can run',
  'tools.import.workspace.run': 'Run import',
  'tools.import.workspace.resume': 'Resume import',
  'tools.import.workspace.taskStarted': 'Import task started: {id}',
  'tools.import.workspace.discard': 'Discard import',
  'tools.import.workspace.discardPrompt': 'Discard this unpublished manuscript import operation?',
  'tools.import.workspace.discarded': 'Manuscript import discarded',
  'tools.import.workspace.recoverable': 'Resumable',
  'tools.import.workspace.notRecoverable': 'Not resumable',
  'tools.import.stage.snapshot': 'Source snapshot',
  'tools.import.stage.split': 'Manuscript split',
  'tools.import.stage.structure_confirmed': 'Structure confirmed',
  'tools.import.stage.published': 'Manuscript published',
  'tools.import.stage.acceptance': 'Acceptance recorded',
  'tools.import.stage.reconcile': 'Derived data reconciled',
  'tools.import.stage.synthesis': 'Fact synthesis',
  'tools.import.stage.complete': 'Complete',
  'tools.archive.title': 'Complete project archives',
  'tools.archive.hint': 'Archive manuscript, structure, revisions, reviews, and task records. Secrets and caches stay outside the archive.',
  'tools.archive.failed': 'Project archive operation failed',
  'tools.archive.preflight': 'Archive preflight revision',
  'tools.archive.create': 'Create from current preflight',
  'tools.archive.created': 'Project archive created: {id}',
  'tools.archive.list': 'Existing archives',
  'tools.archive.empty': 'No project archives yet',
  'tools.archive.download': 'Download archive',
  'tools.archive.downloaded': 'Downloaded {name}',
  'tools.archive.files': 'Files',
  'tools.archive.size': 'Bytes',
  'tools.archive.categories': 'Content categories',
  'tools.archive.includes': 'Included content',
  'tools.archive.excludes': 'Excluded content',
  'tools.archive.missing': 'Missing content',
  'tools.archive.references': 'Reference plan',
  'tools.archive.referencePlan': 'Recognized {known} · preserved {preserved} · warnings {warnings}',
  'tools.archive.restore': 'Restore to a new workspace',
  'tools.archive.targetRoot': 'Absolute target path',
  'tools.archive.pickTarget': 'Pick target directory',
  'tools.archive.targetNovelId': 'Restored novel ID (optional)',
  'tools.archive.referencePolicy': 'Reference policy',
  'tools.archive.preserveRelative': 'Preserve relative references',
  'tools.archive.rewriteNovelId': 'Rewrite references with novel ID',
  'tools.archive.previewRestore': 'Preview restore',
  'tools.archive.restoreReady': 'Ready to restore',
  'tools.archive.restoreBlocked': 'Restore is blocked',
  'tools.archive.conflicts': 'Conflicts',
  'tools.archive.pathRewrites': 'Path rewrites',
  'tools.archive.rewrittenFiles': 'Rewritten files',
  'tools.archive.rewrittenReferences': 'Rewritten references',
  'tools.archive.preservedReferences': 'Preserved references',
  'tools.archive.referenceWarnings': 'Reference warnings',
  'tools.archive.referenceConflicts': 'Reference conflicts',
  'tools.archive.tasksArchived': '{count} old task files will be moved to the task archive',
  'tools.archive.autoResume': 'Old tasks will resume automatically',
  'tools.archive.noAutoResume': 'Old tasks will not resume automatically',
  'tools.archive.confirmRestore': 'Confirm restore',
  'tools.archive.restoreConfirm': 'Restore this archive to the previewed new directory? Old tasks are archived and will not resume automatically.',
  'tools.archive.restoreStarted': 'Restore task started: {id}',
  'tasks.cancel': 'Cancel',
  'tasks.cancel.title': 'Cancel this task',
  'tasks.cancel.confirm': 'Cancel this queued/running task?',
  'tasks.cancel.done': 'Task cancelled',
  'tasks.cancel.failed': 'Cancel failed',
  'tasks.retry': 'Retry',
  'tasks.retry.title': 'Retry this task',
  'tasks.retry.notRecoverable': 'This failure is not recoverable',
  'tasks.retry.done': 'Task re-queued',
  'tasks.retry.failed': 'Retry submission failed',
  'tasks.summary.total': 'Total',
  'tasks.summary.updated': 'Updated {time}',
  'tasks.filter.type': 'Type',
  'tasks.filter.typeAll': 'All types',
  'tasks.filter.chapter': 'Chapter / object',
  'tasks.filter.keyword': 'Search summary, ID, chapter',
  'tasks.sort.newest': 'Newest first',
  'tasks.sort.oldest': 'Oldest first',
  'tasks.sort.toggle': 'Toggle time sort',
  'tasks.progress.unknown': 'Progress unknown',
  'tasks.phase.unknown': 'Phase unknown',
  'tasks.confirm': 'Confirm',
  'tasks.confirm.title': 'Confirm this task',
  'tasks.confirm.done': 'Task confirmed',
  'tasks.confirm.failed': 'Confirm submission failed',
  'tasks.cancel.armYes': 'Confirm cancel',
  'tasks.cancel.armNo': 'Keep',
  'tasks.list': 'Task list',
  'tasks.detail.open': 'Show details',
  'tasks.detail.close': 'Hide details',
  'tasks.detail.copyId': 'Copy task ID',
  'tasks.detail.copied': 'Copied',
  'tasks.detail.events': 'Events',
  'tasks.detail.eventsLoading': 'Loading events…',
  'tasks.detail.eventsEmpty': 'No events recorded.',
  'tasks.detail.eventsFailed': 'Failed to load events',
  'tasks.field.id': 'Task ID',
  'tasks.field.type': 'Type',
  'tasks.field.status': 'Status',
  'tasks.field.phase': 'Phase',
  'tasks.field.chapter': 'Chapter/object',
  'tasks.field.progress': 'Progress',
  'tasks.field.attempt': 'Attempts',
  'tasks.field.created': 'Created',
  'tasks.field.started': 'Started',
  'tasks.field.updated': 'Updated',
  'tasks.field.completed': 'Completed',
  'tasks.field.summary': 'Input summary',
  'tasks.field.resultRef': 'Result reference',
  'tasks.field.failedStage': 'Failed stage',
  'tasks.field.errorCode': 'Error code',
  'tasks.field.recoverable': 'Recoverable',
  'tasks.field.yes': 'Yes',
  'tasks.field.no': 'No',
  'tasks.failure.cancelled': 'Cancelled by user',
  'tasks.failure.recoverable': 'Recoverable failure',
  'tasks.failure.provider': 'Provider failure',
  'tasks.failure.input': 'Input error',
  'tasks.failure.system': 'System error',
  'tasks.jump.benchmark': 'Open benchmark run',
  'tasks.jump.research': 'Open research report',
  'tasks.jump.chapter': 'Locate chapter',
  'tasks.jump.review': 'Locate reviewed chapter',
  'tasks.jump.unavailable': 'No jump available',
  'tasks.jump.chapterHint': 'Chapter selected — switch to the Create view to see it.',
  'tasks.jump.reviewHint': 'Chapter selected — its review lives in the Create view inspector.',
  'tasks.jump.chapterMissing': 'Chapter not found',
  'research.launch': 'Launch research',
  'research.launch.placeholder': 'Research question (e.g. the rise and fall of Ming-Qing grain transport)…',
  'research.launch.submit': 'Submit research task',
  'research.launch.submitting': 'Submitting…',
  'research.launch.submitted': 'Research task submitted — track it in the Tasks tab.',
  'research.launch.failed': 'Submit failed',
  'research.launch.hint': 'Runs in the background (DeepResearch); the report lands in the list on the left when done.',
  'tasks.result.toggle': 'Expand or collapse review issues',
  'tasks.result.score': 'Score',
  'tasks.result.issues': 'Issues',
  'search.preview.back': 'Back to results',
  'search.preview.openCreation': 'Select for editing',
  'search.preview.jumpReady': 'This chapter is selected in the Create view.',
  'search.preview.identityMismatch': 'The server returned another document, so preview was stopped.',
  'search.preview.locatorCurrent': 'The hit locator matches the current manuscript revision',
  'search.preview.locatorStale': 'The manuscript changed; the line locator may be stale',
  'search.preview.locatorUnverified': 'The search result has no revision, so locator freshness cannot be verified',
  'search.preview.revisionUnavailable': 'Revision unavailable',
  'search.change.title': 'Edit this search hit',
  'search.change.serverOwned': 'Server preview with revision checks',
  'search.change.unavailable': 'A safe edit preview requires a search hit with both stable document identity and the current revision.',
  'search.change.currentLine': 'Current matched line',
  'search.change.replacement': 'Replace with',
  'search.change.preview': 'Preview replacement',
  'search.change.previewing': 'Preparing preview…',
  'search.change.sourceRevision': 'Source revision',
  'search.change.resultRevision': 'Predicted revision',
  'search.change.reject': 'Discard preview',
  'search.change.confirmApply': 'Confirm and apply preview',
  'search.change.applying': 'Applying…',
  'search.change.refreshRequired': 'The document or search result changed. This preview cannot be applied; refresh the search result.',
  'search.change.invalidApply': 'The server did not return a verifiable committed result, so this operation was not marked complete.',
  'search.change.invalidReject': 'The server did not confirm that the preview was discarded.',
  'search.change.applied': 'The server committed the preview. Refresh search results to see the new revision.',
  'search.change.rejected': 'Preview discarded; the document was not changed.',
  'search.change.refresh': 'Refresh search results',
  'assets.empty': 'No assets yet. Ask the agent to create some with the novel_asset_* tools, then refresh.',
  'assets.other': 'Other',
  'assets.stages': 'stages',
  'assets.aliases': 'Aliases',
  'assets.segment.characters': 'Characters',
  'assets.segment.world': 'World',
  'assets.segment.progression': 'Progression',
  'assets.segment.references': 'References',
  'assets.segment.core': 'Story Core',
  'assets.segment.empty': 'Nothing in this section yet.',
  'assets.references.empty': 'No reference works yet. Ask the agent to import some with the novel_reference_* tools, then refresh.',
  'assets.core.empty': 'The story core is empty. Ask the agent to draft the author intent and story foundation first.',
  'assets.detail.loading': 'Loading details…',
  'assets.detail.relations': 'Relations',
  'assets.detail.index': 'Index',
  'assets.list.detail_refs': 'Detail refs',
  'assets.list.taboos': 'Taboos',
  'assets.edit.linesHint': 'One entry per line',
  'assets.relation.confirmed': 'Confirmed',
  'assets.relation.registered': 'Annotation',
  'assets.relation.incoming': 'Incoming',
  'assets.searchPlaceholder': 'Search name / id / type / aliases / tags / summary…',
  'assets.edit.open': 'Edit',
  'assets.edit.name': 'Name',
  'assets.edit.summary': 'Summary',
  'assets.edit.tags': 'Tags',
  'assets.edit.listHint': 'Separate with commas',
  'assets.edit.save': 'Save',
  'assets.edit.saving': 'Saving…',
  'assets.edit.cancel': 'Cancel',
  'assets.edit.conflict': 'This asset changed elsewhere. Reload it before editing again.',
  'assets.edit.conflictRefresh': 'Reload & retry',
  'assets.edit.addRelation': 'Add relation',
  'assets.edit.removeRelation': 'Remove',
  'assets.edit.relationTarget': 'Target asset id',
  'assets.edit.relationNote': 'Relation note',
  'assets.edit.derivedRelations': 'Derived relations (read-only; edit them on the owning asset)',
  'assets.edit.body': 'Body',
  'assets.edit.liveLoading': 'Loading the live editor…',
  'assets.edit.optional': 'Optional',
  'assets.field.tier': 'Tier',
  'assets.field.personality': 'Personality',
  'assets.field.goal': 'Goal',
  'assets.field.fear': 'Fear',
  'assets.field.appearance': 'Appearance',
  'assets.field.voice': 'Voice',
  'assets.field.current_state': 'Current state',
  'assets.field.organization': 'Organization',
  'assets.field.progression_system': 'Progression system',
  'assets.field.progression_stage': 'Progression stage',
  'assets.field.status': 'Status',
  'assets.field.kind': 'Kind',
  'assets.field.type': 'Type',
  'assets.field.subtype': 'Subtype',
  'assets.field.state_updated_at': 'State updated at',
  'assets.field.role': 'Role',
  'assets.edit.liveFailed': 'The live editor failed to load; fell back to plain text editing.',
  'assets.selectHint': 'Select an entry on the left to view or edit.',
  'assets.create.open': 'New',
  'assets.create.submit': 'Create',
  'assets.create.idHint': 'Starts with a letter or digit; may contain _ . -',
  'assets.create.tier': 'Tier',
  'assets.create.type': 'Type',
  'assets.create.progressionKind': 'System kind',
  'assets.create.stages': 'Stages',
  'assets.create.stageId': 'Stage id',
  'assets.create.stageName': 'Stage name',
  'assets.create.addStage': 'Add stage',
  'review.running': 'Reviewing…',
  'review.passed': 'Passed',
  'review.failed': 'Needs revision',
  'review.score': 'Score',
  'review.issues': 'Issues',
  'review.suggestion': 'Suggestion',
  'review.quote': 'Quote',
  'review.dimension': 'Dimension',
  'review.coverage': 'Coverage',
  'review.gate': 'Gate',
  'review.delivery': 'Delivery',
  'review.execution': 'Execution',
  'review.priority': 'Revision priority',
  'review.severity.critical': 'Critical',
  'review.severity.warning': 'Warning',
  'review.severity.info': 'Info',
  'review.severity.blocker': 'Blocker',
  'review.severity.high': 'High',
  'review.severity.medium': 'Medium',
  'review.severity.low': 'Low',
  'review.priority.blocker': 'Blocker',
  'review.priority.high': 'High',
  'review.priority.medium': 'Medium',
  'review.priority.low': 'Low',
  'review.status.pass': 'Pass',
  'review.status.blocked': 'Blocked',
  'review.status.inconclusive': 'Inconclusive',
  'review.status.revise': 'Revise',
  'review.status.completed': 'Completed',
  'review.status.partial': 'Partial',
  'review.status.failed': 'Failed',
  'review.status.stale': 'Stale',
  'review.status.unknown': 'Unknown',
  'review.rawTitle': 'Raw output',
  'tasks.empty': 'No tasks yet. Background jobs the agent starts (chapter writing, review, …) will show up here.',
  'tasks.filter.all': 'All',
  'tasks.attempt': 'Attempt',
  'tasks.status.pending': 'Queued',
  'tasks.status.running': 'Running',
  'tasks.status.awaiting_confirmation': 'Awaiting confirmation',
  'tasks.status.completed': 'Completed',
  'tasks.status.failed': 'Failed',
  'tasks.status.cancelled': 'Cancelled',
  'tasks.status.interrupted': 'Interrupted',
  'tasks.phase.queued': 'Queued',
  'tasks.phase.reading': 'Reading',
  'tasks.phase.preparing': 'Preparing',
  'tasks.phase.model': 'Generating',
  'tasks.phase.validating': 'Validating',
  'tasks.phase.committing': 'Committing',
  'tasks.phase.complete': 'Done',
  'tasks.type.chapter_write': 'Write',
  'tasks.type.chapter_review': 'Review',
  'tasks.type.continuous_write': 'Continuous write',
  'tasks.type.revision': 'Revision',
  'tasks.type.source_operation': 'Style source',
  'tasks.type.reference_operation': 'Reference',
  'tasks.type.manuscript_import': 'Import',
  'tasks.type.project_restore': 'Project restore',
  'tasks.type.research': 'Research',
  'tasks.type.model_benchmark': 'Model benchmark',
  'graph.foreshadowing': 'Foreshadowing',
  'graph.relationships': 'Relationships',
  'graph.nodes': 'nodes',
  'graph.connections': 'connections',
  'graph.relayout': 'Re-layout',
  'graph.weight': 'Weight',
  'graph.target': 'Target',
  'graph.truncated': 'Results truncated server-side',
  'graph.validation.errors': 'Foreshadowing DAG validation errors',
  'graph.empty.foreshadowing': 'No pending foreshadowing. Ask the agent to plant some with novel_foreshadowing_*, then refresh.',
  'graph.empty.relationships': 'No relationship data. Create asset relations and refresh (or adjust the kind filters above).',
  'graph.entityType': 'Entity type',
  'graph.entityStatus': 'Status',
  'graph.search': 'Search entities, descriptions or IDs',
  'graph.connectedOnly': 'Connected nodes only',
  'graph.neighbors': 'Neighbors',
  'graph.edgeType': 'Edge type',
  'graph.origin': 'Origin',
  'graph.source': 'Source file',
  'graph.confirmed': 'Confirmed',
  'dag.quality': 'Quality',
  'dag.coverage': 'Coverage',
  'dag.gate': 'Gate',
  'dag.delivery': 'Delivery',
  'dag.current': 'Review current',
  'dag.stale': 'Review stale',
  'dag.toRevision': 'Issues to revision',
  'dag.toRevisionDone': 'Revision task created.',
  'dag.toRevisionFailed': 'Revision task failed',
  'graph.unresolved': 'Unresolved entity',
  'graph.kind.character': 'Characters',
  'graph.kind.faction': 'Factions',
  'graph.kind.place': 'Places',
  'graph.kind.concept': 'Concepts',
  'graph.kind.other': 'Other',
  'graph.truth': 'Truth ledger',
  'graph.truth.currentState': 'Current state',
  'graph.truth.ledger': 'Resource ledger',
  'graph.truth.relationships': 'Relationship matrix',
  'graph.workflows': 'Workflows',
  'graph.workflow.currentStage': 'Current stage',
  'graph.empty.truth': 'No truth-file content yet. The agent updates the data/world/ truth files as chapters advance.',
  'graph.empty.truthDoc': '(empty)',
  'graph.empty.workflows': 'No active chapter workflows.',
  'graph.reviewDag': 'Review DAG',
  'graph.reviewFramework': 'Standard review framework',
  'graph.reviewDomains': 'domains',
  'graph.reviewChecks': 'checks',
  'graph.reviewCriteria': 'criteria',
  'graph.deliveryDag': 'Delivery DAG',
  'graph.filter.all': 'All',
  'graph.filter.anomaly': 'Anomalies',
  'graph.filter.blocker': 'Blockers',
  'graph.expandChecks': 'Expand 37 checks',
  'graph.collapseChecks': 'Collapse 37 checks',
  'graph.empty.dag': 'No materialized DAG for this chapter.',
  'benchmark.title': 'In-framework model benchmark',
  'benchmark.task': 'Background task',
  'benchmark.mode': 'Execution mode',
  'benchmark.mode.framework': 'Production framework',
  'benchmark.mode.creative': 'Creative diagnostic',
  'benchmark.mode.unknown': 'Legacy run (execution mode unrecorded)',
  'benchmark.reviewer': 'Review model',
  'benchmark.chapter': 'Chapter',
  'benchmark.repeats': 'Repeats',
  'benchmark.words': 'Target words',
  'benchmark.concurrency': 'Concurrency',
  'benchmark.run': 'Run benchmark',
  'benchmark.empty': 'No model benchmark runs yet.',
  'benchmark.select': 'Select a run to inspect cross-review results.',
  'benchmark.averageScore': 'Average score',
  'benchmark.output': 'Generated output',
  'benchmark.candidate': 'Writing candidate',
  'benchmark.candidates': 'Candidate reliability',
  'benchmark.evaluations': 'Independent blind review',
  'benchmark.writer': 'Writer model',
  'benchmark.path': 'Execution path',
  'benchmark.status': 'Status',
  'benchmark.actualWords': 'Actual words',
  'benchmark.finishReason': 'Finish reason',
  'benchmark.error': 'Error',
  'benchmark.coverage': 'Coverage',
  'benchmark.gate': 'Quality gate',
  'benchmark.delivery': 'Delivery advice',
  'benchmark.productionGate': 'Production gate',
  'benchmark.productionGateMissing': 'Not recorded (not production approval)',
  'benchmark.domains': 'Incomplete domains',
  'benchmark.latency': 'Latency',
  'benchmark.usage': 'Usage',
  'benchmark.cost': 'Cost',
  'benchmark.inputTokens': 'Input',
  'benchmark.outputTokens': 'Output',
  'benchmark.reasoningTokens': 'Reasoning',
  'benchmark.totalTokens': 'Total',
  'benchmark.actualCost': 'Actual cost',
  'benchmark.costCoverage': 'Cost reported',
  'benchmark.effectiveRate': 'Blended effective / 1M',
  'benchmark.runs': 'runs',
  'benchmark.sameInputGroup': 'Same experiment conditions',
  'benchmark.comparisonIncomplete': 'This historical artifact lacks part of its comparison basis. Inspect it only within this group.',
  'benchmark.inputProvenance': 'Input and provenance',
  'benchmark.runPhases': 'Observed run phases',
  'benchmark.phase.created': 'Task created',
  'benchmark.phase.started': 'Execution started',
  'benchmark.phase.completed': 'Artifact completed',
  'benchmark.contextHash': 'Context hash',
  'benchmark.comparisonKey': 'Comparison group hash',
  'benchmark.promptVersion': 'Prompt version',
  'benchmark.rubricVersion': 'Rubric version',
  'benchmark.blindReview': 'Independent blind review',
  'benchmark.contextStrategy': 'Context strategy',
  'benchmark.manifestVersion': 'Context manifest version',
  'benchmark.tokenEstimator': 'Token estimator',
  'benchmark.packetRevision': 'Packet revision',
  'benchmark.sourceRevision': 'Source revision',
  'benchmark.estimatedTokens': 'Estimated context tokens',
  'benchmark.characters': 'Characters',
  'benchmark.contextSources': 'Context source details',
  'benchmark.sourcePresent': 'present',
  'benchmark.sourceMissing': 'missing',
  'benchmark.responseIdentity': 'Actual response model',
  'models.title': 'Model profiles',
  'models.list': 'Profile list',
  'models.editor': 'Profile editor',
  'models.new': 'New profile',
  'models.empty': 'No model profiles configured.',
  'models.id': 'Profile ID',
  'models.label': 'Profile name',
  'models.provider': 'Protocol adapter',
  'models.protocol.openai': 'OpenAI-compatible',
  'models.protocol.anthropic': 'Anthropic',
  'models.modelId': 'Real model ID',
  'models.baseUrl': 'Base URL',
  'models.apiFormat': 'Request format',
  'models.context': 'Context tokens',
  'models.output': 'Output tokens',
  'models.credential': 'Chat',
  'models.embeddingProvider': 'Embedding protocol adapter',
  'models.embeddingModel': 'Embedding model ID',
  'models.embeddingCredential': 'Embedding',
  'models.credentialHint': 'Leave blank to keep the stored API Key',
  'models.remember': 'Remember the newly entered API Key on this save (write-only)',
  'models.save': 'Save profile',
  'models.chatTest': 'Chat test',
  'models.embeddingTest': 'Embedding test',
  'models.delete': 'Delete profile',
  'models.delete.confirm': 'Confirm delete',
  'models.delete.blocked': 'Deletion blocked',
  'models.delete.wouldFail': 'Routes that would fail',
  'models.test.untested': 'Untested',
  'models.test.ok': 'Last test passed',
  'models.test.failed': 'Last test failed',
  'models.dependencies': 'Dependency preview',
  'models.dependenciesHint': 'These operation routes use this profile; choose a fallback before deletion.',
  'models.fallback': 'Fallback after deletion',
  'models.chooseFallback': 'Choose fallback',
  'models.routes': 'Operation routes',
  'models.routesSave': 'Save routes',
  'models.saved': 'Model profile saved.',
  'models.deleted': 'Model profile deleted.',
  'models.chatOk': 'Chat connection succeeded.',
  'models.embeddingOk': 'Embedding connection succeeded.',
  'models.configured': 'Chat configured',
  'models.missing': 'Chat not configured',
  'models.routesSaved': 'Operation routes saved.',
  'models.group.basic': 'Basic info',
  'models.group.connection': 'API connection',
  'models.group.generation': 'Generation parameters',
  'models.group.embedding': 'Embedding settings',
  'models.group.credentials': 'API Key',
  'models.group.routeUsage': 'Route usage',
  'models.temperature': 'Temperature',
  'models.timeout': 'Timeout (seconds)',
  'models.embeddingBaseUrl': 'Embedding base URL',
  'models.validation.required': 'Missing required fields: profile ID, name, real model ID.',
  'models.validation.positive': 'Numeric fields must be valid positive numbers.',
  'models.validation.temperature': 'Temperature must be between 0 and 2.',
  'models.unsavedChanges': 'This profile has unsaved changes.',
  'models.unsavedDiscard': 'Discard changes',
  'models.unsavedKeep': 'Keep editing',
  'models.test.loading': 'Testing…',
  'models.usedByRoutes': 'Routes using this profile',
  'models.noRoutes': 'Not used by any route.',
  'models.delete.resultingRoutes': 'Routes after deletion',
  'models.embeddingEmpty': 'No Embedding profiles yet. Click “New profile” to create one.',
  'models.embeddingConfigured': 'Embedding configured',
  'models.embeddingMissing': 'Embedding not configured',
  'models.active': 'Active',
  'models.inactive': 'Inactive',
  'models.route.goethe': 'Goethe chat',
  'models.route.dante': 'Dante chat',
  'models.route.chapter_write': 'Chapter writing',
  'models.route.review': 'Chapter review',
  'models.route.source_extract': 'Source extraction',
  'models.route.revision': 'Revision',
  'models.route.search': 'Project search',
  'models.route.research': 'Research',
  'models.routesImpact': 'Route changes',
  'models.routesUnchanged': 'No route changes.',
  'models.routesUnassigned': 'No profile assigned',
  'models.embedConfigured': 'Embedding configured',
  'models.embedMissing': 'Embedding not configured',
  'models.capability.chat': 'Chat',
  'models.capability.embedding': 'Embedding',
  'research.reports': 'Reports',
  'research.unavailable': 'The deep-research runtime is not ready. Finish the setup in Studio first.',
  'research.empty': 'No research reports yet. Ask the agent to run a deep research, then refresh.',
  'research.selectHint': 'Select a report on the left to read it.',
  'research.report.loading': 'Loading report…',
  'research.quality': 'Quality',
  'research.language': 'Language',
  'research.filter.keyword': 'Search title, prompt, task, or model…',
  'research.filter.status': 'Status',
  'research.filter.sources': 'Sources',
  'research.filter.all': 'All',
  'research.status.succeeded': 'Succeeded',
  'research.status.failed': 'Failed',
  'research.status.needsReview': 'Needs human review',
  'research.status.unknown': 'Legacy status unknown',
  'research.sourcesAvailable': 'Source index available',
  'research.sourcesUnavailable': 'Source index unrecorded',
  'research.sourcesEmpty': 'The source index exists but contains no source rows.',
  'research.sources': 'Sources',
  'research.sourceCheck': 'Source verification',
  'research.source.cited': 'Cited in report',
  'research.source.uncited': 'Not cited in report',
  'research.exportMarkdown': 'Export Markdown',
  'research.referenceOnly': 'Research reports are reference material and never enter canon, outline, or manuscript automatically.',
  'research.prompt': 'Research prompt',
  'research.taskId': 'Task ID',
  'research.episodeId': 'Research run ID',
  'research.model': 'Model identity',
  'research.searchProvider': 'Search provider',
  'research.createdAt': 'Started at',
  'research.completedAt': 'Completed at',
  'research.latency': 'Actual latency',
  'research.wordCount': 'Report characters',
  'research.tokens': 'Actual tokens',
  'research.cost': 'Actual cost',
  'research.sourcesStatus': 'Source status',
  'research.metrics': 'Raw run metrics',
  'search.placeholder': 'Search project material…',
  'search.hint': 'Type a query to search the outline, chapters, characters, settings and other project material.',
  'search.empty': 'No matching results.',
  'search.indexed': 'indexed',
  'search.timeout': 'The search request timed out. Make sure Studio is running, then retry.',
  'search.scope.all': 'All',
  'search.scope.outline': 'Outline',
  'search.scope.core': 'Story core',
  'search.scope.characters': 'Characters',
  'search.scope.settings': 'Settings',
  'search.scope.continuity': 'Continuity',
  'search.scope.chapters': 'Chapters',
  'search.scope.sources': 'Sources',
  'assets.references': 'References',
  'reference.intent.reference': 'Reference',
  'reference.intent.continuation': 'Continuation',
  'reference.intent.canon': 'Canon',
  'reference.intent.migration': 'Migration',
  'reference.structure.awaiting_confirmation': 'Structure pending',
  'reference.structure.confirmed': 'Structure confirmed',
  'reference.analysis.complete': 'Analyzed',
  'reference.analysis.pending': 'Analysis incomplete',
  'reference.chars': 'chars',
  'reference.content.loading': 'Loading reference text…',
  'reference.content.full': 'Full text',
}
