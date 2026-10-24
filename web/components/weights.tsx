"use client";

import { useEffect, useState } from "react";
import { send, useApi } from "@/lib/api";
import { Button } from "./ui";

const LABELS: Record<string, string> = {
  dc: "Drive file created",
  de: "Drive file edited",
  dv: "Drive file viewed",
  es: "Email sent",
  er: "Email received",
  mt: "Meet call",
  mh: "Meet hour",
  ch: "Chat message",
  cal: "Calendar event created",
};

/** Editable activity score weights (stored per tenant in score_weights). */
export function WeightsEditor({ onSaved }: { onSaved: () => void }) {
  const { data } = useApi<{ weights: Record<string, number>; defaults: Record<string, number> }>("/weights", { refreshInterval: 0, revalidateOnFocus: false });
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (data) setDraft(Object.fromEntries(Object.entries(data.weights).map(([k, v]) => [k, String(v)])));
  }, [data]);

  if (!data) return null;

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await send("/weights", "PUT", { weights: Object.fromEntries(Object.entries(draft).map(([k, v]) => [k, Number(v)])) });
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mb-5 rounded-lg border border-line bg-surface-2/50 p-4">
      <p className="mb-3 text-sm text-ink-2">Daily score = Σ count × weight. Changes apply to every grid and ranking.</p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {Object.keys(LABELS).map((k) => (
          <label key={k} className="flex items-center justify-between gap-2 text-sm">
            <span className="text-ink-2">{LABELS[k]}</span>
            <input
              type="number"
              step="0.1"
              min={0}
              max={100}
              value={draft[k] ?? ""}
              onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}
              className="w-20 rounded-md border border-line bg-surface px-2 py-1 text-right tabular-nums text-ink"
              aria-label={`Weight for ${LABELS[k]}`}
            />
          </label>
        ))}
      </div>
      {error && <p className="mt-2 text-sm text-critical">{error}</p>}
      <div className="mt-3 flex gap-2">
        <Button variant="primary" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save weights"}
        </Button>
        <Button variant="ghost" onClick={() => setDraft(Object.fromEntries(Object.entries(data.defaults).map(([k, v]) => [k, String(v)])))}>
          Reset to defaults
        </Button>
      </div>
    </div>
  );
}
