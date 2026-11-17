import { useEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle2,
  ChevronRight,
  ArrowRightLeft,
  FileSearch,
  RotateCcw,
  ScanText,
  Settings,
  Timer,
  Upload,
  X,
} from "lucide-react";
import {
  api,
  type Detail,
  type Document,
  type DocumentMemory,
  type FieldDefinition,
  type Result,
} from "./lib/api";
import { fieldLabel, fieldOrder } from "./lib/fields";
import { PageViewer } from "./components/PageViewer";
import { PipelineLog } from "./components/PipelineLog";
import { SettingsDialog } from "./components/SettingsDialog";
import "./styles.css";
import "./reset.css";

type ViewerTab = "original" | "optimized";

const elapsedLabel = (seconds: number) => {
  const minutes = Math.floor(seconds / 60).toString().padStart(2, "0");
  const remainder = (seconds % 60).toString().padStart(2, "0");
  return `${minutes}:${remainder}`;
};

export default function App() {
  const [documents, setDocuments] = useState<Document[]>([]),
    [fields, setFields] = useState<FieldDefinition[]>([]),
    [detail, setDetail] = useState<Detail>(),
    [memory, setMemory] = useState<DocumentMemory>(),
    [selectedFieldKey, setSelectedFieldKey] = useState<string>(),
    [candidateField, setCandidateField] = useState<FieldDefinition>(),
    [savingCandidateId, setSavingCandidateId] = useState<number>(),
    [pageNumber, setPageNumber] = useState<number>(),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [documentsOpen, setDocumentsOpen] = useState(false),
    [viewerTab, setViewerTab] = useState<ViewerTab>("original"),
    [localRunStartedAt, setLocalRunStartedAt] = useState<number>(),
    [interruptRequested, setInterruptRequested] = useState(false),
    [settingsOpen, setSettingsOpen] = useState(false),
    [settingsFields, setSettingsFields] = useState<FieldDefinition[]>([]),
    [settingsSaving, setSettingsSaving] = useState(false),
    [settingsError, setSettingsError] = useState(""),
    [elapsedSeconds, setElapsedSeconds] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const candidateCloseRef = useRef<HTMLButtonElement>(null);
  const progressRef = useRef("");
  const activeDocumentRef = useRef<string | undefined>(undefined);
  const displayedDocumentRef = useRef<string | undefined>(undefined);
  const refreshRequestRef = useRef(0);
  const batchIsProcessing = documents.some((doc) => ["PROCESSING", "QUEUED"].includes(doc.status));
  const isProcessing = detail?.status === "PROCESSING" || detail?.status === "QUEUED";
  const canReset = ["COMPLETED", "FAILED", "CANCELLED"].includes(detail?.status ?? "");
  const persistedRunStartedAt = memory?.run?.started_at
    ? new Date(memory.run.started_at).getTime()
    : undefined;
  const runStartedAt = isProcessing && localRunStartedAt
    ? localRunStartedAt
    : persistedRunStartedAt ?? localRunStartedAt;
  const completedAt = !isProcessing && memory?.run?.completed_at
    ? new Date(memory.run.completed_at).getTime()
    : undefined;
  const refresh = async (id?: string) => {
    if (id && activeDocumentRef.current && id !== activeDocumentRef.current) return;
    const requestId = ++refreshRequestRef.current;
    try {
      const docs = await api.documents();
      if (requestId !== refreshRequestRef.current) return;
      setDocuments(docs);
      const target = id ?? activeDocumentRef.current ?? docs[0]?.id;
      if (target) {
        if (!activeDocumentRef.current) activeDocumentRef.current = target;
        if (target !== activeDocumentRef.current) return;
        const [next, nextMemory] = await Promise.all([api.detail(target), api.memory(target)]);
        if (requestId !== refreshRequestRef.current || target !== activeDocumentRef.current) return;
        const documentChanged = displayedDocumentRef.current !== target;
        displayedDocumentRef.current = target;
        setDetail(next);
        setMemory(nextMemory);
        setPageNumber((p) =>
          documentChanged ? next.pages[0]?.page_number : (p ?? next.pages[0]?.page_number),
        );
        if (documentChanged) setSelectedFieldKey(undefined);
      }
    } catch (e) {
      setError(String(e));
    }
  };
  const openDocument = (id: string) => {
    if (id === activeDocumentRef.current) {
      setDocumentsOpen(false);
      return;
    }
    activeDocumentRef.current = id;
    refreshRequestRef.current += 1;
    setSelectedFieldKey(undefined);
    setPageNumber(undefined);
    setMemory(undefined);
    setDetail(undefined);
    setViewerTab("original");
    setLocalRunStartedAt(undefined);
    setInterruptRequested(false);
    setElapsedSeconds(0);
    setDocumentsOpen(false);
    void refresh(id);
  };
  useEffect(() => {
    refresh();
    const timer = setInterval(async () => {
      const selectedIsProcessing = detail?.status === "PROCESSING" || detail?.status === "QUEUED";
      if (!selectedIsProcessing && !batchIsProcessing) return;
      try {
        if (!selectedIsProcessing) {
          await refresh(detail?.id);
          return;
        }
        const status = await api.status(detail.id);
        const marker = `${status.status}:${status.completed_pages}:${status.latest_audit_id}`;
        if (marker !== progressRef.current) {
          progressRef.current = marker;
          await refresh(detail.id);
        }
      } catch (e) {
        setError(String(e));
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [detail?.id, detail?.status, batchIsProcessing]);
  useEffect(() => {
    if (!runStartedAt || !Number.isFinite(runStartedAt)) {
      setElapsedSeconds(0);
      return;
    }
    const updateElapsed = () =>
      setElapsedSeconds(Math.max(0, Math.floor(((completedAt ?? Date.now()) - runStartedAt) / 1000)));
    updateElapsed();
    if (completedAt || !isProcessing) return;
    const timer = window.setInterval(updateElapsed, 1000);
    return () => window.clearInterval(timer);
  }, [runStartedAt, completedAt, isProcessing]);
  useEffect(() => {
    api.fields()
      .then((items) => setFields(items.filter((field) => field.enabled)))
      .catch((reason) => setError(String(reason)));
  }, []);
  useEffect(() => {
    if (!candidateField) return;
    candidateCloseRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setCandidateField(undefined);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [candidateField]);
  useEffect(() => {
    if (!error) return;
    const timer = window.setTimeout(() => setError(""), 5000);
    return () => window.clearTimeout(timer);
  }, [error]);
  const orderedResults = useMemo(
    () =>
      [...(detail?.results ?? [])].sort(
        (a, b) => fieldOrder(a.field_key, fields) - fieldOrder(b.field_key, fields),
      ),
    [detail?.results, fields],
  );
  const pendingFields = useMemo(() => {
    const resultByKey = new Map((detail?.results ?? []).map((result) => [result.field_key, result]));
    return fields.filter((field) => {
      const result = resultByKey.get(field.key);
      return !result || !result.value?.trim();
    });
  }, [detail?.results, fields]);
  const hasExtractedData = orderedResults.some((result) => Boolean(result.value?.trim())) ||
    (memory?.candidates.length ?? 0) > 0;
  const showAnalysisPrompt = !isProcessing && !hasExtractedData;
  const candidatesByField = useMemo(() => {
    const grouped = new Map<string, NonNullable<DocumentMemory>["candidates"]>();
    for (const candidate of memory?.candidates ?? []) {
      const candidates = grouped.get(candidate.field_key) ?? [];
      candidates.push(candidate);
      grouped.set(candidate.field_key, candidates);
    }
    return grouped;
  }, [memory?.candidates]);
  const selectedCandidateByField = useMemo(() => {
    const candidateById = new Map((memory?.candidates ?? []).map((candidate) => [candidate.id, candidate]));
    const selected = new Map(
      (memory?.candidates ?? [])
        .filter((candidate) => candidate.selected)
        .map((candidate) => [candidate.field_key, candidate]),
    );
    for (const resolved of memory?.resolved_fields ?? []) {
      const candidate = resolved.selected_candidate_id
        ? candidateById.get(resolved.selected_candidate_id)
        : undefined;
      if (candidate) selected.set(resolved.field_key, candidate);
    }
    return selected;
  }, [memory?.candidates, memory?.resolved_fields]);
  const bestCandidateByField = useMemo(() => {
    const best = new Map<string, NonNullable<DocumentMemory>["candidates"][number]>();
    for (const [fieldKey, candidates] of candidatesByField) {
      const candidate = [...candidates].sort(
        (a, b) =>
          b.ocr_confidence - a.ocr_confidence ||
          b.vision_confidence - a.vision_confidence ||
          b.semantic_confidence - a.semantic_confidence ||
          a.id - b.id,
      )[0];
      if (candidate) best.set(fieldKey, candidate);
    }
    return best;
  }, [candidatesByField]);
  const valueChosenByAI = (fieldKey: string) => {
    const result = detail?.results.find((item) => item.field_key === fieldKey);
    const resolved = memory?.resolved_fields.find((item) => item.field_key === fieldKey);
    const candidate = selectedCandidateByField.get(fieldKey);
    return (
      result?.value?.trim() ||
      resolved?.value?.trim() ||
      candidate?.normalized_value ||
      candidate?.raw_value ||
      ""
    );
  };
  const upload = async (file?: File) => {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const doc = await api.upload(file);
      activeDocumentRef.current = doc.id;
      refreshRequestRef.current += 1;
      await refresh(doc.id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };
  const openSettings = async () => {
    try {
      setSettingsError("");
      const configuredFields = await api.fields();
      setSettingsFields(configuredFields);
      setSettingsOpen(true);
    } catch (e) {
      setError(String(e));
    }
  };
  const saveSettings = async (updatedFields: FieldDefinition[]) => {
    setSettingsSaving(true);
    setSettingsError("");
    try {
      const savedFields = await api.saveFields(updatedFields);
      setSettingsFields(savedFields);
      setFields(savedFields.filter((field) => field.enabled));
      setSelectedFieldKey((current) =>
        current && savedFields.some((field) => field.key === current && field.enabled)
          ? current
          : undefined,
      );
      setSettingsOpen(false);
    } catch (e) {
      setSettingsError(String(e));
    } finally {
      setSettingsSaving(false);
    }
  };
  const process = async () => {
    if (!detail || isProcessing) return;
    setBusy(true);
    setInterruptRequested(false);
    setLocalRunStartedAt(Date.now());
    setViewerTab("original");
    try {
      await api.process(detail.id, "AUTO");
      await refresh(detail.id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };
  const interrupt = async () => {
    if (!detail || !isProcessing || interruptRequested) return;
    setBusy(true);
    setError("");
    try {
      await api.interrupt(detail.id);
      setInterruptRequested(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };
  const resetEverything = async () => {
    if (
      !detail ||
      isProcessing ||
      !window.confirm(
        "Resettare completamente il documento? Verranno cancellati PDF ottimizzato, OCR, candidati e risultati. Il PDF originale resterà conservato.",
      )
    ) return;
    setBusy(true);
    setError("");
    try {
      await api.resetDocument(detail.id);
      setMemory(undefined);
      setSelectedFieldKey(undefined);
      setPageNumber(undefined);
      setViewerTab("original");
      setLocalRunStartedAt(undefined);
      setInterruptRequested(false);
      setElapsedSeconds(0);
      progressRef.current = "";
      await refresh(detail.id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };
  const chooseCandidate = async (field: FieldDefinition, candidateId: number, value: string) => {
    if (!detail || isProcessing) return;
    setSavingCandidateId(candidateId);
    setError("");
    try {
      await api.updateResult(detail.id, field.key, value, candidateId);
      await refresh(detail.id);
    } catch (e) {
      setError(String(e));
    } finally {
      setSavingCandidateId(undefined);
    }
  };
  const chooseResult = (result: Result) => {
    setSelectedFieldKey(result.field_key);
    const candidate = bestCandidateByField.get(result.field_key) ?? selectedCandidateByField.get(result.field_key);
    const page = candidate?.page_number ?? result.page_number;
    if (page) navigateToPage(page);
  };
  const navigateToPage = (page: number) => {
    setPageNumber(page);
    setViewerTab("optimized");
    window.requestAnimationFrame(() =>
      document
        .getElementById("page-viewer")
        ?.scrollIntoView({ behavior: "smooth", block: "start" }),
    );
  };
  const chooseField = (fieldKey: string) => {
    setSelectedFieldKey(fieldKey);
    const result = detail?.results.find((item) => item.field_key === fieldKey);
    if (result?.page_number) {
      navigateToPage(result.page_number);
      return;
    }
    const candidate = bestCandidateByField.get(fieldKey) ?? selectedCandidateByField.get(fieldKey);
    if (candidate) navigateToPage(candidate.page_number);
  };
  const selectedFieldResult = detail?.results.find((item) => item.field_key === selectedFieldKey);
  const selectedFieldCandidate = selectedFieldKey
    ? bestCandidateByField.get(selectedFieldKey) ?? selectedCandidateByField.get(selectedFieldKey)
    : undefined;
  const selectedEvidencePage = selectedFieldCandidate?.page_number ?? selectedFieldResult?.page_number;
  const selectedEvidenceBox = selectedFieldCandidate?.bounding_box ?? (
    selectedFieldResult?.page_number === selectedEvidencePage ? selectedFieldResult?.bbox : undefined
  );
  const selectedEvidenceConfidence =
    selectedFieldCandidate?.ocr_confidence ?? selectedFieldResult?.confidence;
  const saveResult = async (result: Result, value: string) => {
    if (!detail || value.trim() === (result.value ?? "")) return;
    try {
      await api.updateResult(detail.id, result.field_key, value);
      await refresh(detail.id);
    } catch (e) {
      setError(String(e));
    }
  };
  return (
    <div className="app">
      <header>
        <div className="header-side header-left">
        <div className="brand">
          <strong>Mnemos</strong>
          <button
            type="button"
            className="settings-trigger"
            onClick={() => void openSettings()}
            disabled={isProcessing || batchIsProcessing}
            title="Campi e regole della pipeline"
            aria-label="Apri impostazioni dei campi e delle regole"
          >
            <Settings size={17} />
          </button>
        </div>
        {detail && (
          <div className="header-document">
            <div className="header-document-name" title={detail.filename}>
              <strong>{detail.filename}</strong>
              <span>{detail.page_count || "—"} pagine</span>
            </div>
            <div className="document-switcher-wrap">
              <button
                className="document-switcher"
                onClick={() => setDocumentsOpen((open) => !open)}
                title="Cambia fascicolo"
                aria-label="Cambia fascicolo"
              >
                <ArrowRightLeft size={16} />
              </button>
              {documentsOpen && (
                <div className="document-switcher-menu">
                  {documents.map((doc) => (
                    <button
                      className={doc.id === detail.id ? "doc active" : "doc"}
                      key={doc.id}
                      onClick={() => openDocument(doc.id)}
                    >
                      {doc.status === "COMPLETED" ? (
                        <CheckCircle2 className="doc-completed-icon" />
                      ) : (
                        <FileSearch />
                      )}
                      <span>
                        <b>{doc.filename}</b>
                        <small>{doc.page_count || "—"} pagine · {doc.status}</small>
                      </span>
                      <ChevronRight />
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
        </div>
        <div className={`analysis-timer${isProcessing ? " running" : ""}`}>
          <Timer size={17} />
          <span>{elapsedLabel(elapsedSeconds)}</span>
          <small>{isProcessing ? "analisi" : "tempo"}</small>
        </div>
        <div className="header-side header-actions">
          {detail && canReset && (
            <button
              className="reset-all-button"
              onClick={() => void resetEverything()}
              disabled={busy}
              title="Cancella elaborazione e file derivati, mantenendo il PDF originale"
              aria-label="Resetta tutto"
            >
              <RotateCcw size={15} />
              <span>Resetta tutto</span>
            </button>
          )}
          <button
            className="upload-button"
            onClick={() => input.current?.click()}
            disabled={busy || isProcessing}
            title="Carica PDF"
            aria-label="Carica PDF"
          >
            <Upload size={17} />
            <span>Carica</span>
          </button>
          {detail && (isProcessing ? (
            <button
              className="primary analyze-button interrupt-button"
              onClick={() => void interrupt()}
              disabled={busy || interruptRequested}
              aria-label={interruptRequested ? "Interruzione richiesta" : "Interrompi analisi"}
              title="Interrompi al prossimo checkpoint sicuro"
            >
              <X size={17} />
              <span className="analyze-label">{interruptRequested ? "Interruzione…" : "Interrompi"}</span>
            </button>
          ) : (
            <button
              className="primary analyze-button"
              onClick={process}
              disabled={busy}
              aria-label="Analizza documento"
            >
              {detail.status === "COMPLETED" || detail.status === "FAILED" || detail.status === "CANCELLED" ? (
                <>
                  <RotateCcw size={16} />
                  <span className="analyze-label">Riprova</span>
                </>
              ) : (
                <>
                  <ScanText size={17} />
                  <span className="analyze-label">Analizza</span>
                </>
              )}
            </button>
          ))}
        </div>
        <input
          ref={input}
          type="file"
          accept="application/pdf"
          hidden
          onChange={(e) => {
            void upload(e.target.files?.[0]);
            e.currentTarget.value = "";
          }}
        />
      </header>
      {error && <div className="error">{error}</div>}
      <main>
        {!detail ? (
          <section className="welcome" onClick={() => input.current?.click()}>
            <Upload />
            <h1>Porta chiarezza nei fascicoli complessi.</h1>
            <p>Carica un PDF per ricostruirne struttura, campi e provenienza.</p>
          </section>
        ) : (
          <div className="workspace-three">
            <section className="fields-column" aria-label="Campi estratti">
              <div className="column-heading">
                <div>
                  <ScanText />
                  <h2>Campi estratti</h2>
                </div>
                <span>{fields.length}</span>
              </div>
              <div className="fields-scroll">
                {showAnalysisPrompt ? (
                  <div className="column-empty analysis-prompt">
                    <ScanText size={24} />
                    <strong>Nessun dato disponibile</strong>
                    <span>Avvia un’analisi del fascicolo per estrarre campi e contenuti.</span>
                  </div>
                ) : pendingFields.length > 0 && (
                  <section className="pending-fields" aria-label="Campi in attesa">
                    <div className="pending-heading">
                      <span>In attesa</span>
                      <small>{pendingFields.length}</small>
                    </div>
                    {pendingFields.map((field) => (
                      <div
                        className={`pending-field${selectedFieldKey === field.key ? " active" : ""}`}
                        key={field.key}
                      >
                        <button
                          type="button"
                          className="pending-field-select"
                          onClick={() => chooseField(field.key)}
                        >
                          <small>{field.label}</small>
                          <strong className={valueChosenByAI(field.key) ? "has-ai-value" : ""}>
                            {valueChosenByAI(field.key) ||
                              (isProcessing ? "In attesa della selezione AI" : "Nessun valore")}
                          </strong>
                        </button>
                        <div className="pending-field-actions">
                          <button
                            type="button"
                            className="candidate-count-button"
                            disabled={!candidatesByField.get(field.key)?.length}
                            onClick={() => {
                              chooseField(field.key);
                              setCandidateField(field);
                            }}
                          >
                            {candidatesByField.get(field.key)?.length ?? 0} candidati
                          </button>
                        </div>
                      </div>
                    ))}
                  </section>
                )}
                {!showAnalysisPrompt && orderedResults.length ? (
                  <div className="results-list">
                    {orderedResults.map((result, index) => (
                    <div
                      key={result.field_key}
                      className={`result${result.field_key === selectedFieldKey ? " active" : ""}${result.confidence < 0.9 ? " low-confidence" : ""}`}
                      onClick={() => chooseResult(result)}
                    >
                      <div>
                        <small>{fieldLabel(result.field_key, fields)}</small>
                        {result.field_key === "sintesi" ? (
                          <textarea
                            key={`${result.field_key}:${result.value ?? ""}`}
                            className="result-value-input summary-value"
                            maxLength={100}
                            defaultValue={result.value || ""}
                            placeholder="In attesa dell’analisi"
                            onClick={(event) => {
                              event.stopPropagation();
                              chooseResult(result);
                            }}
                            onFocus={() => chooseResult(result)}
                            onBlur={(event) => saveResult(result, event.currentTarget.value)}
                          />
                        ) : (
                          <input
                            key={`${result.field_key}:${result.value ?? ""}`}
                            className="result-value-input"
                            defaultValue={result.value || ""}
                            placeholder="In attesa dell’analisi"
                            onClick={(event) => {
                              event.stopPropagation();
                              chooseResult(result);
                            }}
                            onFocus={() => chooseResult(result)}
                            onBlur={(event) => saveResult(result, event.currentTarget.value)}
                            onKeyDown={(event) => {
                              if (event.key === "Enter") event.currentTarget.blur();
                            }}
                          />
                        )}
                        {(() => {
                          const field = fields.find((item) => item.key === result.field_key);
                          const count = candidatesByField.get(result.field_key)?.length ?? 0;
                          return field ? (
                            <button
                              type="button"
                              className="candidate-count-button"
                              disabled={!count}
                              onClick={(event) => {
                                event.stopPropagation();
                                setCandidateField(field);
                              }}
                            >
                              {count} candidati
                            </button>
                          ) : null;
                        })()}
                      </div>
                      <span className="score" title="Confidenza globale">
                        {Math.round(result.confidence * 100)}%
                      </span>
                      <p>{result.evidence}</p>
                      <em>
                        {result.page_number ? `Pag. ${result.page_number}` : "Pagina n/d"} · #{index + 1}
                      </em>
                    </div>
                    ))}
                  </div>
                ) : pendingFields.length === 0 ? (
                <div className="column-empty">
                  <ScanText size={22} />
                  <strong>{isProcessing ? "Analisi in corso" : "Nessun campo ancora"}</strong>
                  <span>
                    {isProcessing
                      ? "I dati appariranno qui man mano che la pipeline li consolida."
                      : "Avvia l’analisi per estrarre i campi dal documento."}
                  </span>
                </div>
                ) : null}
              </div>
            </section>

            <section className="center-column" aria-label="Visualizzatore PDF">
              <div className="viewer-toolbar">
                <div className="viewer-tabs" role="tablist" aria-label="Versione del documento">
                  <button
                    className={viewerTab === "original" ? "active" : ""}
                    onClick={() => setViewerTab("original")}
                    role="tab"
                    aria-selected={viewerTab === "original"}
                  >
                    Originale
                  </button>
                  <button
                    className={viewerTab === "optimized" ? "active" : ""}
                    onClick={() => setViewerTab("optimized")}
                    role="tab"
                    aria-selected={viewerTab === "optimized"}
                  >
                    Ottimizzato
                  </button>
                </div>
                <span className="viewer-page-count">
                  {detail.page_count ? `${detail.page_count} pagine` : "PDF"}
                </span>
              </div>
              <div className="viewer-content">
                <PageViewer
                  key={`${detail.id}-${viewerTab}`}
                  documentUrl={
                    viewerTab === "original"
                      ? `/api/documents/${detail.id}/file`
                      : `/api/documents/${detail.id}/optimized-file`
                  }
                  currentPage={pageNumber ?? 1}
                  totalPages={detail.page_count}
                  onPageChange={setPageNumber}
                  reviewBox={
                    viewerTab === "optimized" && selectedEvidencePage === (pageNumber ?? 1)
                      ? selectedEvidenceBox
                      : undefined
                  }
                  reviewLabel={selectedFieldKey}
                  reviewConfidence={selectedEvidenceConfidence}
                />
              </div>
            </section>

            <PipelineLog detail={detail} memory={memory} showAnalysisPrompt={showAnalysisPrompt} />
          </div>
        )}
      </main>
      {candidateField && (
        <div className="rules-dialog-backdrop" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setCandidateField(undefined);
        }}>
          <section
            className="rules-dialog candidate-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="candidate-dialog-title"
          >
            <div className="rules-dialog-heading">
              <div>
                <span>Candidati estratti · {candidatesByField.get(candidateField.key)?.length ?? 0}</span>
                <h2 id="candidate-dialog-title">{candidateField.label}</h2>
              </div>
              <button ref={candidateCloseRef} type="button" className="rules-close" onClick={() => setCandidateField(undefined)} aria-label="Chiudi dialog">
                <X size={18} />
              </button>
            </div>
            <div className="rules-dialog-content candidate-list">
              {(() => {
                const fieldCandidates = candidatesByField.get(candidateField.key) ?? [];
                const resolved = memory?.resolved_fields.find((item) => item.field_key === candidateField.key);
                const selectedId = resolved?.selected_candidate_id;
                const orderedCandidates = [...fieldCandidates].sort((left, right) => {
                  return right.ocr_confidence - left.ocr_confidence ||
                    right.vision_confidence - left.vision_confidence ||
                    right.semantic_confidence - left.semantic_confidence ||
                    left.id - right.id;
                });
                return orderedCandidates.length ? orderedCandidates.map((candidate, index) => {
                  const selected = selectedId
                    ? selectedId === candidate.id
                    : candidate.selected;
                  return (
                    <details className={`candidate-option${selected ? " selected" : ""}`} key={candidate.id} open={selected || index === 0}>
                      <summary className="candidate-option-summary">
                        <div className="candidate-option-heading">
                          <strong>#{index + 1} · {candidate.raw_value}</strong>
                          <span className="candidate-badges">
                            {index === 0 && <span className="candidate-top-badge">OCR più alta</span>}
                            {selected && <span className="candidate-selected-badge">Scelto</span>}
                          </span>
                        </div>
                        <div className="candidate-meta">
                          <span>Pag. {candidate.page_number}</span>
                          {candidate.semantic_role && <span>{candidate.semantic_role}</span>}
                        </div>
                        <span className="candidate-summary-relevance">
                          Rilevanza {Math.round(candidate.global_relevance * 100)}%
                        </span>
                      </summary>
                      <div className="candidate-expanded">
                        <div className="candidate-relevance-tile">
                          <span>Rilevanza effettiva</span>
                          <strong>{Math.round(candidate.global_relevance * 100)}%</strong>
                          <small>
                            {candidate.relevance_source === "global_cluster"
                              ? "Punteggio globale del gruppo, con riscontri e relazioni tra campi."
                              : "Punteggio del candidato: 75% semantica e 25% OCR."}
                          </small>
                        </div>
                        <div className="candidate-score-details">
                          <span>Semantica {Math.round(candidate.semantic_confidence * 100)}%</span>
                          <span>OCR {Math.round(candidate.ocr_confidence * 100)}%</span>
                          <span>Visione {Math.round(candidate.vision_confidence * 100)}%</span>
                        </div>
                        {candidate.evidence_text && <p>{candidate.evidence_text}</p>}
                        <button
                          type="button"
                          className="candidate-select-button"
                          disabled={isProcessing || savingCandidateId !== undefined || selected}
                          onClick={() => void chooseCandidate(candidateField, candidate.id, candidate.raw_value)}
                        >
                          {savingCandidateId === candidate.id ? "Salvataggio…" : selected ? "Candidato selezionato" : "Scegli questo candidato"}
                        </button>
                      </div>
                    </details>
                  );
                }) : (
                <div className="candidate-empty">Nessun candidato disponibile per questo campo.</div>
                );
              })()}
            </div>
          </section>
        </div>
      )}
      {settingsOpen && (
        <SettingsDialog
          fields={settingsFields}
          saving={settingsSaving}
          error={settingsError}
          onClose={() => setSettingsOpen(false)}
          onSave={(updatedFields) => void saveSettings(updatedFields)}
        />
      )}
    </div>
  );
}
