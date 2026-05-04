# Plan: Provider-Model Tree ComboBox

## Goal

Create a new `ProviderModelComboBox` class based on the existing `FilterableComboBox` that displays a hierarchical tree view of providers and their models (depth 2). The widget should support collapsing providers, filter only by model names, and show providers even when they have no matching models.

## Current Context

- **Existing widget**: `FilterableComboBox` in `src/barbaros/widgets/filterable_combobox.py`
  - Takes flat list of strings via `addItems()`
  - Uses `QListWidget` in popup
  - Simple text-based filtering

- **Data source**: `ModelManager` in `src/barbaros/model_manager.py`
  - Dict-like structure: `{provider_name: ProviderClient}`
  - `ProviderClient` has `meta: ProviderMeta` and `models: Sequence[Model]`
  - Each model has a name attribute

## Proposed Approach

1. Create new `ProviderModelTreePopup` class extending filtering logic to tree structure
2. Create new `ProviderModelComboBox` class extending `FilterableComboBox`
3. Use `QTreeWidget` instead of `QListWidget` in the popup
4. Two-layer hierarchy: Provider (parent) → Models (children)
5. Custom filtering: search applies only to model names, providers always visible
6. Handle empty model results: show provider node without children

## Step-by-Step Plan

### Step 1: Create ProviderModelTreePopup class

**File**: `src/barbaros/widgets/filterable_combobox.py`

- Add new class `ProviderModelTreePopup(QWidget)` extending popup behavior
- Use `QTreeWidget` instead of `QListWidget`
- Tree structure:
  - Top-level items: Providers (collapsible)
  - Child items: Models under each provider
- Override `apply_filter()` to:
  - Always show all providers
  - Filter models by name (case-insensitive)
  - If filter yields no models for a provider, show provider with no children
- Provider items should be expandable/collapsible with toggle arrows

### Step 2: Create Selection container

**File**: `src/barbaros/widgets/filterable_combobox.py`

- Add dataclass `ModelSelection`:
  ```python
  @dataclass
  class ModelSelection:
      provider: str  # provider name
      model: str     # model name
  ```
- This avoids delimiter issues with `/` in model names

### Step 3: Create ProviderModelComboBox class

**File**: `src/barbaros/widgets/filterable_combobox.py`

- Add new class `ProviderModelComboBox(QWidget)` extending `FilterableComboBox`
- Change signal to emit `ModelSelection` instead of `str`:
  ```python
  selectionChanged = Signal(object)  # emits ModelSelection
  ```
- Add `setModelManager(model_manager: ModelManager)` method
- In `setModelManager()`:
  - Iterate over providers in ModelManager
  - Build tree items: provider_name + child model names
  - Store provider→models mapping for selection handling
- Override selection handling:
  - When model selected, emit `ModelSelection(provider_name, model_name)`
  - Display model name in the label (with provider as tooltip)

### Step 3: Update import and exports

**File**: `src/barbaros/widgets/__init__.py`

- Add exports for new classes

### Step 4: Test integration (optional)

**File**: `src/barbaros/main_window.py`

- Replace existing `FilterableComboBox` usage with `ProviderModelComboBox` for model selection
- Connect to `ModelManager` instance

## Files Likely to Change

| File | Change |
|------|--------|
| `src/barbaros/widgets/filterable_combobox.py` | Add new classes |
| `src/barbaros/widgets/__init__.py` | Add exports |
| `src/barbaros/main_window.py` | (optional) Integrate new widget |

## UI/Behavior Details

### Tree Structure
```
▼ Ollama
    ├─ llama3
    ├─ mistral
    └── codellama
▶ OpenAI
    ├─ gpt-4
    └─ gpt-3.5-turbo
```

### Filtering Example
- User types "gpt" → only models containing "gpt" shown under each provider
- Provider without matching models shows as expanded but empty
- Clearing filter shows all providers expanded with all models

### Selection
- Single-click on model item selects it
- Selection emits signal with `ModelSelection(provider, model)` object
- Display label shows model name (tooltip shows full "provider: model")

## Risks and Tradeoffs

1. **Model selection persistence**: Need to handle restoring previous selection from settings (currently stored as "model" string)
2. **Provider collapse state**: Decide whether to persist collapse/expand state
3. **Empty providers**: Handle edge case where provider has zero models gracefully
4. **Widget sizing**: Tree widget may need different width calculations than flat list

## Tests / Validation

1. Verify tree displays correct provider→model hierarchy
2. Verify filter only searches model names, not provider names
3. Verify providers remain visible even with no matching models
4. Verify selection emits `ModelSelection` object with correct provider/model
5. Verify collapse/expand toggle works on provider items
6. Verify widget integrates with existing `ModelManager`
7. Verify model names containing `/` work correctly

# TODO

- Change filter combo box after change providers.