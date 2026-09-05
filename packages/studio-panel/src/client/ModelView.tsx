import { useCallback, useEffect, useRef, useState } from "react";
import {
  FlaskConical,
  MessageSquare,
  Plus,
  RefreshCw,
  Save,
  Trash2,
} from "lucide-react";
import type { ConvViewProps } from "@deepseek-ai/dsh-client-ui-conversation/client";
import type { InjectFace, PropsLocale } from "@deepseek-ai/dsh-client-ui-slots";
import { StudioApiError, type StudioApiInjected } from "./api.ts";
import {
  parseConnectionTestResult,
  parseDeletePreview,
  parseModelProfiles,
  parseRouteImpact,
  parseRouteMap,
  asInteger,
  asRecord,
  asText,
  parseTestRecord,
  type DeletePreviewDto,
  type JsonRecord,
  type ModelProfileDto,
  type ModelTestRecordDto,
  type RouteImpactDto,
} from "./dto.ts";
import { useWorkbench } from "./WorkbenchStore.ts";
import css from "./views.module.css";

type Props = ConvViewProps &
  InjectFace<StudioApiInjected> &
  PropsLocale<"studio-panel">;
type Form = {
  id: string;
  label: string;
  provider: string;
  model: string;
  base_url: string;
  api_format: string;
  context_tokens: string;
  max_output_tokens: string;
  temperature: string;
  timeout_seconds: string;
  api_key: string;
  remember_api_key: boolean;
};
type Embedding = {
  id: string;
  label: string;
  provider: string;
  model: string;
  base_url: string;
  dimension: string;
  max_tokens: string;
  configured: boolean;
  active: boolean;
  last_test: ModelTestRecordDto | null;
  api_key: string;
};
const emptyForm = (): Form => ({
  id: "",
  label: "",
  provider: "openai",
  model: "",
  base_url: "",
  api_format: "chat",
  context_tokens: "64000",
  max_output_tokens: "24000",
  temperature: "0.7",
  timeout_seconds: "120",
  api_key: "",
  remember_api_key: true,
});
const emptyEmbedding = (): Embedding => ({
  id: "",
  label: "",
  provider: "openai",
  model: "text-embedding-3-small",
  base_url: "https://api.openai.com/v1",
  dimension: "1536",
  max_tokens: "8192",
  configured: false,
  active: false,
  last_test: null,
  api_key: "",
});
const newEmbeddingDraft = (): Embedding => ({
  ...emptyEmbedding(),
  id: `embedding-${Date.now().toString(36)}`,
  label: "新 Embedding 档案",
});
const snapshot = (value: unknown) => JSON.stringify(value);
// Connection outcomes and active/configured markers are server metadata,
// never user edits. Refreshing them must not make a clean draft dirty.
const embeddingSnapshot = ({ configured: _configured, active: _active, last_test: _test, ...fields }: Embedding) => snapshot(fields);
const errorText = (cause: unknown) =>
  cause instanceof StudioApiError && cause.code
    ? `${cause.code}: ${cause.message}`
    : cause instanceof Error
      ? cause.message
      : String(cause);
const marker = (
  t: Props["t"],
  record: ModelTestRecordDto | null,
  busy: boolean,
) => {
  if (busy) return t("models.test.loading");
  if (!record) return t("models.test.untested");
  const latency =
    record.latency_ms === null ? "—" : `${Math.round(record.latency_ms)} ms`;
  return record.status === "ok"
    ? `${t("models.test.ok")} · ${latency}`
    : `${t("models.test.failed")} ${record.error_code ?? ""} · ${latency}`;
};
const routeOrder = [
  "goethe",
  "dante",
  "chapter_write",
  "review",
  "source_extract",
  "revision",
  "search",
  "research",
] as const;

