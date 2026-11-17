import { useEffect, useMemo, useRef } from "react";
import { Activity, Braces, Check, Circle, LoaderCircle, Play, ScanText } from "lucide-react";
import type { Audit, Detail, DocumentMemory } from "../lib/api";

type Props = { detail: Detail; memory?: DocumentMemory; showAnalysisPrompt?: boolean };
const labels: Record<string, string> = {
  INGESTION: "Acquisizione file",
  OPTIMIZATION: "Ottimizzazione PDF",
  PIPELINE: "Avvio pipeline",
  MODEL_HEALTH: "Verifica modello",
  OCR: "OCR pagina",
  PAGE_CHECKPOINT: "Analisi pagina",
  STRUCTURE: "Struttura documento",
  PLANNING: "Pianificazione",
  EXTRACTION: "Estrazione campi",
  GLOBAL_PASS: "Consolidamento globale",
  RESET: "Reset",
  INTERRUPT: "Interruzione",
  MANUAL_EDIT: "Modifica manuale",
};
const detailLabels: Record<string, string> = {
  page: "pagina",
  pages: "pagine",
  candidate_count: "candidati",
  candidates: "candidati",
  focus_fields: "campi richiesti",
  rotated_pages: "pagine ruotate",
  duration_ms: "durata ms",
  prompt_tokens: "token input",
  completion_tokens: "token output",
  populated_fields: "campi valorizzati",
  evidence_backed_fields: "campi con evidenza",
  accepted: "accettato",
  source: "fonte",
};
const details = (event: Audit) =>
  Object.entries(event.detail ?? {})
    .filter(([, v]) => ["string", "number", "boolean"].includes(typeof v))
    .slice(0, 6)
    .map(([k, v]) => `${detailLabels[k] ?? k}: ${String(v)}`)
    .join(" · ");
const narration = (event: Audit) => {
  const detail = event.detail ?? {};
  if (event.stage === "PIPELINE")
    return `Preparo la pipeline e applico le regole configurate${detail.pages ? ` alle ${detail.pages} pagine` : ""}.`;
  if (event.stage === "OPTIMIZATION")
    return "Creo il PDF di lavoro ottimizzato e normalizzo la rotazione delle pagine.";
  if (event.stage === "MODEL_HEALTH")
    return "Verifico che il modello sia disponibile prima di affidargli una revisione.";
  if (event.stage === "OCR")
    return `MiniCPM-OCR legge il PDF di lavoro${detail.page ? `, pagina ${detail.page}` : ""}.`;
  if (event.stage === "PAGE_CHECKPOINT")
    return `Consolido la Micro-Memory${detail.page ? ` della pagina ${detail.page}` : ""}: candidati, contesto e confidence.`;
  if (event.stage === "GLOBAL_PASS")
    return "Qwen sceglie tra i candidati della memoria globale; Python valida e scrive i risultati.";
  if (event.stage === "RESET")
    return "Rimuovo i risultati precedenti mantenendo PDF e OCR disponibili.";
  if (event.stage === "INTERRUPT") return "Interrompo la run al checkpoint sicuro raggiunto.";
  if (event.stage === "MANUAL_EDIT")
    return "Registro la correzione dell’operatore come valore validato manualmente.";
  return event.action;
};
const engines = (event: Audit) => {
  const python = [
    "PIPELINE",
    "OPTIMIZATION",
    "OCR",
    "PAGE_CHECKPOINT",
    "GLOBAL_PASS",
    "RESET",
    "MANUAL_EDIT",
  ].includes(event.stage);
  const localModel = event.stage === "GLOBAL_PASS";
  const pythonTask =
    event.stage === "OCR"
      ? "Python ha eseguito MiniCPM-OCR sul PDF di lavoro."
      : event.stage === "OPTIMIZATION"
        ? "Python ha ottimizzato il PDF e normalizzato le rotazioni."
      : event.stage === "PAGE_CHECKPOINT"
        ? "Python ha creato e validato candidati, contesti e confidence della Micro-Memory."
        : event.stage === "GLOBAL_PASS"
          ? "Python ha validato le scelte e scritto i valori finali."
          : event.stage === "RESET"
            ? "Python ha azzerato i dati della run conservando il documento."
            : event.stage === "MANUAL_EDIT"
              ? "Python ha registrato la correzione manuale."
              : "Python ha orchestrato e preparato la pipeline deterministica.";
  const localModelTask =
    event.stage === "GLOBAL_PASS"
      ? "Il modello locale ha selezionato i candidati secondo le regole della pipeline."
      : "Qwen locale ha selezionato i candidati dalla memoria globale.";
  return (
    <span className="engine-badges">
      {python && (
        <i className="engine python" data-tooltip={pythonTask} aria-label={pythonTask}>
          <Braces />
          PY
        </i>
      )}
      {localModel && (
        <i className="engine model" data-tooltip={localModelTask} aria-label={localModelTask}>
          MLX
        </i>
      )}
    </span>
  );
};

