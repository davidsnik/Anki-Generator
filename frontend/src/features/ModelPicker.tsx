import { useEffect, useId, useState } from 'react';
import { Check, ChevronDown, Search, SlidersHorizontal } from 'lucide-react';
import type { AvailableModel, ModelStage } from '../services/models';
import './model-settings.css';

const groupNames = {
  general: 'Document and card models',
  embeddings: 'Semantic search models',
  unverified: 'Other account models · compatibility unverified',
};

/** Accessible editable combobox. Typing filters; only a selection changes preferences. */
export function ModelPicker({
  label,
  value,
  models,
  stage,
  onChange,
  disabled = false,
}: {
  label: string;
  value: string;
  models: AvailableModel[];
  stage: ModelStage | 'all';
  onChange: (id: string) => void;
  disabled?: boolean;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [active, setActive] = useState(0);
  const [custom, setCustom] = useState(false);
  const [customId, setCustomId] = useState('');
  useEffect(() => {
    if (open)
      document.getElementById(`${id}-option-${active}`)?.scrollIntoView?.({ block: 'nearest' });
  }, [active, open, id, search]);
  const selected = models.find((model) => model.id === value);
  const options = models
    .filter((model) => {
      const relevant =
        stage === 'all' ||
        (stage === 'embeddings' ? model.group !== 'general' : model.group !== 'embeddings');
      return relevant && `${model.name} ${model.id}`.toLowerCase().includes(search.toLowerCase());
    })
    .sort((a, b) => {
      const groupOrder = { general: 0, embeddings: 1, unverified: 2 };
      return (
        groupOrder[a.group] - groupOrder[b.group] ||
        Number(a.available === false) - Number(b.available === false) ||
        Number(b.recommended_for.includes(stage)) - Number(a.recommended_for.includes(stage)) ||
        a.name.localeCompare(b.name)
      );
    });
  const canChoose = (model: AvailableModel) =>
    model.available !== false && (stage === 'all' || model.compatibility[stage] !== 'unsupported');
  const choose = (model: AvailableModel) => {
    if (!canChoose(model)) return;
    onChange(model.id);
    setOpen(false);
    setSearch('');
  };
  const move = (direction: number) => {
    if (!open) {
      setOpen(true);
      setActive(direction > 0 ? 0 : Math.max(0, options.length - 1));
      return;
    }
    setActive((current) => Math.max(0, Math.min(options.length - 1, current + direction)));
  };
  const compatibility = (model: AvailableModel) =>
    stage === 'all' ? 'supported' : model.compatibility[stage];
  const invalid =
    selected?.available === false || (selected && compatibility(selected) === 'unsupported');
  return (
    <div className="model-picker">
      <label htmlFor={id}>{label}</label>
      <div
        className="model-picker-anchor"
        onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
        }}
      >
        <div className={`model-picker-input ${invalid ? 'invalid' : ''}`}>
          <Search size={16} aria-hidden="true" />
          <input
            id={id}
            role="combobox"
            aria-autocomplete="list"
            aria-expanded={open}
            aria-controls={`${id}-options`}
            aria-activedescendant={open && options[active] ? `${id}-option-${active}` : undefined}
            aria-describedby={`${id}-help`}
            autoComplete="off"
            disabled={disabled}
            value={open ? search : selected?.name || value}
            placeholder="Search available models…"
            onFocus={() => {
              setOpen(true);
              setSearch('');
              setActive(0);
            }}
            onClick={() => {
              if (!open) {
                setOpen(true);
                setSearch('');
                setActive(0);
              }
            }}
            onChange={(event) => {
              setSearch(event.target.value);
              setActive(0);
              setOpen(true);
            }}
            onKeyDown={(event) => {
              if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault();
                move(event.key === 'ArrowDown' ? 1 : -1);
              } else if (event.key === 'Enter' && open) {
                event.preventDefault();
                if (options[active]) choose(options[active]);
              } else if (event.key === 'Escape') {
                event.preventDefault();
                setOpen(false);
                setSearch('');
              } else if (open && (event.key === 'Home' || event.key === 'End')) {
                event.preventDefault();
                setActive(event.key === 'Home' ? 0 : Math.max(0, options.length - 1));
              }
            }}
          />
          <button
            type="button"
            className="icon-button"
            aria-label={`${open ? 'Close' : 'Show'} ${label.toLowerCase()} options`}
            disabled={disabled}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => {
              setOpen(!open);
              setSearch('');
              setActive(0);
            }}
          >
            <ChevronDown size={16} />
          </button>
        </div>
        {open && (
          <div
            id={`${id}-options`}
            role="listbox"
            aria-label={`${label} models`}
            className="model-picker-options"
          >
            {options.length === 0 && (
              <p className="model-picker-empty">
                No matching models. Try another name or use a custom model below.
              </p>
            )}
            {options.map((model, index) => (
              <div key={model.id}>
                {(index === 0 || options[index - 1].group !== model.group) && (
                  <div className="model-picker-group">{groupNames[model.group]}</div>
                )}
                <div
                  id={`${id}-option-${index}`}
                  role="option"
                  aria-selected={model.id === value}
                  aria-disabled={!canChoose(model)}
                  className={`model-picker-option ${index === active ? 'active' : ''}`}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => choose(model)}
                >
                  <span>
                    <strong>{model.name}</strong>
                    <code>{model.id}</code>
                  </span>
                  <small>
                    {model.available === false
                      ? 'Not in this account'
                      : compatibility(model) === 'unsupported'
                        ? 'Incompatible with this task'
                        : compatibility(model) !== 'supported'
                          ? 'Compatibility unverified'
                          : stage === 'all'
                            ? 'Account model'
                            : model.recommended_for.includes(stage)
                              ? 'Recommended'
                              : 'Supported'}
                  </small>
                  {model.id === value && <Check size={15} aria-hidden="true" />}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      <p id={`${id}-help`} className={`field-help ${invalid ? 'model-warning' : ''}`}>
        {value && <code>{value}</code>}
        {invalid
          ? 'This selection is unavailable or incompatible. Choose another model before processing.'
          : !selected && value
            ? 'Saved custom model. Compatibility will be checked before processing.'
            : selected && compatibility(selected) === 'unknown'
              ? 'This model’s task compatibility is unverified.'
              : null}
      </p>
      <button
        type="button"
        className="text-link model-custom-toggle"
        aria-expanded={custom}
        onClick={() => {
          setCustom(!custom);
          setCustomId(value);
        }}
      >
        <SlidersHorizontal size={12} /> {custom ? 'Hide custom model' : 'Advanced: custom model'}
      </button>
      {custom && (
        <div className="model-custom">
          <p className="field-help">
            Use an exact model ID for a new or account-specific model. Unknown capabilities stay
            unverified; availability is checked before processing.
          </p>
          <label htmlFor={`${id}-custom`}>Custom model ID</label>
          <div className="inline-actions">
            <input
              id={`${id}-custom`}
              value={customId}
              maxLength={200}
              autoComplete="off"
              placeholder="Exact model identifier"
              onChange={(event) => setCustomId(event.target.value)}
            />
            <button
              type="button"
              className="button small"
              disabled={!customId.trim() || /\s/.test(customId.trim())}
              onClick={() => {
                onChange(customId.trim());
                setOpen(false);
                setCustom(false);
              }}
            >
              Use model
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
