import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "../../components/Button";
import { Dropdown, Input } from "../../components/FormControls";
import { queryKeys } from "../../query/queryKeys";
import { unitsService } from "../../services/unitsService";
import type { Unit } from "../../types/units";

const CUSTOM_VALUE = "__custom__";

// The routing graph now always proposes a primary unit (and usually an
// alternative) -- see backend app.ai.workflows.routing_graph._best_effort_
// unit -- but a human may still know better than either suggestion. This
// lets them pick any of the company's own active units, or type one that
// isn't in the list at all (a destination need not match a real `units`
// row -- see DraftModel.destination_unit_id's own docstring).
//
// Split into an outer shell (owns `open` + the units fetch) and an inner
// form (owns the selection state) so the form's own `useState` initializers
// -- which decide whether the current destination should show as a
// dropdown selection or a free-text value -- only ever run once the unit
// list has actually loaded. Mounting them together would freeze that
// decision at the first render, before the async fetch resolves, and
// permanently misclassify a real match as "custom text" instead.
export function UnitPicker({
  currentDestination,
  saving,
  onSave,
}: {
  currentDestination: string | null;
  saving: boolean;
  onSave: (destination: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const unitsQuery = useQuery({
    queryKey: queryKeys.units,
    queryFn: () => unitsService.list(),
    staleTime: 5 * 60_000,
    enabled: open,
  });

  if (!open) {
    return (
      <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
        Birimi değiştir
      </Button>
    );
  }

  if (unitsQuery.isLoading) {
    return <p className="unit-picker-loading">Birimler yükleniyor…</p>;
  }

  const units = (unitsQuery.data ?? []).filter((unit) => unit.is_active);
  return (
    <UnitPickerForm
      units={units}
      currentDestination={currentDestination}
      saving={saving}
      onSave={(destination) => {
        onSave(destination);
        setOpen(false);
      }}
      onCancel={() => setOpen(false)}
    />
  );
}

function UnitPickerForm({
  units,
  currentDestination,
  saving,
  onSave,
  onCancel,
}: {
  units: Unit[];
  currentDestination: string | null;
  saving: boolean;
  onSave: (destination: string) => void;
  onCancel: () => void;
}) {
  const currentMatchesAUnit = units.some((unit) => unit.name === currentDestination);
  const [selected, setSelected] = useState<string>(
    currentDestination && currentMatchesAUnit ? currentDestination : CUSTOM_VALUE,
  );
  const [customValue, setCustomValue] = useState(
    currentDestination && !currentMatchesAUnit ? currentDestination : "",
  );

  const pendingValue = selected === CUSTOM_VALUE ? customValue.trim() : selected;
  const isUnchanged = pendingValue === (currentDestination ?? "");

  return (
    <form
      className="unit-picker form-stack"
      onSubmit={(event) => {
        event.preventDefault();
        if (!pendingValue || isUnchanged) return;
        onSave(pendingValue);
      }}
    >
      <Dropdown
        label="Hedef birim"
        controlSize="sm"
        value={selected}
        onChange={(event) => setSelected(event.target.value)}
      >
        {units.map((unit) => (
          <option key={unit.id} value={unit.name}>
            {unit.name}
          </option>
        ))}
        <option value={CUSTOM_VALUE}>Diğer birim…</option>
      </Dropdown>
      {selected === CUSTOM_VALUE && (
        <Input
          label="Birim adı"
          controlSize="sm"
          value={customValue}
          onChange={(event) => setCustomValue(event.target.value)}
          placeholder="Örn. Basın ve Halkla İlişkiler"
          autoFocus
        />
      )}
      <div className="unit-picker-actions">
        <Button type="button" variant="ghost" size="sm" disabled={saving} onClick={onCancel}>
          Vazgeç
        </Button>
        <Button type="submit" size="sm" loading={saving} disabled={saving || !pendingValue || isUnchanged}>
          Kaydet
        </Button>
      </div>
    </form>
  );
}
