import { useEffect, useState } from "react";
import { Plus, Save, Trash2, X } from "lucide-react";
import type { FieldDefinition } from "../lib/api";

type Props = {
  fields: FieldDefinition[];
  saving: boolean;
  error: string;
  onClose: () => void;
  onSave: (fields: FieldDefinition[]) => void;
};

const lines = (value: unknown) =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === "string").join("\n") : "";

export function SettingsDialog({ fields, saving, error, onClose, onSave }: Props) {
  const [draft, setDraft] = useState(fields);
  const [newKey, setNewKey] = useState("");
  const [newLabel, setNewLabel] = useState("");

  useEffect(() => setDraft(fields), [fields]);

  const updateField = (id: number, key: string, value: unknown) => {
    setDraft((current) => current.map((field) => field.id === id ? { ...field, [key]: value } : field));
  };
  const updateStrategy = (field: FieldDefinition, key: string, value: unknown) => {
    updateField(field.id, "strategy", { ...field.strategy, [key]: value });
  };
  const updateValidator = (field: FieldDefinition, key: string, value: unknown) => {
    updateField(field.id, "validator", { ...field.validator, [key]: value });
  };
  const addField = () => {
    const key = newKey.trim();
    const label = newLabel.trim();
    if (!/^[a-z][a-z0-9_]{1,79}$/.test(key) || !label || draft.some((field) => field.key === key)) return;
    setDraft((current) => [...current, {
      id: -Date.now() - draft.length,
      key,
      label,
      instructions: "",
      positive_examples: [],
      negative_examples: [],
      validator: { min_length: 1, max_length: 500 },
      ranking_rules: [],
      strategy: { type: "text", keywords: [], pattern: "", allowed_roles: [], candidate_role: "SCONOSCIUTO" },
      enabled: true,
    }]);
    setNewKey("");
    setNewLabel("");
  };

  return (
    <div className="rules-dialog-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="rules-dialog settings-dialog" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <div className="rules-dialog-heading">
          <div>
            <span>Configurazione permanente</span>
            <h2 id="settings-title">Campi e regole della pipeline</h2>
          </div>
          <button type="button" className="rules-close" onClick={onClose} aria-label="Chiudi impostazioni">
            <X size={18} />
          </button>
        </div>
        <div className="rules-dialog-content settings-content">
          <p>Le modifiche vengono salvate e usate nelle elaborazioni successive. Disattiva un campo per escluderlo dall’estrazione.</p>
          {draft.map((field) => (
            <details className={`settings-field${field.enabled ? " enabled" : " disabled"}`} key={field.id}>
              <summary>
                <span className="settings-field-state" aria-hidden="true" />
                <strong>{field.label || field.key}</strong>
                <small>{field.key}</small>
              </summary>
              <div className="settings-field-content">
                <label className="settings-enabled">
                  <input type="checkbox" checked={field.enabled} onChange={(event) => updateField(field.id, "enabled", event.target.checked)} />
                  Estrai questo campo
                </label>
                <label>Nome visibile
                  <input value={field.label} onChange={(event) => updateField(field.id, "label", event.target.value)} />
                </label>
                <label>Istruzioni e criteri di scelta
                  <textarea value={field.instructions} onChange={(event) => updateField(field.id, "instructions", event.target.value)} rows={3} placeholder="Spiega quale occorrenza scegliere e quali escludere." />
                </label>
                <label>Parole chiave, una per riga
                  <textarea value={lines(field.strategy.keywords)} onChange={(event) => updateStrategy(field, "keywords", event.target.value.split("\n").map((item) => item.trim()).filter(Boolean))} rows={2} />
                </label>
                <label>Pattern di estrazione
                  <textarea value={String(field.strategy.pattern ?? "")} onChange={(event) => updateStrategy(field, "pattern", event.target.value)} rows={2} placeholder="Usa un gruppo nominato (?P&lt;value&gt;...)." />
                </label>
                <label>Ruoli ammessi, uno per riga
                  <textarea value={lines(field.strategy.allowed_roles)} onChange={(event) => updateStrategy(field, "allowed_roles", event.target.value.split("\n").map((item) => item.trim()).filter(Boolean))} rows={2} />
                </label>
                <label>Ruolo candidato predefinito
                  <input value={String(field.strategy.candidate_role ?? "")} onChange={(event) => updateStrategy(field, "candidate_role", event.target.value.trim())} placeholder="SCONOSCIUTO" />
                </label>
                <label>Regex di validazione del valore
                  <input value={String(field.validator.value_pattern ?? "")} onChange={(event) => updateValidator(field, "value_pattern", event.target.value)} placeholder="Lascia vuoto per usare il controllo standard." />
                </label>
                <label>Esempi positivi, uno per riga
                  <textarea value={lines(field.positive_examples)} onChange={(event) => updateField(field.id, "positive_examples", event.target.value.split("\n").map((item) => item.trim()).filter(Boolean))} rows={2} />
                </label>
                <label>Esempi da escludere, uno per riga
                  <textarea value={lines(field.negative_examples)} onChange={(event) => updateField(field.id, "negative_examples", event.target.value.split("\n").map((item) => item.trim()).filter(Boolean))} rows={2} />
                </label>
                <button type="button" className="settings-delete-field" onClick={() => setDraft((current) => current.filter((item) => item.id !== field.id))}>
                  <Trash2 size={14} /> Rimuovi campo
                </button>
              </div>
            </details>
          ))}
          <div className="settings-add-field">
            <strong>Aggiungi campo</strong>
            <div>
              <input value={newKey} onChange={(event) => setNewKey(event.target.value)} placeholder="chiave_campo" pattern="[a-z][a-z0-9_]{1,79}" aria-label="Chiave del nuovo campo" />
              <input value={newLabel} onChange={(event) => setNewLabel(event.target.value)} placeholder="Nome visibile" aria-label="Nome del nuovo campo" />
              <button type="button" onClick={addField} disabled={!/^[a-z][a-z0-9_]{1,79}$/.test(newKey.trim()) || !newLabel.trim() || draft.some((field) => field.key === newKey.trim())}>
                <Plus size={15} /> Aggiungi
              </button>
            </div>
          </div>
          {error && <div className="settings-error">{error}</div>}
        </div>
        <div className="settings-footer">
          <button type="button" className="settings-cancel" onClick={onClose} disabled={saving}>Annulla</button>
          <button type="button" className="primary" onClick={() => onSave(draft)} disabled={saving || !draft.length}>
            <Save size={15} /> {saving ? "Salvataggio…" : "Salva modifiche"}
          </button>
        </div>
      </section>
    </div>
  );
}
