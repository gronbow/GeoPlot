import type { InspectResult, RecipeReview, ReviewTask } from "../types/desktop";

export const TOP_CONFIRMATIONS = [
  "input_structure_reviewed",
  "column_mapping_reviewed",
  "units_reviewed",
  "plotted_data_export_reviewed",
] as const;

export const CONFIRMATION_LABELS: Record<string, string> = {
  input_structure_reviewed: "I reviewed the input structure and selected layout.",
  column_mapping_reviewed: "I reviewed every sample, group, and analyte mapping.",
  units_reviewed: "I reviewed every declared unit; none were inferred silently.",
  plotted_data_export_reviewed: "I understand plotted source values may be exported locally.",
  data_basis_reviewed: "I reviewed the exact analytes used for anhydrous normalization.",
  data_quality_reviewed: "I reviewed the data-health counts shown above.",
  volcanic_samples: "I confirm these are volcanic samples for this classification.",
  composition_basis_reviewed: "I reviewed the composition basis for this task.",
};

export interface ReviewDraft {
  sampleId: string;
  group: string;
  mapping: Record<string, string>;
  units: Record<string, string>;
  confirmations: Record<string, boolean>;
  selected: Record<string, boolean>;
  parameters: Record<string, Record<string, unknown>>;
  taskConfirmations: Record<string, Record<string, boolean>>;
  reportProfile: "shareable" | "local-reproducible";
}

function suggestionArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

export function initialReviewDraft(result: InspectResult): ReviewDraft {
  const mapping = { ...(result.mapping_suggestions ?? {}) };
  const units: Record<string, string> = {};
  for (const analyte of result.recognized_analytes) {
    if (
      mapping[analyte.canonical] === analyte.source_column &&
      analyte.unit_status === "confirmed_from_header" &&
      typeof analyte.explicit_unit === "string"
    ) {
      units[analyte.canonical] = analyte.explicit_unit;
    }
  }
  const parameters: ReviewDraft["parameters"] = {};
  const taskConfirmations: ReviewDraft["taskConfirmations"] = {};
  for (const candidate of result.figure_candidates) {
    parameters[candidate.diagram] = {};
    if (candidate.diagram === "ree" || candidate.diagram === "spider") {
      parameters[candidate.diagram].elements = suggestionArray(candidate.suggestions.elements);
      parameters[candidate.diagram].reference = "";
    }
    if (candidate.diagram === "harker") {
      parameters.harker.x = candidate.suggestions.x ?? "";
      parameters.harker.y = suggestionArray(candidate.suggestions.y);
    }
    if (candidate.diagram === "tas" || candidate.diagram === "k2o-sio2") {
      parameters[candidate.diagram].composition_basis = "";
    }
    if (candidate.diagram === "xy") {
      parameters.xy.x = "";
      parameters.xy.y = "";
    }
    taskConfirmations[candidate.diagram] = Object.fromEntries(
      candidate.required_confirmations.map((name) => [name, false]),
    );
  }
  return {
    sampleId: result.sample_column_suggestion ?? "",
    group:
      result.group_column_candidates.length === 1 ? result.group_column_candidates[0] : "",
    mapping,
    units,
    confirmations: Object.fromEntries(TOP_CONFIRMATIONS.map((name) => [name, false])),
    selected: {},
    parameters,
    taskConfirmations,
    reportProfile: "shareable",
  };
}

function taskFor(diagram: string, draft: ReviewDraft): ReviewTask | null {
  const parameters = draft.parameters[diagram] ?? {};
  let normalized: Record<string, unknown>;
  if (diagram === "ree" || diagram === "spider") {
    normalized = {
      reference: parameters.reference,
      elements: parameters.elements,
      groups: "all",
    };
  } else if (diagram === "harker") {
    normalized = { x: parameters.x, y: parameters.y, groups: "all" };
  } else if (diagram === "tas" || diagram === "k2o-sio2") {
    normalized = { composition_basis: parameters.composition_basis, groups: "all" };
  } else if (diagram === "xy") {
    normalized = {
      x: { kind: "direct", id: parameters.x, scale: "linear" },
      y: { kind: "direct", id: parameters.y, scale: "linear" },
      groups: "all",
    };
  } else {
    return null;
  }
  return {
    id: `${diagram}-main`,
    diagram,
    stem: `figure-${diagram}`,
    preset: "review-preview",
    parameters: normalized,
    confirmations: { ...(draft.taskConfirmations[diagram] ?? {}) },
  };
}