export function ModelView({ fetchStudioApi, postStudioApi, t }: Props) {
  const workbench = useWorkbench();
  const [profiles, setProfiles] = useState<ModelProfileDto[]>([]);
  const [embeddingProfiles, setEmbeddingProfiles] = useState<Embedding[]>([]);
  const [activeEmbeddingId, setActiveEmbeddingId] = useState("");
  const [routes, setRoutes] = useState<Record<string, string>>({});
  const [savedRoutes, setSavedRoutes] = useState<Record<string, string>>({});
  const [selectedId, setSelectedId] = useState("");
  const [form, setForm] = useState<Form>(emptyForm);
  const [embedding, setEmbedding] = useState<Embedding>(emptyEmbedding);
  const [tab, setTab] = useState<"chat" | "embedding">("chat");
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState<{ text: string; bad: boolean } | null>(
    null,
  );
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState("");
  const [routeImpact, setRouteImpact] = useState<RouteImpactDto | null>(null);
  const [pendingAction, setPendingAction] = useState<(() => void) | null>(null);
  const [deletePreview, setDeletePreview] = useState<DeletePreviewDto | null>(null);
  const [fallbackId, setFallbackId] = useState("");
  const mounted = useRef(true);
  const formBase = useRef(snapshot(emptyForm()));
  const embeddingBase = useRef(embeddingSnapshot(emptyEmbedding()));
  const formDirty = snapshot(form) !== formBase.current;
  const embeddingDirty = embeddingSnapshot(embedding) !== embeddingBase.current;
  const routesDirty = snapshot(routes) !== snapshot(savedRoutes);
  // Reloads read the current drafts without making load() an effect dependency
  // of every keystroke. A mutation refreshes only the section it committed.
  const drafts = useRef({ form, embedding, selectedId, routes, formDirty, embeddingDirty, routesDirty });
  drafts.current = { form, embedding, selectedId, routes, formDirty, embeddingDirty, routesDirty };
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const resetChat = (p?: ModelProfileDto) => {
    const next: Form = p ? {
      id: p.id, label: p.label, provider: p.provider === "anthropic" ? "anthropic" : "openai",
      model: p.model, base_url: p.base_url, api_format: p.api_format || "chat",
      context_tokens: String(p.context_tokens), max_output_tokens: String(p.max_output_tokens),
      temperature: String(p.temperature), timeout_seconds: String(p.timeout_seconds),
      api_key: "", remember_api_key: true,
    } : emptyForm();
    setSelectedId(p?.id ?? "");
    setForm(next);
    formBase.current = snapshot(next);
    setDeletePreview(null);
  };
  const resetEmbedding = (p: Embedding = emptyEmbedding()) => {
    const next = { ...p, api_key: "" };
    setEmbedding(next);
    embeddingBase.current = embeddingSnapshot(next);
  };
  type LoadOptions = { preserveChat?: boolean; preserveEmbedding?: boolean; preserveRoutes?: boolean; chatId?: string; embeddingId?: string };
  const load = useCallback(async (options: LoadOptions = {}) => {
    setBusy("load");
    try {
      const value = await fetchStudioApi("/model/profiles");
      if (!mounted.current) return;
      const next = parseModelProfiles(value);
      const root = asRecord(asRecord(value).data ?? value);
      const rawEmb = Array.isArray(root["embedding_profiles"]) ? root["embedding_profiles"] : [];
      const embeds: Embedding[] = rawEmb.map((raw) => {
        const x = asRecord(raw);
        return {
          id: asText(x.id), label: asText(x.label), provider: asText(x.provider) || "openai",
          model: asText(x.model), base_url: asText(x.base_url),
          dimension: String(asInteger(x.dimension, 1536)), max_tokens: String(asInteger(x.max_tokens, 8192)),
          configured: x.configured === true, active: x.active === true,
          last_test: parseTestRecord(x.last_test), api_key: "",
        };
      }).filter((x) => x.id);
      const activeId = asText(root["active_embedding_profile_id"]);
      setProfiles(next);
      setEmbeddingProfiles(embeds);
      setActiveEmbeddingId(activeId);
      const map = parseRouteMap(value);
      setSavedRoutes(map);
      if (!options.preserveRoutes) setRoutes(map);
      if (!options.preserveChat) {
        const id = options.chatId ?? drafts.current.selectedId;
        resetChat(next.find((p) => p.id === id) ?? next[0]);
      }
      if (!options.preserveEmbedding) {
        const id = options.embeddingId ?? (drafts.current.embedding.id || activeId);
        resetEmbedding(embeds.find((p) => p.id === id) ?? embeds.find((p) => p.id === activeId) ?? embeds[0]);
      } else {
        setEmbedding((current) => {
          const saved = embeds.find((p) => p.id === current.id);
          return saved ? { ...current, configured: saved.configured, active: saved.active, last_test: saved.last_test } : current;
        });
      }
      setState("ready");
      setLoadError("");
    } catch (cause) {
      if (mounted.current) {
        setState("error");
        setLoadError(errorText(cause));
      }
    } finally {
      if (mounted.current) setBusy("");
    }
  }, [fetchStudioApi]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (workbench.epochs.models > 0) {
      const current = drafts.current;
      void load({ preserveChat: current.formDirty, preserveEmbedding: current.embeddingDirty, preserveRoutes: current.routesDirty });
    }
  }, [load, workbench.epochs.models]);
  const guarded = (dirty: boolean, action: () => void) => {
    if (busy) return;
    if (dirty) setPendingAction(() => action);
    else { setNotice(null); action(); }
  };
  const refresh = () => guarded(formDirty || embeddingDirty || routesDirty, () => { void load(); });
  const setField = (key: keyof Form, value: string | boolean) => setForm((current) => ({ ...current, [key]: value }) as Form);
  const setEmbed = (key: keyof Embedding, value: string) => setEmbedding((current) => ({ ...current, [key]: value }));
  const validationError = (message: "models.validation.required" | "models.validation.positive" | "models.validation.temperature") => {
    setNotice({ text: t(message), bad: true });
  };
  const positiveInteger = (value: string) => Number.isInteger(Number(value)) && Number(value) > 0;
  const saveChat = async () => {
    if (busy) return;
    if (![form.id, form.label, form.model].every((value) => value.trim())) return validationError("models.validation.required");
    if (![form.context_tokens, form.max_output_tokens].every(positiveInteger) || !Number.isFinite(Number(form.timeout_seconds)) || Number(form.timeout_seconds) <= 0) return validationError("models.validation.positive");
    if (!form.temperature.trim() || !Number.isFinite(Number(form.temperature)) || Number(form.temperature) < 0 || Number(form.temperature) > 2) return validationError("models.validation.temperature");
    setBusy("save");
    try {
      const payload: JsonRecord = {
        ...form, id: form.id.trim(), label: form.label.trim(), model: form.model.trim(),
        context_tokens: Number(form.context_tokens), max_output_tokens: Number(form.max_output_tokens),
        temperature: Number(form.temperature), timeout_seconds: Number(form.timeout_seconds),
      };
      if (!form.api_key) delete payload.api_key;
      await postStudioApi("/model/profiles", payload);
      setForm((current) => ({ ...current, api_key: "" }));
      await load({ chatId: form.id.trim(), preserveEmbedding: true, preserveRoutes: drafts.current.routesDirty });
      setNotice({ text: t("models.saved"), bad: false });
    } catch (cause) { setNotice({ text: errorText(cause), bad: true }); }
    finally { setBusy(""); }
  };
  const saveEmbedding = async () => {
    if (busy) return;
    if (![embedding.id, embedding.label, embedding.model].every((value) => value.trim())) return validationError("models.validation.required");
    if (![embedding.dimension, embedding.max_tokens].every(positiveInteger)) return validationError("models.validation.positive");
    setBusy("embedding-save");
    try {
      const payload: JsonRecord = {
        id: embedding.id.trim(), label: embedding.label.trim(), provider: embedding.provider,
        model: embedding.model.trim(), base_url: embedding.base_url,
        dimension: Number(embedding.dimension), max_tokens: Number(embedding.max_tokens), remember_api_key: true,
      };
      if (embedding.api_key) payload.api_key = embedding.api_key;
      await postStudioApi("/model/embedding", payload);
      setEmbedding((current) => ({ ...current, api_key: "" }));
      await load({ embeddingId: embedding.id.trim(), preserveChat: true, preserveRoutes: drafts.current.routesDirty });
      setNotice({ text: t("models.saved"), bad: false });
    } catch (cause) { setNotice({ text: errorText(cause), bad: true }); }
    finally { setBusy(""); }
  };
  const test = async (kind: "chat" | "embedding") => {
    if (busy) return;
    setBusy(`${kind}-test`);
    let outcome: { text: string; bad: boolean };
    try {
      const target: JsonRecord = kind === "chat"
        ? { ...form, context_tokens: Number(form.context_tokens), max_output_tokens: Number(form.max_output_tokens), temperature: Number(form.temperature), timeout_seconds: Number(form.timeout_seconds) }
        : { id: embedding.id, label: embedding.label, provider: embedding.provider, model: embedding.model, base_url: embedding.base_url, dimension: Number(embedding.dimension), max_tokens: Number(embedding.max_tokens), api_key: embedding.api_key };
      if (!target.api_key) delete target.api_key;
      const result = parseConnectionTestResult(await postStudioApi(kind === "chat" ? "/model/test" : "/model/embedding/test", target));
      outcome = { text: `${kind === "chat" ? t("models.chatOk") : t("models.embeddingOk")} · ${result.latency_ms === null ? "—" : `${Math.round(result.latency_ms)} ms`}`, bad: false };
    } catch (cause) { outcome = { text: errorText(cause), bad: true }; }
    // Probing a draft must not save it, erase it, or clear its entered key.
    await load({ preserveChat: true, preserveEmbedding: true, preserveRoutes: true });
    if (mounted.current) setNotice(outcome);
  };
  const selectEmbedding = async (id: string) => {
    if (busy) return;
    setBusy("embedding-select");
    try {
      await postStudioApi("/model/embedding/select", { profile_id: id });
      await load({ embeddingId: id, preserveChat: true, preserveRoutes: drafts.current.routesDirty });
    } catch (cause) { setNotice({ text: errorText(cause), bad: true }); }
    finally { setBusy(""); }
  };
  const deleteEmbedding = async () => {
    if (busy || !embeddingProfiles.some((p) => p.id === embedding.id) || embeddingProfiles.length <= 1 || !window.confirm("Delete this Embedding profile?")) return;
    setBusy("embedding-delete");
    try {
      await postStudioApi("/model/embedding/delete", { profile_id: embedding.id });
      await load({ embeddingId: "", preserveChat: true, preserveRoutes: drafts.current.routesDirty });
      setNotice({ text: t("models.deleted"), bad: false });
    } catch (cause) { setNotice({ text: errorText(cause), bad: true }); }
    finally { setBusy(""); }
  };
  const previewDelete = async (fallback: string) => {
    if (busy || !selectedId) return;
    setBusy("delete-preview");
    setDeletePreview(null);
    setFallbackId(fallback);
    try {
      setDeletePreview(parseDeletePreview(await postStudioApi("/model/profiles/delete-preview", { profile_id: selectedId, fallback_id: fallback })));
    } catch (cause) { setNotice({ text: errorText(cause), bad: true }); }
    finally { setBusy(""); }
  };
  const deleteChat = async () => {
    if (busy || !deletePreview?.deletable || deletePreview.profile_id !== selectedId) return;
    setBusy("delete");
    try {
      await postStudioApi("/model/profiles/delete", { profile_id: selectedId, fallback_id: fallbackId });
      setDeletePreview(null);
      await load({ preserveEmbedding: true });
      setNotice({ text: t("models.deleted"), bad: false });
    } catch (cause) { setNotice({ text: errorText(cause), bad: true }); }
    finally { setBusy(""); }
  };
  const saveRoutes = async () => {
    if (busy) return;
    setBusy("routes");
    try {
      const result = parseRouteImpact(await postStudioApi("/model/routes", { routes }));
      setRoutes(result.routes);
      setSavedRoutes(result.routes);
      setRouteImpact(result);
      setNotice({ text: t("models.routesSaved"), bad: false });
    } catch (cause) { setNotice({ text: errorText(cause), bad: true }); }
    finally { setBusy(""); }
  };
  const routeLabel = (route: string) => routeOrder.includes(route as typeof routeOrder[number]) ? t(`models.route.${route}` as Parameters<Props["t"]>[0]) : route;
  if (state === "loading")
    return (
      <div className={css.root}>
        <div className={css.notice}>{t("loading")}</div>
      </div>
    );
  if (state === "error")
    return (
      <div className={css.root}>
        <div className={css.notice}>
          <span className={css.errorText}>{loadError}</span>
          <button
            type="button"
            className={css.button}
            onClick={() => void load()}
          >
            {t("retry")}
          </button>
        </div>
      </div>
    );
  return (
    <div className={css.root}>
      <div className={css.toolbar}>
        <span className={css.toolbarMeta}>{t("models.title")}</span>
        <span className={css.toolbarActions}>
          <button
            type="button"
            className={css.button}
            onClick={refresh}
            disabled={!!busy}
            title={t("refresh")}
          >
            <RefreshCw size={14} />
          </button>
        </span>
      </div>
      <div className={css.body}>
        {pendingAction && (
          <div className={css.notice} role="alert">
            <span>{t("models.unsavedChanges")}</span>
            <button type="button" className={css.button} onClick={() => setPendingAction(null)}>{t("models.unsavedKeep")}</button>
            <button type="button" className={css.button} onClick={() => { setPendingAction(null); setNotice(null); pendingAction(); }}>{t("models.unsavedDiscard")}</button>
          </div>
        )}
        {notice && (
          <div
            className={notice.bad ? css.taskError : css.notice}
            role={notice.bad ? "alert" : "status"}
          >
            {notice.text}
          </div>
        )}
        <div className={css.modelTabs}>
          <button
            type="button"
            className={css.button}
            data-active={tab === "chat"}
            disabled={!!busy}
            onClick={() => setTab("chat")}
          >
            <MessageSquare size={14} /> Chat
          </button>
          <button
            type="button"
            className={css.button}
            data-active={tab === "embedding"}
            disabled={!!busy}
            onClick={() => setTab("embedding")}
          >
            <FlaskConical size={14} /> Embedding
          </button>
        </div>
        {tab === "chat" ? (
          <>
            <div className={css.modelLayout}>
              <section className={css.modelList} aria-label={t("models.list")}>
                <button
                  type="button"
                  className={css.button}
                  disabled={!!busy}
                  onClick={() => guarded(formDirty, () => resetChat())}
                >
                  <Plus size={14} /> {t("models.new")}
                </button>
                {profiles.length === 0 && <p className={css.modelEmpty}>{t("models.empty")}</p>}
                {profiles.map((p) => (
                  <button
                    type="button"
                    key={p.id}
                    className={css.modelListItem}
                    data-active={p.id === selectedId}
                    disabled={!!busy}
                    onClick={() => { if (p.id !== selectedId) guarded(formDirty, () => resetChat(p)); }}
                  >
                    <strong>{p.label}</strong>
                    <span>
                      {p.provider} · {p.model}
                    </span>
                    <small>
                      {p.configured
                        ? t("models.configured")
                        : t("models.missing")}{" "}
                      · {t("models.chatTest")} {marker(t, p.last_test, false)}
                    </small>
                  </button>
                ))}
              </section>
              <section className={css.modelEditor} aria-label={t("models.editor")}>
                <fieldset className={css.modelGroup}>
                  <legend className={css.modelGroupTitle}>
                    {t("models.group.basic")}
                  </legend>
                  <div className={css.modelFormGrid}>
                    <label>
                      {t("models.id")}
                      <input
                        value={form.id}
                        disabled={!!selectedId}
                        onChange={(e) => setField("id", e.target.value)}
                      />
                    </label>
                    <label>
                      {t("models.label")}
                      <input
                        value={form.label}
                        onChange={(e) => setField("label", e.target.value)}
                      />
                    </label>
                    <label>
                      {t("models.provider")}
                      <select
                        value={form.provider}
                        onChange={(e) => setField("provider", e.target.value)}
                      >
                        <option value="openai">{t("models.protocol.openai")}</option>
                        <option value="anthropic">{t("models.protocol.anthropic")}</option>
                      </select>
                    </label>
                    <label>
                      {t("models.modelId")}
                      <input
                        value={form.model}
                        onChange={(e) => setField("model", e.target.value)}
                      />
                    </label>
                  </div>
                </fieldset>
                <fieldset className={css.modelGroup}>
                  <legend className={css.modelGroupTitle}>
                    {t("models.group.connection")}
                  </legend>
                  <div className={css.modelFormGrid}>
                    <label>
                      {t("models.baseUrl")}
                      <input
                        value={form.base_url}
                        onChange={(e) => setField("base_url", e.target.value)}
                      />
                    </label>
                    <label>
                      {t("models.apiFormat")}
                      <input
                        value={form.api_format}
                        onChange={(e) => setField("api_format", e.target.value)}
                      />
                    </label>
                    <label>
                      {t("models.timeout")}
                      <input
                        type="number"
                        value={form.timeout_seconds}
                        onChange={(e) =>
                          setField("timeout_seconds", e.target.value)
                        }
                      />
                    </label>
                  </div>
                </fieldset>
                <fieldset className={css.modelGroup}>
                  <legend className={css.modelGroupTitle}>
                    {t("models.group.generation")}
                  </legend>
                  <div className={css.modelFormGrid}>
                    <label>
                      {t("models.context")}
                      <input
                        type="number"
                        value={form.context_tokens}
                        onChange={(e) =>
                          setField("context_tokens", e.target.value)
                        }
                      />
                    </label>
                    <label>
                      {t("models.output")}
                      <input
                        type="number"
                        value={form.max_output_tokens}
                        onChange={(e) =>
                          setField("max_output_tokens", e.target.value)
                        }
                      />
                    </label>
                    <label>
                      {t("models.temperature")}
                      <input
                        type="number"
                        step="0.1"
                        value={form.temperature}
                        onChange={(e) =>
                          setField("temperature", e.target.value)
                        }
                      />
                    </label>
                  </div>
                </fieldset>
                <fieldset className={css.modelGroup}>
                  <legend className={css.modelGroupTitle}>
                    {t("models.group.credentials")}
                  </legend>
                  <input
                    className={css.modelApiKeyInput}
                    type="password"
                    aria-label={t("models.group.credentials")}
                    autoComplete="new-password"
                    value={form.api_key}
                    onChange={(e) => setField("api_key", e.target.value)}
                    placeholder={t("models.credentialHint")}
                  />
                  <label className={css.modelCheckbox}>
                    <input
                      type="checkbox"
                      checked={form.remember_api_key}
                      onChange={(e) =>
                        setField("remember_api_key", e.target.checked)
                      }
                    />
                    {t("models.remember")}
                  </label>
                </fieldset>
                <fieldset className={css.modelGroup}>
                  <legend className={css.modelGroupTitle}>{t("models.group.routeUsage")}</legend>
                  <ul>{Object.entries(savedRoutes).filter(([, id]) => id === selectedId).map(([route]) => <li key={route}>{routeLabel(route)}</li>)}</ul>
                </fieldset>
                <div className={css.modelTestRow}>
                  {t("models.chatTest")} · {marker(t, profiles.find((p) => p.id === selectedId)?.last_test ?? null, busy === "chat-test")}
                </div>
                <div className={css.modelActions}>
                  <button
                    type="button"
                    className={css.button}
                    onClick={() => void saveChat()}
                    disabled={!!busy}
                  >
                    <Save size={14} /> {t("models.save")}
                  </button>
                  <button
                    type="button"
                    className={css.button}
                    onClick={() => void test("chat")}
                    disabled={!!busy || !form.model}
                  >
                    <MessageSquare size={14} /> {t("models.chatTest")}
                  </button>
                  {selectedId && <button type="button" className={css.buttonDanger} disabled={!!busy}
                    onClick={() => guarded(formDirty || routesDirty, () => { void previewDelete(profiles.find((p) => p.id !== selectedId)?.id ?? ""); })}>
                    <Trash2 size={14} /> {t("models.delete")}
                  </button>}
                </div>
                {deletePreview && <div className={css.modelDependencies}>
                  <p>{t("models.usedByRoutes")}: {deletePreview.used_by_routes.map(routeLabel).join(", ") || t("models.noRoutes")}</p>
                  <label>{t("models.fallback")}
                    <select value={fallbackId} disabled={!!busy} onChange={(event) => { void previewDelete(event.target.value); }}>
                      <option value="">{t("models.chooseFallback")}</option>
                      {deletePreview.fallback_candidates.map((candidate) => <option value={candidate.id} key={candidate.id}>{candidate.label}</option>)}
                    </select>
                  </label>
                  {deletePreview.routes_that_would_fail.length > 0 && <p>{t("models.delete.wouldFail")}: {deletePreview.routes_that_would_fail.map(routeLabel).join(", ")}</p>}
                  {deletePreview.blocking_reasons.length > 0 && <p>{t("models.delete.blocked")}: {deletePreview.blocking_reasons.join(", ")}</p>}
                  <p>{t("models.delete.resultingRoutes")}: {Object.entries(deletePreview.resulting_routes ?? {}).map(([route, id]) => `${routeLabel(route)} → ${id}`).join(", ")}</p>
                  <button type="button" className={css.buttonDanger} disabled={!!busy || !deletePreview.deletable} onClick={() => void deleteChat()}>{t("models.delete.confirm")}</button>
                </div>}
              </section>
            </div>
            <section
              className={css.modelRoutes}
              aria-label={t("models.routes")}
            >
              <div className={css.paneHeading}>{t("models.routes")}</div>
              {Object.keys(routes)
                .sort(
                  (a, b) =>
                    routeOrder.indexOf(a as never) -
                    routeOrder.indexOf(b as never),
                )
                .map((route) => (
                  <div className={css.modelRouteRow} key={route}>
                    <label>
                      {routeLabel(route)}
                      <select
                        value={routes[route] ?? ""}
                        disabled={!!busy}
                        onChange={(e) =>
                          setRoutes((x) => ({ ...x, [route]: e.target.value }))
                        }
                      >
                        {profiles.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.label}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                ))}
              <button
                type="button"
                className={css.button}
                onClick={() => void saveRoutes()}
                disabled={!!busy || !routesDirty}
              >
                <Save size={14} /> {t("models.routesSave")}
              </button>
              {routeImpact && (
                <p className={css.modelImpact}>
                  {t("models.routesImpact")}: {routeImpact.changed_routes.map((change) => `${routeLabel(change.route)}: ${change.from ?? "—"} → ${change.to ?? "—"}`).join("; ") || t("models.routesUnchanged")}
                </p>
              )}
            </section>
          </>
        ) : (
          <div className={css.modelLayout}>
            <section className={css.modelList} aria-label="Embedding profiles">
              <button type="button" className={css.button} onClick={() => guarded(embeddingDirty, () => resetEmbedding(newEmbeddingDraft()))} disabled={!!busy}>
                <Plus size={14} /> {t('models.new')}
              </button>
              {embeddingProfiles.length === 0 && (
                <p className={css.modelEmpty}>{t('models.embeddingEmpty')}</p>
              )}
              {embeddingProfiles.map((p) => (
                <button
                  type="button"
                  key={p.id}
                  className={css.modelListItem}
                  data-active={p.id === activeEmbeddingId}
                  disabled={!!busy}
                  onClick={() => guarded(embeddingDirty, () => { void selectEmbedding(p.id); })}
                >
                  <strong>{p.label}</strong>
                  <span>
                    {p.provider} · {p.model}
                  </span>
                  <small>
                    {p.active ? `${t("models.active")} · ` : ""}
                    {p.configured
                      ? t("models.embeddingConfigured")
                      : t("models.embeddingMissing")}{" "}
                    · {t("models.embeddingTest")} {marker(t, p.last_test, false)}
                  </small>
                </button>
              ))}
            </section>
            <section className={css.modelEditor}>
              <div className={css.modelActiveStatus} aria-live="polite">
                {embedding.active ? t("models.active") : t("models.inactive")}
              </div>
              <fieldset className={css.modelGroup}>
                <legend className={css.modelGroupTitle}>{t('models.group.basic')}</legend>
                <div className={css.modelFormGrid}>
                <label>
                  {t("models.id")}
                  <input
                    value={embedding.id}
                    disabled={embeddingProfiles.some((p) => p.id === embedding.id)}
                    onChange={(e) => setEmbed("id", e.target.value)}
                  />
                </label>
                <label>
                  {t("models.label")}
                  <input
                    value={embedding.label}
                    onChange={(e) => setEmbed("label", e.target.value)}
                  />
                </label>
                </div>
              </fieldset>
              <fieldset className={css.modelGroup}>
                <legend className={css.modelGroupTitle}>{t('models.group.connection')}</legend>
                <div className={css.modelFormGrid}>
                <label>
                  {t("models.embeddingProvider")}
                  <input
                    value={embedding.provider}
                    onChange={(e) => setEmbed("provider", e.target.value)}
                  />
                </label>
                <label>
                  {t("models.embeddingModel")}
                  <input
                    value={embedding.model}
                    onChange={(e) => setEmbed("model", e.target.value)}
                  />
                </label>
                <label>
                  {t("models.embeddingBaseUrl")}
                  <input
                    value={embedding.base_url}
                    onChange={(e) => setEmbed("base_url", e.target.value)}
                  />
                </label>
                </div>
              </fieldset>
              <fieldset className={css.modelGroup}>
                <legend className={css.modelGroupTitle}>Vector parameters</legend>
                <div className={css.modelFormGrid}>
                <label>
                  Dimension
                  <input
                    type="number"
                    value={embedding.dimension}
                    onChange={(e) => setEmbed("dimension", e.target.value)}
                  />
                </label>
                <label>
                  Max tokens
                  <input
                    type="number"
                    value={embedding.max_tokens}
                    onChange={(e) => setEmbed("max_tokens", e.target.value)}
                  />
                </label>
                </div>
              </fieldset>
              <fieldset className={css.modelGroup}>
                <legend className={css.modelGroupTitle}>{t('models.group.credentials')}</legend>
                <div className={css.modelFormGrid}>
                  <input
                    className={css.modelApiKeyInput}
                    type="password"
                    aria-label={t("models.group.credentials")}
                    autoComplete="new-password"
                    value={embedding.api_key}
                    onChange={(e) => setEmbed("api_key", e.target.value)}
                  />
                </div>
              </fieldset>
              <div className={css.modelTestRow}>
                <span>{t('models.embeddingTest')} · {marker(t, embedding.last_test, busy === 'embedding-test')}</span>
              </div>
              <div className={css.modelActions}>
              <button
                type="button"
                className={css.button}
                onClick={() => void saveEmbedding()}
                disabled={!!busy}
              >
                <Save size={14} /> {t("models.save")}
              </button>
              <button
                type="button"
                className={css.button}
                onClick={() => void test("embedding")}
                disabled={!!busy || !embedding.id}
              >
                <FlaskConical size={14} /> {t("models.embeddingTest")}
              </button>
              <button
                type="button"
                className={css.buttonDanger}
                onClick={() => void deleteEmbedding()}
                disabled={!!busy || embeddingProfiles.length <= 1 || !embeddingProfiles.some((p) => p.id === embedding.id)}
              >
                <Trash2 size={14} /> {t("models.delete")}
              </button>
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
