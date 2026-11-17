export const FIELD_DEFINITIONS = [
  { key: "protocollo", label: "Protocollo" },
  { key: "data_protocollo", label: "Data protocollo" },
  { key: "richiedente", label: "Richiedente" },
  { key: "comune", label: "Comune" },
  { key: "odonimo", label: "Odonimo" },
  { key: "civico", label: "Numero civico" },
  { key: "foglio", label: "Foglio catastale" },
  { key: "particella", label: "Particella catastale" },
  { key: "subalterno", label: "Subalterno" },
  { key: "categoria_catastale", label: "Categoria catastale" },
  { key: "data_valutazione", label: "Data valutazione" },
  { key: "esito_valutazione", label: "Esito valutazione" },
] as const;

const labels = new Map<string, string>(FIELD_DEFINITIONS.map((field) => [field.key, field.label]));
const order = new Map<string, number>(FIELD_DEFINITIONS.map((field, index) => [field.key, index]));

type DynamicField = { key: string; label: string };

export const fieldLabel = (key: string, fields: DynamicField[] = []): string =>
  fields.find((field) => field.key === key)?.label ??
  labels.get(key) ??
  key
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");

export const fieldOrder = (key: string, fields: DynamicField[] = []): number =>
  order.get(key) ??
  FIELD_DEFINITIONS.length + Math.max(0, fields.findIndex((field) => field.key === key));
