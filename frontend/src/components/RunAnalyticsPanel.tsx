import { useEffect, useState } from "react";
import { BarChart3, Clock3, Coins, FileText, ScanEye } from "lucide-react";
import { api, type Document, type RunAnalytics } from "../lib/api";

const integer = new Intl.NumberFormat("it-IT");
const duration = (milliseconds: number | null) => {
  if (milliseconds === null) return "In corso";
  const seconds = Math.round(milliseconds / 1000),
    minutes = Math.floor(seconds / 60);
  return minutes ? `${minutes}m ${seconds % 60}s` : `${seconds}s`;
};
const phaseLabel = (phase: string) =>
  phase.replace(/^global_/, "Selezione globale: ").replaceAll("_", " ");

type AnalyticsRun = RunAnalytics & { document_id: string; filename: string };

export function RunAnalyticsPanel({
  documents,
  refreshKey,
}: {
  documents: Document[];
  refreshKey: string;
}) {
  const [runs, setRuns] = useState<AnalyticsRun[]>([]),
    [selected, setSelected] = useState(""),
    [documentFilter, setDocumentFilter] = useState("all"),
    [mode, setMode] = useState<"file" | "page">("file"),
    [error, setError] = useState("");
  useEffect(() => {
    Promise.all(
      documents.map(async (document) =>
        (await api.runAnalytics(document.id)).map((run) => ({
          ...run,
          document_id: document.id,
          filename: document.filename,
        })),
      ),
    )
      .then((groups) => {
        const data = groups
          .flat()
          .sort((a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime());
        setRuns(data);
        setSelected((current) =>
          data.some((item) => item.run_id === current) ? current : data[0]?.run_id || "",
        );
      })
      .catch((reason) => setError(String(reason)));
  }, [documents, refreshKey]);
  const filtered =
    documentFilter === "all" ? runs : runs.filter((item) => item.document_id === documentFilter);
  const run = filtered.find((item) => item.run_id === selected) ?? filtered[0];
  const completed = runs.filter((item) => item.duration_ms !== null && item.page_count > 0);
  const totalPages = completed.reduce((sum, item) => sum + item.page_count, 0);
  const averagePageMs = totalPages
    ? completed.reduce((sum, item) => sum + (item.duration_ms ?? 0), 0) / totalPages
    : null;
  const totalTokens = runs.reduce((sum, item) => sum + item.total_tokens, 0);
  return (
    <section className="run-analytics panel">
      <div className="panel-title">
        <BarChart3 /> Usage pipeline <span>{runs.length} run</span>
      </div>
      <div className="usage-summary">
        <div>
          <Clock3 />
          <small>Tempo medio globale / pagina</small>
          <b>{averagePageMs === null ? "—" : duration(averagePageMs)}</b>
        </div>
        <div>
          <Coins />
          <small>Token complessivi</small>
          <b>{integer.format(totalTokens)}</b>
        </div>
        <div>
          <FileText />
          <small>Pagine complessive</small>
          <b>{integer.format(totalPages)}</b>
        </div>
      </div>
      <div className="usage-document-filter">
        <label>
          Documento
          <select
            value={documentFilter}
            onChange={(event) => {
              setDocumentFilter(event.target.value);
              setSelected("");
            }}
          >
            <option value="all">Tutti i documenti</option>
            {documents.map((document) => (
              <option key={document.id} value={document.id}>
                {document.filename}
              </option>
            ))}
          </select>
        </label>
      </div>
      {!run ? (
        <div className="empty">{error || "Nessuna run disponibile."}</div>
      ) : (
        <>
          <div className="analytics-controls">
            <label>
              Run
              <select value={run.run_id} onChange={(event) => setSelected(event.target.value)}>
                {filtered.map((item) => (
                  <option value={item.run_id} key={item.run_id}>
                    {item.filename} · {new Date(item.started_at).toLocaleString("it-IT")} ·{" "}
                    {item.status}
                  </option>
                ))}
              </select>
            </label>
            <div className="analytics-switch">
              <button className={mode === "file" ? "active" : ""} onClick={() => setMode("file")}>
                File completo
              </button>
              <button className={mode === "page" ? "active" : ""} onClick={() => setMode("page")}>
                Per pagina
              </button>
            </div>
          </div>
          <div className="analytics-cards">
            <div>
              <Clock3 />
              <small>Tempo totale</small>
              <b>{duration(run.duration_ms)}</b>
            </div>
            <div>
              <Coins />
              <small>Token totali</small>
              <b>{integer.format(run.total_tokens)}</b>
              <em>
                {integer.format(run.prompt_tokens)} input · {integer.format(run.completion_tokens)}{" "}
                output
              </em>
            </div>
            <div>
              <FileText />
              <small>Pagine elaborate</small>
              <b>{run.page_count}</b>
            </div>
            <div>
              <ScanEye />
              <small>Pagine Vision</small>
              <b>{run.vision_pages}</b>
            </div>
            <div>
              <BarChart3 />
              <small>Candidati / campi</small>
              <b>
                {run.candidate_count} / {run.resolved_count}
              </b>
            </div>
          </div>
          <div className="analytics-table-wrap">
            <table>
              <thead>
                {mode === "file" ? (
                  <tr>
                    <th>Step</th>
                    <th>Chiamate</th>
                    <th>Tempo</th>
                    <th>Token input</th>
                    <th>Token output</th>
                    <th>Totale</th>
                  </tr>
                ) : (
                  <tr>
                    <th>Pagina</th>
                    <th>Tempo</th>
                    <th>Token input</th>
                    <th>Token output</th>
                    <th>Totale</th>
                    <th>Vision</th>
                    <th>Candidati</th>
                    <th>Review</th>
                  </tr>
                )}
              </thead>
              <tbody>
                {mode === "file"
                  ? run.phases.map((item) => (
                      <tr key={item.phase}>
                        <td>{phaseLabel(item.phase)}</td>
                        <td>{item.calls}</td>
                        <td>{duration(item.duration_ms)}</td>
                        <td>{integer.format(item.prompt_tokens)}</td>
                        <td>{integer.format(item.completion_tokens)}</td>
                        <td>{integer.format(item.prompt_tokens + item.completion_tokens)}</td>
                      </tr>
                    ))
                  : run.pages.map((item) => (
                      <tr key={item.page_number}>
                        <td>
                          <b>p. {item.page_number}</b>
                        </td>
                        <td>{duration(item.duration_ms)}</td>
                        <td>{integer.format(item.prompt_tokens)}</td>
                        <td>{integer.format(item.completion_tokens)}</td>
                        <td>{integer.format(item.total_tokens)}</td>
                        <td>{item.vision_used ? "Sì" : "No"}</td>
                        <td>{item.candidate_count}</td>
                        <td>{item.requires_review ? "Richiesta" : "—"}</td>
                      </tr>
                    ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
