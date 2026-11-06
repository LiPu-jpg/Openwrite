import { existsSync, readFileSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { createLlmChatFromEnv } from "@deepresearch/embedding-providers";
import { BingSearchProvider, BochaSearchProvider, FallbackSearchProvider, FetchPageProvider, JinaSearchProvider, stripHtml } from "@deepresearch/tool-providers";
import type { EpisodeResult, EpisodeStack, EvidenceQualityMode, FetchProvider, HumanReviewResponse, LlmChat, MemoryEvent, RuntimeProfile, SearchProvider, TaskSubmission } from "@deepresearch/contracts";
import { createInMemoryOrchestrator } from "./orchestrator.js";
import { resolveEvidenceQualityPolicy } from "./evidence-quality.js";
import { loadDefaultRuntimeProfile } from "./infra/config.js";
import { ResearchStreamRenderer, type ResearchStreamFrame, type ResearchStreamMode } from "./stream-renderer.js";
import { abortError, throwIfAborted } from "@deepresearch/net-utils";

export type ResearchLlmProviderName = "bigmodel" | "deepseek" | "openai" | "custom";
export type ResearchSearchProviderName = "bing" | "bocha" | "jina" | "none";

/**
 * Fetch through the dsh host's loopback web relay.
 *
 * The host owns the web providers (including the model-facing web_fetch tool);
 * the research child only has an HTTP face onto them. Keeping this provider
 * here, beside the other fetch construction, means the framework never needs a
 * provider registry change to gain a host-backed fetch.
 */
class RelayFetchProvider implements FetchProvider {
  readonly name = "dsh-web-fetch";
  constructor(
    private readonly url: string,
    private readonly token: string,
    private readonly timeoutMs: number,
    private readonly maxChars: number,
  ) {}

  async fetchPage(url: string, opts: { timeoutMs?: number; maxChars?: number; signal?: AbortSignal } = {}) {
    const response = await fetch(`${this.url.replace(/\/+$/, "")}/fetch`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${this.token}` },
      body: JSON.stringify({ url }),
      signal: opts.signal ?? AbortSignal.timeout(opts.timeoutMs ?? this.timeoutMs),
    });
    if (!response.ok) throw new Error(`dsh web fetch HTTP ${response.status}`);
    const payload = await response.json() as {
      url?: string; statusCode?: number; body?: { kind?: string; content?: string }; truncated?: boolean
    };
    if (typeof payload.statusCode === "number" && payload.statusCode >= 400) {
      throw new Error(`dsh web fetch HTTP ${payload.statusCode} for ${url}`);
    }
    const raw = typeof payload.body?.content === "string" ? payload.body.content : "";
    const content = payload.body?.kind === "html" ? stripHtml(raw) : raw;
    const maxChars = opts.maxChars ?? this.maxChars;
    return {
      url: payload.url?.trim() || url,
      title: "",
      content: content.slice(0, maxChars),
      description: "",
    };
  }
}

const DEBUG_TEST_MAX_ASPECTS = 2;
const DEBUG_TEST_MAX_BRANCHES_PER_ASPECT = 2;

export interface ResearchRunInput {
  prompt: string;
  sessionId?: string;
  artifactDir?: string;
  language?: string;
  citationRequired?: boolean;
  maxCycles?: number;
  completionRepairCycles?: number;
  reportMaxTokens?: number;
  reportMaxCalls?: number;
  reportContextTokenLimit?: number;
  evidenceTargetSteps?: number;
  evidenceTargetFetchCalls?: number;
  maxEpisodeCostUsd?: number;
  maxLlmRequests?: number;
  maxEpisodeTokens?: number;
  adaptiveBudget?: boolean;
  humanReview?: boolean;
  humanReviewResponse?: HumanReviewResponse;
  evidenceQualityMode?: EvidenceQualityMode;
  debugSingleBranch?: boolean;
  debugMaxAspects?: number;
  debugMaxBranchesPerAspect?: number;
  debugMaxInitialAgentNodes?: number;
  debugMaxAgentNodeParts?: number;
  checkpointDir?: string;
  resumeCheckpointPath?: string;
  disableCheckpoints?: boolean;
  traceLevel?: "summary" | "full";
  streamMode?: ResearchStreamMode;
  streamMaxChars?: number;
  runtimeProfile?: RuntimeProfile;
  cwd?: string;
  now?: () => number;
  signal?: AbortSignal;
  env?: NodeJS.ProcessEnv;
  llm?: LlmChat;
  llmProvider?: ResearchLlmProviderName;
  reviewLlm?: LlmChat;
  reviewLlmProvider?: ResearchLlmProviderName;
  search?: SearchProvider;
  searchProvider?: ResearchSearchProviderName;
  fetch?: FetchProvider;
  stack?: Partial<EpisodeStack>;
  onEvent?: (event: MemoryEvent) => void | Promise<void>;
  onFrame?: (frame: ResearchStreamFrame) => void | Promise<void>;
}

export interface ResearchRunOutput {
  result: EpisodeResult;
  summary: ResearchRunSummary;
}

export type ResearchStreamMessage =
  | { type: "frame"; frame: ResearchStreamFrame }
  | { type: "result"; result: EpisodeResult; summary: ResearchRunSummary };

export interface ResearchRunSummary {
  status: EpisodeResult["status"];
  episodeId: string;
  report: string;
  evidenceIndex?: string;
  evidenceQualityAudit?: string;
  budgetAudit?: string;
  humanReviewResponse?: string;
  trace?: string;
  fullTrace?: string;
  checkpoint?: string;
  resumeCommand?: string;
  filesExist: {
    report: boolean;
    evidenceIndex: boolean;
    evidenceQualityAudit?: boolean;
    budgetAudit?: boolean;
    humanReviewResponse?: boolean;
    trace: boolean;
    fullTrace: boolean;
    checkpoint: boolean;
  };
  metrics: EpisodeResult["metrics"];
}

export function buildResearchRuntimeProfile(input: Pick<ResearchRunInput, "runtimeProfile" | "cwd" | "artifactDir" | "maxCycles" | "completionRepairCycles" | "reportMaxTokens" | "reportMaxCalls" | "reportContextTokenLimit" | "evidenceTargetSteps" | "evidenceTargetFetchCalls" | "maxEpisodeCostUsd" | "maxLlmRequests" | "maxEpisodeTokens" | "adaptiveBudget" | "humanReview" | "evidenceQualityMode" | "debugSingleBranch" | "debugMaxAspects" | "debugMaxBranchesPerAspect" | "debugMaxInitialAgentNodes" | "debugMaxAgentNodeParts" | "traceLevel" | "streamMode">): RuntimeProfile {
  const profile = structuredClone(input.runtimeProfile ?? loadDefaultRuntimeProfile(input.cwd ?? process.cwd())) as RuntimeProfile;
  profile.evidenceQuality = resolveEvidenceQualityPolicy(profile.evidenceQuality);
  if (typeof input.humanReview === "boolean") profile.hilMode = input.humanReview ? "explicit" : "auto_accept";
  if (input.evidenceQualityMode) profile.evidenceQuality.mode = input.evidenceQualityMode;
  if (input.artifactDir) profile.artifactDir = input.artifactDir;
  if (typeof input.maxEpisodeCostUsd === "number") {
    if (!Number.isFinite(input.maxEpisodeCostUsd) || input.maxEpisodeCostUsd < 0) throw new Error("maxEpisodeCostUsd must be >= 0");
    profile.providers.episode = { ...profile.providers.episode, maxCostUsd: input.maxEpisodeCostUsd };
    // The episode limit is the final cross-provider guard. A lower inherited
    // LLM-only limit would make the UI's requested episode budget impossible
    // to use and can stop a run before the displayed limit is reached.
    profile.providers.default_llm = { ...profile.providers.default_llm, maxCostUsd: input.maxEpisodeCostUsd };
  }
  if (typeof input.maxLlmRequests === "number") {
    if (!Number.isFinite(input.maxLlmRequests) || input.maxLlmRequests < 0) throw new Error("maxLlmRequests must be >= 0");
    profile.providers.default_llm = { ...profile.providers.default_llm, maxRequests: Math.floor(input.maxLlmRequests) };
  }
  if (typeof input.maxEpisodeTokens === "number") {
    if (!Number.isFinite(input.maxEpisodeTokens) || input.maxEpisodeTokens < 0) throw new Error("maxEpisodeTokens must be >= 0");
    profile.providers.episode = { ...profile.providers.episode, maxTotalTokens: Math.floor(input.maxEpisodeTokens) };
    profile.providers.default_llm = { ...profile.providers.default_llm, maxTotalTokens: Math.floor(input.maxEpisodeTokens) };
  }
  if (typeof input.adaptiveBudget === "boolean") {
    profile.adaptiveBudget = { ...profile.adaptiveBudget!, enabled: input.adaptiveBudget };
  }
  if (typeof input.maxCycles === "number") {
    const dispatchEvidence = profile.phases.dispatchEvidence;
    if (!dispatchEvidence) throw new Error("RuntimeProfile.phases.dispatchEvidence is required");
    dispatchEvidence.maxCycles = input.maxCycles;
  }
  if (typeof input.completionRepairCycles === "number") {
    if (!Number.isFinite(input.completionRepairCycles) || input.completionRepairCycles < 0) throw new Error("completionRepairCycles must be >= 0");
    const completionGate = profile.phases.completionGate;
    if (!completionGate) throw new Error("RuntimeProfile.phases.completionGate is required");
    completionGate.maxCycles = Math.floor(input.completionRepairCycles);
  }
  if (typeof input.reportMaxTokens === "number") {
    const reportLlm = profile.llm.report;
    if (!reportLlm) throw new Error("RuntimeProfile.llm.report is required");
    reportLlm.maxTokens = input.reportMaxTokens;
  }
  if (typeof input.reportMaxCalls === "number" || typeof input.reportContextTokenLimit === "number") {
    const reportPhase = profile.phases.report;
    if (!reportPhase) throw new Error("RuntimeProfile.phases.report is required");
    if (typeof input.reportMaxCalls === "number") reportPhase.maxLlmCalls = input.reportMaxCalls;
    if (typeof input.reportContextTokenLimit === "number") reportPhase.contextTokenLimit = input.reportContextTokenLimit;
  }
  if (typeof input.evidenceTargetSteps === "number" || typeof input.evidenceTargetFetchCalls === "number") {
    const evidenceAgent = profile.agents.evidence;
    if (!evidenceAgent) throw new Error("RuntimeProfile.agents.evidence is required");
    if (typeof input.evidenceTargetSteps === "number") {
      evidenceAgent.targetReactSteps = Math.max(1, Math.floor(input.evidenceTargetSteps));
      evidenceAgent.maxReactSteps = evidenceAgent.targetReactSteps * 2;
      const targetToolCalls = Math.max(1, evidenceAgent.targetReactSteps - 1);
      const maxToolCalls = Math.max(1, evidenceAgent.maxReactSteps - 1);
      const targetSearchCalls = Math.max(1, Math.ceil(evidenceAgent.targetReactSteps / 6));
      const maxSearchCalls = Math.max(1, Math.ceil(evidenceAgent.maxReactSteps / 6));
      evidenceAgent.targetToolCalls = targetToolCalls;
      evidenceAgent.maxToolCalls = maxToolCalls;
      evidenceAgent.targetSearchCalls = targetSearchCalls;
      evidenceAgent.maxSearchCalls = maxSearchCalls;
    }
    if (typeof input.evidenceTargetFetchCalls === "number") {
      const targetFetchCalls = Math.max(0, Math.floor(input.evidenceTargetFetchCalls));
      evidenceAgent.targetFetchCalls = Math.min(targetFetchCalls, evidenceAgent.targetToolCalls ?? targetFetchCalls);
      evidenceAgent.maxFetchCalls = Math.min(targetFetchCalls * 2, evidenceAgent.maxToolCalls ?? targetFetchCalls * 2);
    }
  }
  if (input.debugSingleBranch || typeof input.debugMaxAspects === "number" || typeof input.debugMaxBranchesPerAspect === "number" || typeof input.debugMaxInitialAgentNodes === "number" || typeof input.debugMaxAgentNodeParts === "number") {
    const dispatchEvidence = profile.phases.dispatchEvidence;
    if (!dispatchEvidence) throw new Error("RuntimeProfile.phases.dispatchEvidence is required");
    const maxAspects = Math.min(DEBUG_TEST_MAX_ASPECTS, Math.max(1, Math.floor(input.debugMaxAspects ?? DEBUG_TEST_MAX_ASPECTS)));
    const maxBranchesPerAspect = Math.min(DEBUG_TEST_MAX_BRANCHES_PER_ASPECT, Math.max(1, Math.floor(input.debugMaxBranchesPerAspect ?? DEBUG_TEST_MAX_BRANCHES_PER_ASPECT)));
    const branchCountLimit = maxAspects * maxBranchesPerAspect;
    const maxInitialAgentNodes = Math.min(
      branchCountLimit,
      Math.max(1, Math.floor(input.debugMaxInitialAgentNodes ?? branchCountLimit)),
    );
    const maxAgentNodeParts = Math.max(1, Math.floor(input.debugMaxAgentNodeParts ?? (input.debugSingleBranch ? 2 : 8)));
    profile.debug = {
      ...(profile.debug ?? {}),
      singleBranch: input.debugSingleBranch ?? profile.debug?.singleBranch,
      maxAspects,
      maxBranchesPerAspect,
      maxInitialAgentNodes,
      maxAgentNodeParts,
    };
    dispatchEvidence.maxParallelAgents = Math.min(dispatchEvidence.maxParallelAgents ?? maxInitialAgentNodes, maxInitialAgentNodes);
    dispatchEvidence.maxConcurrentAgents = Math.min(dispatchEvidence.maxConcurrentAgents ?? 1, Math.max(1, maxInitialAgentNodes));
    if (input.debugSingleBranch) dispatchEvidence.maxCycles = Math.min(dispatchEvidence.maxCycles ?? 2, 2);
  }
  if (input.traceLevel) profile.traceLevel = input.traceLevel;
  if (requiresFullTrace(input.streamMode) && profile.traceLevel !== "full") profile.traceLevel = "full";
  return profile;
}

export function createResearchLlmFromEnv(env: NodeJS.ProcessEnv = process.env, provider?: ResearchLlmProviderName, cwd = process.cwd()): LlmChat {
  return createLlmChatFromEnv({
    env: mergeResearchEnv(env, cwd),
    providerOverride: provider,
    loadEnvFile: false,
  });
}

export function createResearchReviewLlmFromEnv(env: NodeJS.ProcessEnv = process.env, cwd = process.cwd()): LlmChat | undefined {
  const merged = mergeResearchEnv(env, cwd);
  const provider = merged.PUBLISH_REVIEW_PROVIDER?.trim().toLowerCase();
  if (!provider) return undefined;
  if (!["bigmodel", "deepseek", "openai", "custom"].includes(provider)) {
    throw new Error(`Unsupported PUBLISH_REVIEW_PROVIDER: ${provider}`);
  }
  const reviewEnv = { ...merged };
  const model = merged.PUBLISH_REVIEW_MODEL?.trim();
  if (model) {
    if (provider === "deepseek") reviewEnv.DEEPSEEK_MODEL = model;
    else if (provider === "bigmodel") reviewEnv.BIGMODEL_MODEL = model;
    else reviewEnv.AGENT_MODEL = model;
  }
  if (merged.PUBLISH_REVIEW_REASONING_EFFORT) {
    reviewEnv.AGENT_REASONING_EFFORT = merged.PUBLISH_REVIEW_REASONING_EFFORT;
  }
  const delegate = createLlmChatFromEnv({ env: reviewEnv, providerOverride: provider, loadEnvFile: false });
  return {
    name: `review:${delegate.name}:${model || "default"}`,
    chat: (request) => delegate.chat(request),
  };
}

export function createResearchSearchFromEnv(env: NodeJS.ProcessEnv = process.env, provider: ResearchSearchProviderName = "bocha", cwd = process.cwd()): SearchProvider | undefined {
  const merged = mergeResearchEnv(env, cwd);
  if (provider === "none") return undefined;
  if (provider === "bing") {
    const bing = new BingSearchProvider({
      timeoutMs: Number(merged.BING_TIMEOUT_MS ?? 30000),
      market: merged.BING_MARKET ?? "zh-CN",
    });
    const jinaApiKey = merged.JINA_API_KEY?.trim();
    if (!jinaApiKey) return bing;
    const jina = new JinaSearchProvider({
      apiKey: jinaApiKey,
      timeoutMs: Number(merged.JINA_TIMEOUT_MS ?? 90000),
      retry: Number(merged.JINA_RETRY ?? 3),
      maxNum: Number(merged.JINA_MAX_NUM ?? 20),
      proxy: merged.HTTPS_PROXY ?? merged.https_proxy ?? merged.HTTP_PROXY ?? merged.http_proxy,
    });
    return new FallbackSearchProvider({
      providers: [bing, jina],
      acceptResults: acceptBingResearchResults,
    });
  }
  if (provider === "bocha") {
    const apiKey = merged.BOCHA_API_KEY;
    if (!apiKey) throw new Error("BOCHA_API_KEY is required when searchProvider is bocha");
    return new BochaSearchProvider({
      apiKey,
      endpoint: merged.BOCHA_ENDPOINT,
      timeoutMs: Number(merged.BOCHA_TIMEOUT_MS ?? 60000),
      retry: Number(merged.BOCHA_RETRY ?? 2),
      count: Number(merged.BOCHA_COUNT ?? 10),
      maxCount: Number(merged.BOCHA_MAX_COUNT ?? 50),
      freshness: bochaFreshness(merged.BOCHA_FRESHNESS),
      summary: merged.BOCHA_SUMMARY === undefined ? true : merged.BOCHA_SUMMARY !== "0" && merged.BOCHA_SUMMARY.toLowerCase() !== "false",
      minIntervalMs: Number(merged.BOCHA_MIN_INTERVAL_MS ?? 350),
      retryBaseDelayMs: Number(merged.BOCHA_RETRY_BASE_DELAY_MS ?? 1500),
      maxRetryDelayMs: Number(merged.BOCHA_MAX_RETRY_DELAY_MS ?? 15000),
    });
  }
  if (provider === "jina") {
    const apiKey = merged.JINA_API_KEY;
    if (!apiKey) throw new Error("JINA_API_KEY is required when searchProvider is jina");
    return new JinaSearchProvider({
      apiKey,
      timeoutMs: Number(merged.JINA_TIMEOUT_MS ?? 90000),
      retry: Number(merged.JINA_RETRY ?? 3),
      maxNum: Number(merged.JINA_MAX_NUM ?? 20),
      proxy: merged.HTTPS_PROXY ?? merged.https_proxy ?? merged.HTTP_PROXY ?? merged.http_proxy,
    });
  }
  return undefined;
}

const LOW_VALUE_RESEARCH_HOST = /(?:^|\.)(?:baike\.baidu\.com|wenku\.baidu\.com|zhidao\.baidu\.com|dictionary\.cambridge\.org|oxfordlearnersdictionaries\.com|kmcha\.com)$/iu;

export function acceptBingResearchResults(input: {
  query: string;
  providerName: string;
  results: Array<{ url: string }>;
}): boolean {
  if (input.providerName !== "bing-html") return true;
  const requestedHosts = Array.from(input.query.matchAll(/\bsite:\s*([a-z0-9.-]+)\b/giu), (match) => match[1]!.toLowerCase());
  const resultHosts = input.results.flatMap((result) => {
    try {
      return [new URL(result.url).hostname.toLowerCase().replace(/^www\./u, "")];
    } catch {
      return [];
    }
  });
  if (requestedHosts.length > 0 && !resultHosts.some((host) => requestedHosts.some((requested) => host === requested || host.endsWith(`.${requested}`)))) {
    return false;
  }
  return resultHosts.some((host) => !LOW_VALUE_RESEARCH_HOST.test(host));
}

export function createResearchFetchFromEnv(env: NodeJS.ProcessEnv = process.env, cwd = process.cwd()): FetchProvider {
  const merged = mergeResearchEnv(env, cwd);
  if ((merged.FETCH_PROVIDER ?? "").trim().toLowerCase() === "dsh") {
    const url = merged.OPENWRITE_WEB_RELAY_URL?.trim();
    const token = merged.OPENWRITE_WEB_RELAY_TOKEN?.trim();
    if (!url || !token) throw new Error("OPENWRITE_WEB_RELAY_URL/TOKEN are required when FETCH_PROVIDER=dsh");
    return new RelayFetchProvider(
      url,
      token,
      Number(merged.FETCH_TIMEOUT_MS ?? 30000),
      Number(merged.FETCH_MAX_CHARS ?? 180000),
    );
  }
  const legacyJina = merged.FETCH_USE_JINA_READER === "1" || merged.FETCH_PROVIDER === "jina";
  const mode = fetchMode(merged.FETCH_MODE) ?? (legacyJina ? "jina" : "direct");
  const readerInPlay = mode !== "direct";
  return new FetchPageProvider({
    mode,
    apiKey: merged.JINA_API_KEY,
    timeoutMs: Number(readerInPlay ? merged.JINA_READER_TIMEOUT_MS ?? merged.JINA_TIMEOUT_MS ?? 90000 : merged.FETCH_TIMEOUT_MS ?? 30000),
    maxChars: Number(readerInPlay ? merged.JINA_READER_MAX_CHARS ?? 180000 : merged.FETCH_MAX_CHARS ?? 180000),
    retry: Number(readerInPlay ? merged.JINA_READER_RETRY ?? merged.JINA_RETRY ?? 2 : merged.FETCH_RETRY ?? 1),
    proxy: merged.HTTPS_PROXY ?? merged.https_proxy ?? merged.HTTP_PROXY ?? merged.http_proxy,
    maxPdfBytes: Number(merged.FETCH_MAX_PDF_BYTES ?? 50_000_000),
    maxTextBytes: Number(merged.FETCH_MAX_TEXT_BYTES ?? 10_000_000),
    maxRedirects: Number(merged.FETCH_MAX_REDIRECTS ?? 5),
    allowPrivateNetwork: merged.FETCH_ALLOW_PRIVATE_NETWORK === "1",
    ocrScannedPdfs: merged.FETCH_PDF_OCR === "1",
    ocrLanguages: merged.FETCH_PDF_OCR_LANGUAGES ?? "eng",
    maxOcrPages: Number(merged.FETCH_PDF_OCR_MAX_PAGES ?? 12),
    ocrTimeoutMs: Number(merged.FETCH_PDF_OCR_TIMEOUT_MS ?? 120000),
    pdftoppmPath: merged.FETCH_PDFTOPPM_PATH,
    tesseractPath: merged.FETCH_TESSERACT_PATH,
  });
}

export async function runResearch(input: ResearchRunInput): Promise<ResearchRunOutput> {
  if (!input.prompt.trim() && !input.resumeCheckpointPath) throw new Error("Research prompt is required");
  if (input.humanReviewResponse && !input.resumeCheckpointPath) throw new Error("humanReviewResponse requires resumeCheckpointPath");
  throwIfAborted(input.signal, "Research run aborted");
  const streamMode = input.streamMode ?? (input.onFrame ? "steps" : "off");
  const checkpointProfile = input.runtimeProfile || !input.resumeCheckpointPath
    ? undefined
    : await readCheckpointRuntimeProfile(input.resumeCheckpointPath);
  const runtimeProfile = buildResearchRuntimeProfile({
    ...input,
    runtimeProfile: input.runtimeProfile ?? checkpointProfile,
    streamMode,
  });
  const streamRenderer = input.onFrame && streamMode !== "off"
    ? new ResearchStreamRenderer({ mode: streamMode, maxTranscriptChars: input.streamMaxChars })
    : undefined;
  const llm = input.llm ?? input.stack?.llm ?? createResearchLlmFromEnv(input.env, input.llmProvider, input.cwd);
  const reviewLlm = input.reviewLlm
    ?? input.stack?.reviewLlm
    ?? (input.reviewLlmProvider
      ? createResearchLlmFromEnv(input.env, input.reviewLlmProvider, input.cwd)
      : createResearchReviewLlmFromEnv(input.env, input.cwd));
  const resolvedSearchProvider = input.searchProvider
    ?? searchProviderName(mergeResearchEnv(input.env ?? process.env, input.cwd).SEARCH_PROVIDER)
    ?? "bocha";
  const search = input.search ?? (resolvedSearchProvider === "none"
    ? undefined
    : input.stack?.search ?? createResearchSearchFromEnv(input.env, resolvedSearchProvider, input.cwd));
  const fetch = input.fetch ?? input.stack?.fetch ?? (!input.search && resolvedSearchProvider !== "none" ? createResearchFetchFromEnv(input.env, input.cwd) : undefined);
  const orchestrator = createInMemoryOrchestrator({
    runtimeProfile,
    artifactDir: runtimeProfile.artifactDir,
    checkpointDir: input.checkpointDir,
    resumeCheckpointPath: input.resumeCheckpointPath,
    humanReviewResponse: input.humanReviewResponse,
    disableCheckpoints: input.disableCheckpoints,
    llm,
    reviewLlm,
    search,
    fetch,
    stack: input.stack,
    now: input.now,
    signal: input.signal,
    onEvent: async (event) => {
      throwIfAborted(input.signal, "Research run aborted");
      await input.onEvent?.(event);
      const frame = streamRenderer?.render(event);
      if (frame) await input.onFrame?.(frame);
    },
  });
  const submission: TaskSubmission = {
    sessionId: input.sessionId ?? `S_run_${Date.now()}`,
    userInput: input.prompt,
    uiOptions: {
      outputLanguage: input.language,
      citationRequired: input.citationRequired ?? true,
    },
  };
  const result = await orchestrator.runEpisode(submission, { runtimeProfile });
  return { result, summary: summarizeEpisodeResult(result) };
}

async function readCheckpointRuntimeProfile(checkpointPath: string): Promise<RuntimeProfile | undefined> {
  const resolved = checkpointPath.endsWith(".json") ? checkpointPath : join(checkpointPath, "latest.json");
  try {
    const checkpoint = JSON.parse(await readFile(resolved, "utf8")) as { state?: { runtimeProfile?: RuntimeProfile } };
    return checkpoint.state?.runtimeProfile ? structuredClone(checkpoint.state.runtimeProfile) : undefined;
  } catch {
    // Checkpoint restoration below remains the source of truth for missing or invalid files.
    return undefined;
  }
}

export async function* streamResearch(input: ResearchRunInput): AsyncGenerator<ResearchStreamMessage> {
  const queue: ResearchStreamMessage[] = [];
  let wake: (() => void) | undefined;
  let done = false;
  let error: unknown;

  const notify = () => {
    wake?.();
    wake = undefined;
  };
  const enqueue = (message: ResearchStreamMessage) => {
    queue.push(message);
    notify();
  };

  const abortListener = () => {
    error = abortError(input.signal, "Research run aborted");
    notify();
  };
  input.signal?.addEventListener("abort", abortListener, { once: true });

  void runResearch({
    ...input,
    streamMode: input.streamMode ?? "steps",
    onFrame: async (frame) => {
      await input.onFrame?.(frame);
      enqueue({ type: "frame", frame });
    },
  }).then((output) => {
    enqueue({ type: "result", result: output.result, summary: output.summary });
  }).catch((err: unknown) => {
    error = err;
  }).finally(() => {
    done = true;
    notify();
  });

  try {
    while (!done || queue.length > 0) {
      const next = queue.shift();
      if (next) {
        yield next;
        continue;
      }
      if (error) throw error;
      await new Promise<void>((resolve) => {
        wake = resolve;
      });
    }
  } finally {
    input.signal?.removeEventListener("abort", abortListener);
  }
  if (error) throw error;
}

export function summarizeEpisodeResult(result: EpisodeResult): ResearchRunSummary {
  const checkpoint = join(dirname(result.reportArtifactPath), "checkpoints", "latest.json");
  const checkpointExists = existsSync(checkpoint);
  return {
    status: result.status,
    episodeId: result.episodeId,
    report: result.reportArtifactPath,
    evidenceIndex: result.evidenceIndexPath,
    evidenceQualityAudit: result.evidenceQualityAuditPath,
    budgetAudit: result.budgetAuditPath,
    humanReviewResponse: result.humanReviewResponsePath,
    trace: result.tracePath,
    fullTrace: result.fullTracePath,
    checkpoint: checkpointExists ? checkpoint : undefined,
    resumeCommand: checkpointExists ? `pnpm research --resume ${JSON.stringify(checkpoint)}` : undefined,
    filesExist: {
      report: existsSync(result.reportArtifactPath),
      evidenceIndex: result.evidenceIndexPath ? existsSync(result.evidenceIndexPath) : false,
      evidenceQualityAudit: result.evidenceQualityAuditPath ? existsSync(result.evidenceQualityAuditPath) : false,
      budgetAudit: result.budgetAuditPath ? existsSync(result.budgetAuditPath) : false,
      humanReviewResponse: result.humanReviewResponsePath ? existsSync(result.humanReviewResponsePath) : false,
      trace: result.tracePath ? existsSync(result.tracePath) : false,
      fullTrace: result.fullTracePath ? existsSync(result.fullTracePath) : false,
      checkpoint: checkpointExists,
    },
    metrics: result.metrics,
  };
}

function requiresFullTrace(mode: ResearchStreamMode | undefined): boolean {
  return mode === "steps" || mode === "full" || mode === "transcript";
}

function bochaFreshness(value: string | undefined): "noLimit" | "oneDay" | "oneWeek" | "oneMonth" | "oneYear" | undefined {
  if (!value) return undefined;
  if (value === "noLimit" || value === "oneDay" || value === "oneWeek" || value === "oneMonth" || value === "oneYear") return value;
  throw new Error(`Unsupported BOCHA_FRESHNESS: ${value}`);
}

function fetchMode(value: string | undefined): "direct" | "jina" | "fallback" | undefined {
  if (!value) return undefined;
  const mode = value.trim().toLowerCase();
  if (mode === "direct" || mode === "jina" || mode === "fallback") return mode;
  throw new Error(`Unsupported FETCH_MODE: ${value}`);
}

function searchProviderName(value: string | undefined): ResearchSearchProviderName | undefined {
  if (!value) return undefined;
  const name = value.trim().toLowerCase();
  if (name === "bing" || name === "bocha" || name === "jina" || name === "none") return name;
  throw new Error(`Unsupported SEARCH_PROVIDER: ${value}`);
}

function mergeResearchEnv(env: NodeJS.ProcessEnv, cwd = process.cwd()): NodeJS.ProcessEnv {
  return { ...env, ...readEnvFile(cwd) };
}

function readEnvFile(cwd: string): NodeJS.ProcessEnv {
  const paths = [".env.local", ".env"];
  for (const name of paths) {
    const fullPath = `${cwd.replace(/\/$/, "")}/${name}`;
    try {
      const text = readFileSync(fullPath, "utf8");
      return parseEnvText(text);
    } catch {
      continue;
    }
  }
  return {};
}

function parseEnvText(text: string): NodeJS.ProcessEnv {
  const out: NodeJS.ProcessEnv = {};
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq <= 0) continue;
    const key = trimmed.slice(0, eq).trim();
    if (!key) continue;
    let value = trimmed.slice(eq + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    if (out[key] === undefined) out[key] = value;
  }
  return out;
}