export function reviewErrors(result: InspectResult, draft: ReviewDraft): string[] {
  const errors: string[] = [];
  if (!draft.sampleId) errors.push("Select a sample identifier column.");
  const mapped = Object.entries(draft.mapping).filter(([, source]) => Boolean(source));
  if (mapped.length === 0) errors.push("Keep at least one reviewed analyte mapping.");
  for (const [canonical] of mapped) {
    if (!draft.units[canonical]) errors.push(`Confirm the unit for ${canonical}.`);
  }
  for (const name of TOP_CONFIRMATIONS) {
    if (draft.confirmations[name] !== true) errors.push(CONFIRMATION_LABELS[name]);
  }
  const selected = result.figure_candidates.filter((candidate) => draft.selected[candidate.diagram]);
  if (selected.length === 0) errors.push("Select at least one available figure candidate.");
  for (const candidate of selected) {
    const diagram = candidate.diagram;
    if (candidate.state === "NOT_AVAILABLE" || candidate.state === "BLOCKED") {
      errors.push(`${candidate.display_name_en} is not available for the reviewed mappings.`);
      continue;
    }
    const parameters = draft.parameters[diagram] ?? {};
    if (diagram === "ree" || diagram === "spider") {
      if (!parameters.reference) errors.push(`Select the normalization reference for ${diagram}.`);
      const minimum = diagram === "ree" ? 3 : 5;
      if (suggestionArray(parameters.elements).length < minimum) {
        errors.push(`${diagram} needs at least ${minimum} reviewed elements.`);
      }
    } else if (diagram === "harker") {
      if (!parameters.x || suggestionArray(parameters.y).length === 0) {
        errors.push("Select Harker x and y variables.");
      }
    } else if (diagram === "tas" || diagram === "k2o-sio2") {
      if (!parameters.composition_basis) errors.push(`Select the composition basis for ${diagram}.`);
    } else if (diagram === "xy") {
      if (!parameters.x || !parameters.y || parameters.x === parameters.y) {
        errors.push("Select two different variables for the XY plot.");
      }
    }
    for (const name of candidate.required_confirmations) {
      if (draft.taskConfirmations[diagram]?.[name] !== true) {
        errors.push(CONFIRMATION_LABELS[name] ?? `Confirm ${name}.`);
      }
    }
  }
  const normalized = selected.some((candidate) => {
    const basis = draft.parameters[candidate.diagram]?.composition_basis;
    return basis === "anhydrous-normalized";
  });
  if (normalized && draft.confirmations.data_basis_reviewed !== true) {
    errors.push(CONFIRMATION_LABELS.data_basis_reviewed);
  }
  if (
    Object.values(result.quality).some((count) => count > 0) &&
    draft.confirmations.data_quality_reviewed !== true
  ) {
    errors.push(CONFIRMATION_LABELS.data_quality_reviewed);
  }
  return [...new Set(errors)];
}

export function buildRecipeReview(result: InspectResult, draft: ReviewDraft): RecipeReview {
  const tasks = result.figure_candidates
    .filter((candidate) => draft.selected[candidate.diagram])
    .map((candidate) => taskFor(candidate.diagram, draft))
    .filter((task): task is ReviewTask => task !== null);
  const review: RecipeReview = {
    sample_id: draft.sampleId,
    group: draft.group || null,
    mapping: Object.fromEntries(Object.entries(draft.mapping).filter(([, value]) => Boolean(value))),
    units: Object.fromEntries(
      Object.keys(draft.mapping)
        .filter((canonical) => Boolean(draft.mapping[canonical]))
        .map((canonical) => [canonical, draft.units[canonical]]),
    ),
    output_directory: "outputs/current",
    report_profile: draft.reportProfile,
    presets: {},
    confirmations: { ...draft.confirmations },
    tasks,
  };
  const normalized = tasks.some(
    (task) => task.parameters.composition_basis === "anhydrous-normalized",
  );
  if (normalized) {
    const analytes = Object.keys(review.mapping).filter((canonical) => review.units[canonical] === "wt%");
    review.data_basis = {
      operation: "normalize-to-100",
      basis: "anhydrous-100",
      analytes,
    };
  }
  return review;
}
