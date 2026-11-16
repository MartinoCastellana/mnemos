import { useEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle2,
  ChevronRight,
  ArrowRightLeft,
  FileSearch,
  BookOpenText,
  LoaderCircle,
  RotateCcw,
  ScanText,
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
    [selectedResult, setSelectedResult] = useState<Result>(),
    [rulesField, setRulesField] = useState<FieldDefinition>(),
    [candidateField, setCandidateField] = useState<FieldDefinition>(),
    [savingCandidateId, setSavingCandidateId] = useState<number>(),
    [pageNumber, setPageNumber] = useState<number>(),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [documentsOpen, setDocumentsOpen] = useState(false),
    [viewerTab, setViewerTab] = useState<ViewerTab>("original"),
    [localRunStartedAt, setLocalRunStartedAt] = useState<number>(),
    [elapsedSeconds, setElapsedSeconds] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const rulesCloseRef = useRef<HTMLButtonElement>(null);
  const progressRef = useRef("");
  const activeDocumentRef = useRef<string | undefined>(undefined);
  const displayedDocumentRef = useRef<string | undefined>(undefined);
  const refreshRequestRef = useRef(0);
  const batchIsProcessing = documents.some((doc) => ["PROCESSING", "QUEUED"].includes(doc.status));
  const isProcessing = detail?.status === "PROCESSING" || detail?.status === "QUEUED";
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
        if (documentChanged) setSelectedResult(undefined);
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
    setSelectedResult(undefined);
    setPageNumber(undefined);
    setMemory(undefined);
    setDetail(undefined);
    setViewerTab("original");
    setLocalRunStartedAt(undefined);
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
    if (!rulesField) return;
    rulesCloseRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setRulesField(undefined);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [rulesField]);
  useEffect(() => {
    if (!candidateField) return;
    rulesCloseRef.current?.focus();
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
  const candidatesByField = useMemo(() => {
    const grouped = new Map<string, NonNullable<DocumentMemory>["candidates"]>();
    for (const candidate of memory?.candidates ?? []) {
      const candidates = grouped.get(candidate.field_key) ?? [];
      candidates.push(candidate);
      grouped.set(candidate.field_key, candidates);
    }
    return grouped;
  }, [memory?.candidates]);
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
  const process = async () => {
    if (!detail || isProcessing) return;
    setBusy(true);
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
      setSelectedResult(undefined);
      setPageNumber(undefined);
      setViewerTab("original");
      setLocalRunStartedAt(undefined);
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
    setSelectedResult(result);
    if (result.page_number) navigateToPage(result.page_number);
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
          <ScanText />
          <strong>Mnemos</strong>
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
          {detail && (
            <button
              className="reset-all-button"
              onClick={() => void resetEverything()}
              disabled={isProcessing || busy}
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
          {detail && (
            <button
              className={`primary analyze-button${isProcessing ? " analyzing" : ""}`}
              onClick={process}
              disabled={busy || isProcessing}
              aria-label={isProcessing ? "Analisi in corso" : "Analizza documento"}
            >
              {isProcessing ? (
                <>
                  <LoaderCircle className="spin" size={17} />
                  <span className="analyze-label">Analisi in corso</span>
                </>
              ) : detail.status === "COMPLETED" || detail.status === "FAILED" ? (
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
          )}
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
                {pendingFields.length > 0 && (
                  <section className="pending-fields" aria-label="Campi in attesa">
                    <div className="pending-heading">
                      <span>In attesa</span>
                      <small>{pendingFields.length}</small>
                    </div>
                    {pendingFields.map((field) => (
                      <div className="pending-field" key={field.key}>
                        <div>
                          <strong>{field.label}</strong>
                          <small>{isProcessing ? "Estrazione in corso" : "Nessun valore"}</small>
                          <button
                            type="button"
                            className="candidate-count-button"
                            disabled={!candidatesByField.get(field.key)?.length}
                            onClick={() => setCandidateField(field)}
                          >
                            {candidatesByField.get(field.key)?.length ?? 0} candidati
                          </button>
                        </div>
                        <button
                          type="button"
                          className="rules-button"
                          onClick={() => setRulesField(field)}
                          aria-label={`Mostra le regole di estrazione per ${field.label}`}
                        >
                          <BookOpenText size={14} /> Regole
                        </button>
                      </div>
                    ))}
                  </section>
                )}
                {orderedResults.length ? (
                  <div className="results-list">
                    {orderedResults.map((result, index) => (
                    <div
                      key={result.field_key}
                      className={`result${result.field_key === selectedResult?.field_key ? " active" : ""}${result.confidence < 0.9 ? " low-confidence" : ""}`}
                      onClick={() => chooseResult(result)}
                    >
                      <div>
                        <small>{fieldLabel(result.field_key, fields)}</small>
                        {result.field_key === "sintesi" ? (
                          <textarea
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
                    viewerTab === "optimized" && selectedResult?.page_number === (pageNumber ?? 1)
                      ? selectedResult.bbox
                      : undefined
                  }
                  reviewLabel={selectedResult?.field_key}
                  reviewConfidence={selectedResult?.confidence}
                />
              </div>
            </section>

            <PipelineLog detail={detail} memory={memory} />
          </div>
        )}
      </main>
      {rulesField && (
        <div className="rules-dialog-backdrop" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setRulesField(undefined);
        }}>
          <section
            className="rules-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="rules-dialog-title"
            onKeyDown={(event) => {
              if (event.key === "Escape") setRulesField(undefined);
            }}
          >
            <div className="rules-dialog-heading">
              <div>
                <span>Regole di estrazione</span>
                <h2 id="rules-dialog-title">{rulesField.label}</h2>
              </div>
              <button ref={rulesCloseRef} type="button" className="rules-close" onClick={() => setRulesField(undefined)} aria-label="Chiudi dialog">
                <X size={18} />
              </button>
            </div>
            <div className="rules-dialog-content">
              <p>{rulesField.instructions || "Nessuna istruzione specifica configurata."}</p>
              <RuleList title="Parole chiave" values={rulesField.strategy.keywords} empty="Nessuna parola chiave configurata." />
              <RuleList title="Ruoli ammessi" values={rulesField.strategy.allowed_roles} empty="Nessun ruolo specificato." />
              <RuleList title="Regole di priorità" values={rulesField.ranking_rules.map((rule) => JSON.stringify(rule))} empty="Nessuna regola di priorità configurata." />
              <RuleList title="Esempi positivi" values={rulesField.positive_examples} empty="Nessun esempio configurato." />
              <RuleList title="Esempi da escludere" values={rulesField.negative_examples} empty="Nessun esempio configurato." />
              <div className="rule-detail">
                <strong>Validazione</strong>
                <code>{JSON.stringify({ pattern: rulesField.strategy.pattern ?? rulesField.validator.pattern, tipo: rulesField.strategy.type, profilo: rulesField.strategy.profile, ruolo_candidato: rulesField.strategy.candidate_role }, null, 2)}</code>
              </div>
            </div>
          </section>
        </div>
      )}
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
              <button ref={rulesCloseRef} type="button" className="rules-close" onClick={() => setCandidateField(undefined)} aria-label="Chiudi dialog">
                <X size={18} />
              </button>
            </div>
            <div className="rules-dialog-content candidate-list">
              {(candidatesByField.get(candidateField.key) ?? []).length ? (
                (candidatesByField.get(candidateField.key) ?? []).map((candidate, index) => {
                  const resolved = memory?.resolved_fields.find((item) => item.field_key === candidateField.key);
                  const selected = resolved
                    ? resolved.selected_candidate_id === candidate.id
                    : candidate.selected;
                  return (
                    <article className={`candidate-option${selected ? " selected" : ""}`} key={candidate.id}>
                      <div className="candidate-option-heading">
                        <strong>#{index + 1} · {candidate.raw_value}</strong>
                        {selected && <span className="candidate-selected-badge">Selezionato</span>}
                      </div>
                      <div className="candidate-meta">
                        <span>Pag. {candidate.page_number}</span>
                        <span>{Math.round(candidate.semantic_confidence * 100)}% confidenza</span>
                        {candidate.semantic_role && <span>{candidate.semantic_role}</span>}
                      </div>
                      {candidate.evidence_text && <p>{candidate.evidence_text}</p>}
                      <button
                        type="button"
                        className="candidate-select-button"
                        disabled={isProcessing || savingCandidateId !== undefined || selected}
                        onClick={() => void chooseCandidate(candidateField, candidate.id, candidate.raw_value)}
                      >
                        {savingCandidateId === candidate.id ? "Salvataggio…" : selected ? "Selezionato" : "Sostituisci con questo"}
                      </button>
                    </article>
                  );
                })
              ) : (
                <div className="candidate-empty">Nessun candidato disponibile per questo campo.</div>
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

function RuleList({ title, values, empty }: { title: string; values: unknown; empty: string }) {
  const items = Array.isArray(values) ? values.filter((value): value is string => typeof value === "string" && Boolean(value.trim())) : [];
  return (
    <div className="rule-detail">
      <strong>{title}</strong>
      {items.length ? <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul> : <span>{empty}</span>}
    </div>
  );
}