export function PipelineLog({ detail, memory, showAnalysisPrompt = false }: Props) {
  const feedRef = useRef<HTMLDivElement>(null);
  const events = useMemo(() => {
    if (!memory?.run) return [];
    const startedAt = new Date(memory.run.started_at).getTime();
    return (detail.audits ?? [])
      .filter((event) => new Date(event.created_at).getTime() >= startedAt)
      .slice()
      .sort((a, b) => b.id - a.id);
  }, [detail.audits, memory?.run]);
  const done = memory?.micro_memories.length ?? 0,
    total = detail.page_count || 0;
  const progress = total ? Math.min(100, Math.round((done / total) * 100)) : 0,
    running = ["PROCESSING", "QUEUED"].includes(detail.status);
  const current =
    detail.status === "QUEUED"
      ? "In attesa di avvio"
      : detail.status === "COMPLETED"
        ? "Analisi completata"
        : detail.status === "FAILED"
          ? "Pipeline interrotta"
        : detail.status === "CANCELLED"
          ? "Analisi interrotta"
          : done < total
            ? `OCR e analisi pagina ${Math.min(done + 1, total || 1)}`
            : "Consolidamento ed estrazione finale";
  useEffect(() => {
    feedRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  }, [events.length, current]);
  return (
    <aside className="pipeline-log panel" aria-live="polite">
      <div className="panel-title">
        <Activity /> Registro operativo{" "}
        <div className="panel-title-badges">
          <span className={`status ${detail.status.toLowerCase()}`}>{detail.status}</span>
          {running && (
            <span className="live-badge">
              <i />
              LIVE
            </span>
          )}
        </div>
      </div>
      <div className="pipeline-current">
        <div className={`pipeline-state ${running ? "running" : detail.status.toLowerCase()}`}>
          {running ? (
            <LoaderCircle className="spin" />
          ) : detail.status === "COMPLETED" ? (
            <Check />
          ) : (
            <Circle />
          )}
          <div>
            <small>Fase corrente</small>
            <strong>{current}</strong>
          </div>
        </div>
        <div className="progress-meta">
          <span>
            {done} di {total} pagine consolidate
          </span>
          <b>{progress}%</b>
        </div>
        <div className="progress-track">
          <span style={{ width: `${progress}%` }} />
        </div>
      </div>
      <div className="pipeline-feed" ref={feedRef}>
        {showAnalysisPrompt && (
          <div className="pipeline-empty">
            <ScanText />
            <span>Avvia un’analisi del fascicolo per estrarre campi e contenuti.</span>
          </div>
        )}
        {events.length === 0 && !showAnalysisPrompt ? (
          <div className="pipeline-empty">
            <LoaderCircle className={running ? "spin" : ""} />
            <span>
              {running
                ? "Preparazione file e inizializzazione OCR…"
                : detail.status === "CANCELLED"
                  ? "Analisi interrotta."
                  : "Nessun evento registrato."}
            </span>
          </div>
        ) : events.map((event, index) => {
            const current = index === 0 && running;
            return (
              <div className="pipeline-event" key={event.id}>
                <div className="event-rail">
                  {current ? <Play className="current-step" /> : <Check />}
                  <span />
                </div>
                <div className="event-body">
                  <div>
                    <b>{labels[event.stage] ?? event.stage}</b>
                    {engines(event)}
                    <time>{new Date(event.created_at).toLocaleTimeString("it-IT")}</time>
                  </div>
                  <p>{narration(event)}</p>
                  {event.action !== narration(event) && <blockquote>{event.action}</blockquote>}
                  {details(event) && <small>{details(event)}</small>}
                  <code>{event.agent}</code>
                </div>
              </div>
            );
          })}
      </div>
    </aside>
  );
}
