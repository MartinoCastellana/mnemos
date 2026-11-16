import { useMemo, useState } from "react";
import { Database } from "lucide-react";
import { fieldLabel } from "../lib/fields";
import type { DocumentMemory } from "../lib/api";

const percent = (value: number) => `${Math.round(value * 100)}%`;
type Tab = "finali" | "candidati" | "micro" | "cluster" | "relazioni";

export function DocumentMemoryPanel({
  memory,
  onNavigate,
  onSave,
}: {
  memory?: DocumentMemory;
  onNavigate: (page: number) => void;
  onSave: (fieldKey: string, value: string) => void;
}) {
  const [tab, setTab] = useState<Tab>("finali");
  const candidates = useMemo(
    () => new Map(memory?.candidates.map((item) => [item.id, item.raw_value]) ?? []),
    [memory],
  );
  if (!memory?.run || memory.run.status !== "COMPLETED") return null;
  const tabs: Array<[Tab, string, number]> = [
    ["finali", "Valori scelti", memory.resolved_fields.length],
    ["candidati", "Valori estratti", memory.candidates.length],
    ["micro", "Micro-Memory", memory.micro_memories.length],
    ["cluster", "Entity cluster", memory.entity_clusters.length],
    ["relazioni", "Relazioni", memory.relationships.length],
  ];
  return (
    <section className="memory panel">
      <div className="memory-title">
        <Database /> Tabelle della memoria documentale{" "}
        <span>Run {memory.run.id.slice(0, 8)} · COMPLETATA</span>
      </div>
      <nav className="memory-tabs">
        {tabs.map(([key, label, count]) => (
          <button key={key} className={tab === key ? "active" : ""} onClick={() => setTab(key)}>
            {label}
            <b>{count}</b>
          </button>
        ))}
      </nav>
      <div className="memory-tab-content">
        {tab === "finali" && (
          <div className="memory-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Campo</th>
                  <th>Valore finale</th>
                  <th>Confidence globale</th>
                  <th>Pagina</th>
                  <th>Motivazione</th>
                  <th>Revisione</th>
                </tr>
              </thead>
              <tbody>
                {memory.resolved_fields.map((item) => (
                  <tr key={item.field_key}>
                    <td>{fieldLabel(item.field_key)}</td>
                    <td>
                      <input
                        className="memory-value-input"
                        defaultValue={item.value || ""}
                        onBlur={(event) => onSave(item.field_key, event.currentTarget.value)}
                      />
                    </td>
                    <td>{percent(item.confidence)}</td>
                    <td>
                      {item.source_page ? (
                        <button
                          className="memory-page-link"
                          onClick={() => onNavigate(item.source_page!)}
                        >
                          {item.source_page}
                        </button>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>{item.selection_reason.join(" · ")}</td>
                    <td>{item.requires_review ? "Richiesta" : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {tab === "candidati" && (
          <div className="memory-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Campo</th>
                  <th>Valore estratto</th>
                  <th>Ruolo</th>
                  <th>Fonte</th>
                  <th>Pagina</th>
                  <th>OCR</th>
                  <th>Vision</th>
                  <th>Semantica</th>
                  <th>Scelta</th>
                </tr>
              </thead>
              <tbody>
                {memory.candidates.map((item) => (
                  <tr key={item.id} className={item.selected ? "selected" : ""}>
                    <td>{fieldLabel(item.field_key)}</td>
                    <td>
                      <button
                        className="memory-value-link"
                        onClick={() => onNavigate(item.page_number)}
                      >
                        {item.raw_value}
                      </button>
                    </td>
                    <td>{item.semantic_role}</td>
                    <td>
                      {item.source_engine}
                      <small>{item.chunk_id}</small>
                    </td>
                    <td>
                      <button
                        className="memory-page-link"
                        onClick={() => onNavigate(item.page_number)}
                      >
                        {item.page_number}
                      </button>
                    </td>
                    <td>{percent(item.ocr_confidence)}</td>
                    <td>{percent(item.vision_confidence)}</td>
                    <td>{percent(item.semantic_confidence)}</td>
                    <td>
                      {item.selected ? (
                        <span className="chosen">Scelto</span>
                      ) : (
                        item.rejection_reason || "Candidato"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {tab === "micro" && (
          <div className="memory-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Pagina</th>
                  <th>Documento</th>
                  <th>Tipo pagina</th>
                  <th>Confidence tipo</th>
                  <th>Continuità</th>
                  <th>Nuovo documento</th>
                  <th>Sintesi</th>
                  <th>Candidati</th>
                  <th>Revisione</th>
                </tr>
              </thead>
              <tbody>
                {memory.micro_memories.map((item) => (
                  <tr key={item.page_number}>
                    <td>
                      <b>{item.page_number}</b>
                    </td>
                    <td>
                      {item.document_assignment}
                      <small>{item.document_type}</small>
                    </td>
                    <td>{item.page_type}</td>
                    <td>{percent(item.page_type_confidence)}</td>
                    <td>{percent(item.continuation_confidence)}</td>
                    <td>
                      {item.starts_new_document ? "Sì" : "No"}
                      <small>{percent(item.new_document_confidence)}</small>
                    </td>
                    <td>{item.page_summary || "—"}</td>
                    <td>{item.entity_candidates.length}</td>
                    <td>{item.requires_review ? "Richiesta" : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {tab === "cluster" && (
          <div className="memory-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Campo</th>
                  <th>Entità consolidata</th>
                  <th>Ruolo semantico</th>
                  <th>Pagine</th>
                  <th>Documenti</th>
                  <th>Confidence globale</th>
                </tr>
              </thead>
              <tbody>
                {memory.entity_clusters.map((item) => (
                  <tr key={item.id}>
                    <td>{fieldLabel(item.field_key)}</td>
                    <td>
                      <b>{item.representative_value}</b>
                    </td>
                    <td>{item.semantic_role}</td>
                    <td>{item.page_numbers.join(", ")}</td>
                    <td>{item.document_assignments.join(", ")}</td>
                    <td>{percent(item.global_confidence)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {tab === "relazioni" && (
          <div className="memory-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Relazione</th>
                  <th>Origine</th>
                  <th>Destinazione</th>
                  <th>Pagina</th>
                  <th>Confidenza</th>
                  <th>Evidenza</th>
                </tr>
              </thead>
              <tbody>
                {memory.relationships.map((item) => (
                  <tr key={item.id}>
                    <td>{item.relation_type}</td>
                    <td>
                      {candidates.get(item.source_candidate_id) || `#${item.source_candidate_id}`}
                    </td>
                    <td>
                      {candidates.get(item.target_candidate_id) || `#${item.target_candidate_id}`}
                    </td>
                    <td>{item.page_number || "—"}</td>
                    <td>{percent(item.confidence)}</td>
                    <td>{item.evidence}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
