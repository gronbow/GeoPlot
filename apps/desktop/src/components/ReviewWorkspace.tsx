import { useMemo, useState } from "react";

import type { DesktopBackend } from "../lib/backend";
import {
  CONFIRMATION_LABELS,
  TOP_CONFIRMATIONS,
  buildRecipeReview,
  initialReviewDraft,
  reviewErrors,
  type ReviewDraft,
} from "../lib/review";
import type {
  ArtifactBundle,
  DesktopReport,
  ExecutionPlan,
  FigureCandidate,
  InputLayout,
  InspectResult,
  ProjectSummary,
  RunResult,
  ScreeningResult,
} from "../types/desktop";
import { InspectSummary } from "./InspectSummary";

interface ReviewWorkspaceProps {
  backend: DesktopBackend;
  project: ProjectSummary;
  report: DesktopReport<InspectResult>;
  onProjectUpdate: (project: ProjectSummary) => void;
  onInspectionUpdate: (report: DesktopReport<InspectResult>) => void;
  onImportAnother: () => void;
  onError: (message: string) => void;
}

const candidateState: Record<string, string> = {
  AVAILABLE_AFTER_REVIEW: "Available after review",
  NEEDS_PARAMETER: "Needs parameters",
  NEEDS_SCIENTIFIC_CONFIRMATION: "Scientific confirmation required",
  NOT_AVAILABLE: "Not available",
  BLOCKED: "Blocked",
};

const qualityLabels: Record<string, string> = {
  missing_value_count: "Missing values",
  below_detection_limit_count: "Below detection",
  non_numeric_count: "Non-numeric",
  non_positive_count: "Non-positive",
  duplicate_sample_id_count: "Duplicate sample IDs",
  blank_sample_id_count: "Blank sample IDs",
  unknown_unit_count: "Unknown units",
  unit_conflict_count: "Unit conflicts",
};

function caughtMessage(caught: unknown, fallback: string): string {
  if (typeof caught === "string") return caught;
  if (caught instanceof Error && caught.message) return caught.message;
  return fallback;
}

function splitList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function ReviewWorkspace({
  backend,
  project,
  report,
  onProjectUpdate,
  onInspectionUpdate,
  onImportAnother,
  onError,
}: ReviewWorkspaceProps) {
  const [draft, setDraft] = useState<ReviewDraft>(() => initialReviewDraft(report.result));
  const [busy, setBusy] = useState(false);
  const [workflowReport, setWorkflowReport] = useState<DesktopReport<Record<string, unknown>> | null>(null);
  const [plan, setPlan] = useState<ExecutionPlan | null>(null);
  const [planReviewed, setPlanReviewed] = useState(false);
  const [replaceOutput, setReplaceOutput] = useState(false);
  const [runResult, setRunResult] = useState<RunResult | null>(null);
  const [artifact, setArtifact] = useState<ArtifactBundle | null>(null);
  const [screening, setScreening] = useState<DesktopReport<ScreeningResult> | null>(null);

  const columns = report.result.preview?.columns ?? [];
  const analytes = useMemo(
    () => [...new Set(report.result.recognized_analytes.map((item) => item.canonical))].sort(),
    [report.result.recognized_analytes],
  );
  const errors = useMemo(() => reviewErrors(report.result, draft), [draft, report.result]);
  const qualityNeedsReview = Object.values(report.result.quality).some((count) => count > 0);
  const needsBasisReview = report.result.figure_candidates.some(
    (candidate) =>
      draft.selected[candidate.diagram] &&
      draft.parameters[candidate.diagram]?.composition_basis === "anhydrous-normalized",
  );

  const updateDraft = (patch: Partial<ReviewDraft>) => {
    setDraft((current) => ({ ...current, ...patch }));
    setPlan(null);
    setPlanReviewed(false);
    setRunResult(null);
    setArtifact(null);
    setScreening(null);
  };

  const updateParameters = (diagram: string, patch: Record<string, unknown>) => {
    updateDraft({
      parameters: {
        ...draft.parameters,
        [diagram]: { ...(draft.parameters[diagram] ?? {}), ...patch },
      },
    });
  };

  const refreshInspection = async (
    projectUpdate: Promise<ProjectSummary>,
  ) => {
    if (busy) return;
    setBusy(true);
    onError("");
    try {
      const updated = await projectUpdate;
      const inspected = await backend.inspectProject(updated.id);
      onProjectUpdate(updated);
      onInspectionUpdate(inspected);
    } catch (caught) {
      onError(caughtMessage(caught, "The local source could not be re-inspected."));
    } finally {
      setBusy(false);
    }
  };

  const saveAndPlan = async () => {
    if (busy || errors.length > 0) return;
    setBusy(true);
    onError("");
    setWorkflowReport(null);
    try {
      const review = buildRecipeReview(report.result, draft);
      const recipeReport = await backend.saveProjectRecipe(project.id, review, true);
      setWorkflowReport(recipeReport);
      if (recipeReport.status !== "ready") return;
      const result = await backend.createExecutionPlan(
        project.id,
        review.tasks.map((task) => task.id),
        true,
      );
      setWorkflowReport(result.report);
      setPlan(result.plan);
      setPlanReviewed(false);
      onProjectUpdate(result.project);
    } catch (caught) {
      onError(caughtMessage(caught, "The reviewed plan could not be created."));
    } finally {
      setBusy(false);
    }
  };

  const runPlan = async () => {
    if (busy || !planReviewed || plan?.status !== "ready") return;
    setBusy(true);
    onError("");
    try {
      const result = await backend.runExecutionPlan(
        project.id,
        planReviewed,
        replaceOutput,
      );
      setRunResult(result);
      setWorkflowReport(result.report);
      if (result.artifacts.length > 0) {
        setArtifact(
          await backend.getGeneratedArtifact(project.id, result.artifacts[0].task_id),
        );
      }
    } catch (caught) {
      onError(caughtMessage(caught, "The reviewed plan did not run."));
    } finally {
      setBusy(false);
    }
  };

  const runScreening = async () => {
    if (busy || plan?.status !== "ready") return;
    setBusy(true);
    onError("");
    try {
      setScreening(await backend.runSio2Screening(project.id));
    } catch (caught) {
      onError(caughtMessage(caught, "The bounded local screening did not run."));
    } finally {
      setBusy(false);
    }
  };

  const loadArtifact = async (taskId: string) => {
    setBusy(true);
    onError("");
    try {
      setArtifact(await backend.getGeneratedArtifact(project.id, taskId));
    } catch (caught) {
      onError(caughtMessage(caught, "The generated artifact could not be displayed safely."));
    } finally {
      setBusy(false);
    }
  };

  const renderParameters = (candidate: FigureCandidate) => {
    const values = draft.parameters[candidate.diagram] ?? {};
    if (candidate.diagram === "ree" || candidate.diagram === "spider") {
      const references =
        candidate.diagram === "ree"
          ? [["chondrite-sm89", "Chondrite (Sun & McDonough 1989)"]]
          : [
              ["pm-sm89", "Primitive mantle (SM89)"],
              ["pm-sm89-modified", "Modified primitive mantle (SM89)"],
              ["nmorb-sm89", "N-MORB (SM89)"],
            ];
      return (
        <div className="parameter-grid">
          <label>
            Normalization reference
            <select
              aria-label={`${candidate.diagram} normalization reference`}
              value={String(values.reference ?? "")}
              onChange={(event) => updateParameters(candidate.diagram, { reference: event.target.value })}
            >
              <option value="">Choose and confirm…</option>
              {references.map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>
          <label>
            Reviewed elements (comma-separated)
            <input
              aria-label={`${candidate.diagram} elements`}
              value={(values.elements as string[] | undefined)?.join(", ") ?? ""}
              onChange={(event) => updateParameters(candidate.diagram, { elements: splitList(event.target.value) })}
            />
          </label>
        </div>
      );
    }
    if (candidate.diagram === "harker") {
      return (
        <div className="parameter-grid">
          <label>Harker x variable<select aria-label="Harker x variable" value={String(values.x ?? "")} onChange={(event) => updateParameters("harker", { x: event.target.value })}><option value="">Choose…</option>{analytes.map((name) => <option key={name}>{name}</option>)}</select></label>
          <label>Harker y variables (comma-separated)<input aria-label="Harker y variables" value={(values.y as string[] | undefined)?.join(", ") ?? ""} onChange={(event) => updateParameters("harker", { y: splitList(event.target.value) })} /></label>
        </div>
      );
    }
    if (candidate.diagram === "tas" || candidate.diagram === "k2o-sio2") {
      return (
        <label className="parameter-single">
          Composition basis
          <select aria-label={`${candidate.diagram} composition basis`} value={String(values.composition_basis ?? "")} onChange={(event) => updateParameters(candidate.diagram, { composition_basis: event.target.value })}>
            <option value="">Choose and confirm…</option>
            <option value="anhydrous-normalized">Anhydrous, normalized to 100%</option>
            {candidate.diagram === "tas" && <option value="as-reported">As reported</option>}
          </select>
        </label>
      );
    }
    if (candidate.diagram === "xy") {
      return (
        <div className="parameter-grid">
          {(["x", "y"] as const).map((axis) => (
            <label key={axis}>{axis.toUpperCase()} variable<select aria-label={`XY ${axis} variable`} value={String(values[axis] ?? "")} onChange={(event) => updateParameters("xy", { [axis]: event.target.value })}><option value="">Choose…</option>{analytes.map((name) => <option key={name}>{name}</option>)}</select></label>
          ))}
        </div>
      );
    }
    return null;
  };

  return (
    <div className="workflow-stack">
      <InspectSummary projectTitle={project.title} report={report} onImportAnother={onImportAnother} />

      <section className="review-panel" aria-labelledby="source-review-title">
        <div className="panel-heading"><div><p className="eyebrow">GATE 3 · REVIEW</p><h2 id="source-review-title">Source mode review</h2></div><span>{busy ? "Working locally…" : "No uploads"}</span></div>
        {report.result.source.sheet_names.length > 1 && (
          <label>Workbook sheet<select aria-label="Workbook sheet" value={String(project.selected_sheet ?? "")} onChange={(event) => void refreshInspection(backend.selectSheet(project.id, event.target.value || null))}><option value="">Choose a sheet…</option>{report.result.source.sheet_names.map((sheet) => <option key={sheet}>{sheet}</option>)}</select></label>
        )}
        <label>Table layout<select aria-label="Table layout" value={project.selected_layout} onChange={(event) => void refreshInspection(backend.selectLayout(project.id, event.target.value as InputLayout))}><option value="auto">Auto-detect, then review</option><option value="row-per-sample">One row per sample</option><option value="analyte-per-row">Analytes in rows (transpose)</option></select></label>
        {report.result.row_count === null && <p className="review-callout">Choose a worksheet before mapping review can continue.</p>}
      </section>

      {report.result.row_count !== null && (
        <>
          <section className="review-panel" aria-labelledby="health-title">
            <div className="panel-heading"><div><p className="eyebrow">GATE 4 · DATA HEALTH</p><h2 id="health-title">Basic quality counts</h2></div><span>Full dataset · no sampling</span></div>
            <div className="health-grid">
              {Object.entries(qualityLabels).map(([name, label]) => (
                <div className="health-card" key={name} data-alert={(report.result.quality[name] ?? 0) > 0}>
                  <strong>{report.result.quality[name] ?? 0}</strong>
                  <span>{label}</span>
                </div>
              ))}
            </div>
            <p className="method-note">Counts are descriptive checks only. Values are not deleted, imputed, or regrouped.</p>
          </section>

          <section className="review-panel" aria-labelledby="mapping-title">
            <div className="panel-heading"><div><p className="eyebrow">MAPPING & UNITS</p><h2 id="mapping-title">Review every mapping</h2></div><span>Units are never guessed</span></div>
            <div className="parameter-grid">
              <label>Sample identifier<select aria-label="Sample identifier" value={draft.sampleId} onChange={(event) => updateDraft({ sampleId: event.target.value })}><option value="">Choose…</option>{columns.map((column) => <option key={column}>{column}</option>)}</select></label>
              <label>Group column (optional)<select aria-label="Group column" value={draft.group} onChange={(event) => updateDraft({ group: event.target.value })}><option value="">No group</option>{columns.filter((column) => column !== draft.sampleId).map((column) => <option key={column}>{column}</option>)}</select></label>
            </div>
            <div className="mapping-table" role="table" aria-label="Analyte mappings">
              {analytes.map((canonical) => {
                const matches = report.result.recognized_analytes.filter((item) => item.canonical === canonical);
                const requiredUnit = matches[0]?.required_unit ?? "";
                return (
                  <div className="mapping-row" role="row" key={canonical}>
                    <label><input type="checkbox" aria-label={`Use ${canonical}`} checked={Boolean(draft.mapping[canonical])} onChange={(event) => updateDraft({ mapping: { ...draft.mapping, [canonical]: event.target.checked ? matches[0]?.source_column ?? "" : "" } })} />{canonical}</label>
                    <select aria-label={`${canonical} source column`} disabled={!draft.mapping[canonical]} value={draft.mapping[canonical] ?? ""} onChange={(event) => updateDraft({ mapping: { ...draft.mapping, [canonical]: event.target.value } })}>{matches.map((match) => <option key={match.source_column}>{match.source_column}</option>)}</select>
                    <select aria-label={`${canonical} unit`} disabled={!draft.mapping[canonical]} value={draft.units[canonical] ?? ""} onChange={(event) => updateDraft({ units: { ...draft.units, [canonical]: event.target.value } })}><option value="">Confirm unit…</option>{requiredUnit && <option value={requiredUnit}>{requiredUnit}</option>}</select>
                  </div>
                );
              })}
            </div>
          </section>

          <section className="review-panel" aria-labelledby="candidate-title">
            <div className="panel-heading"><div><p className="eyebrow">CANDIDATES</p><h2 id="candidate-title">Choose figure tasks</h2></div><span>Registry-derived</span></div>
            <div className="candidate-grid">
              {report.result.figure_candidates.map((candidate) => {
                const disabled = candidate.state === "NOT_AVAILABLE" || candidate.state === "BLOCKED";
                const selected = Boolean(draft.selected[candidate.diagram]);
                return (
                  <article className="candidate-card" data-state={candidate.state} key={candidate.diagram}>
                    <header><div><h3>{candidate.display_name_zh}</h3><p>{candidate.display_name_en}</p></div><span>{candidateState[candidate.state]}</span></header>
                    <label className="candidate-toggle"><input type="checkbox" aria-label={`Select ${candidate.display_name_en}`} disabled={disabled} checked={selected} onChange={(event) => updateDraft({ selected: { ...draft.selected, [candidate.diagram]: event.target.checked } })} />Include this task</label>
                    {selected && <div className="candidate-parameters">{renderParameters(candidate)}{candidate.required_confirmations.map((name) => <label className="confirmation" key={name}><input type="checkbox" checked={draft.taskConfirmations[candidate.diagram]?.[name] === true} onChange={(event) => updateDraft({ taskConfirmations: { ...draft.taskConfirmations, [candidate.diagram]: { ...(draft.taskConfirmations[candidate.diagram] ?? {}), [name]: event.target.checked } } })} />{CONFIRMATION_LABELS[name] ?? name}</label>)}</div>}
                    {candidate.requirements.length > 0 && <small>{candidate.requirements.join(" · ")}</small>}
                  </article>
                );
              })}
            </div>
          </section>

          <section className="review-panel" aria-labelledby="confirmation-title">
            <div className="panel-heading"><div><p className="eyebrow">CONFIRMATION GATE</p><h2 id="confirmation-title">Explicit review confirmations</h2></div><span>All default to false</span></div>
            {TOP_CONFIRMATIONS.map((name) => <label className="confirmation" key={name}><input type="checkbox" checked={draft.confirmations[name] === true} onChange={(event) => updateDraft({ confirmations: { ...draft.confirmations, [name]: event.target.checked } })} />{CONFIRMATION_LABELS[name]}</label>)}
            {needsBasisReview && <label className="confirmation"><input type="checkbox" checked={draft.confirmations.data_basis_reviewed === true} onChange={(event) => updateDraft({ confirmations: { ...draft.confirmations, data_basis_reviewed: event.target.checked } })} />{CONFIRMATION_LABELS.data_basis_reviewed}</label>}
            {qualityNeedsReview && <label className="confirmation"><input type="checkbox" checked={draft.confirmations.data_quality_reviewed === true} onChange={(event) => updateDraft({ confirmations: { ...draft.confirmations, data_quality_reviewed: event.target.checked } })} />{CONFIRMATION_LABELS.data_quality_reviewed}</label>}
            <label>Report profile<select aria-label="Report profile" value={draft.reportProfile} onChange={(event) => updateDraft({ reportProfile: event.target.value as ReviewDraft["reportProfile"] })}><option value="shareable">Shareable (no source values)</option><option value="local-reproducible">Local reproducible (includes source data)</option></select></label>
            {errors.length > 0 && (
              <>
                <details className="remaining-review">
                  <summary>{errors.length} review item(s) remaining · open to resolve</summary>
                  <ul>{errors.map((message) => <li key={message}>{message}</li>)}</ul>
                </details>
                <p className="gate-hint" id="create-plan-gate-status">
                  Complete the required review items above to unlock plan creation. The disabled button is waiting for review, not processing.
                </p>
              </>
            )}
            <button
              className="primary-button"
              type="button"
              aria-busy={busy}
              aria-describedby={errors.length > 0 ? "create-plan-gate-status" : undefined}
              data-busy={busy}
              disabled={busy || errors.length > 0}
              title={
                busy
                  ? "Saving the reviewed recipe and creating the plan."
                  : errors.length > 0
                    ? `Complete ${errors.length} required review item${errors.length === 1 ? "" : "s"} to enable this action.`
                    : "Save the reviewed recipe and create an execution plan."
              }
              onClick={() => void saveAndPlan()}
            >
              {busy ? "Saving recipe and creating plan…" : "Save reviewed recipe and create plan"}
            </button>
          </section>
        </>
      )}

      {workflowReport && workflowReport.status !== "ready" && <section className="issue-panel" aria-label="Workflow issues"><h2>Workflow stopped for review</h2><ul>{workflowReport.issues.map((issue) => <li key={`${issue.code}-${issue.field ?? "general"}`}><strong>{issue.code}</strong> {issue.message}</li>)}</ul></section>}

      {plan && (
        <section className="review-panel plan-panel" aria-labelledby="plan-title">
          <div className="panel-heading"><div><p className="eyebrow">EXECUTION PLAN</p><h2 id="plan-title">Review before run</h2></div><span data-status={plan.status}>{plan.status}</span></div>
          <dl><div><dt>Plan</dt><dd>{plan.plan_id.slice(0, 16)}…</dd></div><div><dt>Tasks</dt><dd>{plan.tasks.map((task) => task.diagram).join(" · ")}</dd></div><div><dt>Mappings</dt><dd>{plan.column_mapping.length}</dd></div><div><dt>Output</dt><dd>outputs/current (project-relative)</dd></div></dl>
          <label className="confirmation"><input type="checkbox" checked={planReviewed} onChange={(event) => setPlanReviewed(event.target.checked)} />I reviewed this exact plan and its scientific parameters.</label>
          <label className="confirmation"><input type="checkbox" checked={replaceOutput} onChange={(event) => setReplaceOutput(event.target.checked)} />Explicitly replace an existing reviewed output bundle.</label>
          <button className="primary-button" type="button" aria-busy={busy} data-busy={busy} disabled={busy || !planReviewed || plan.status !== "ready"} onClick={() => void runPlan()}>{busy ? "Working locally…" : "Run reviewed plan locally"}</button>
          <button className="secondary-button" type="button" disabled={busy || plan.status !== "ready"} onClick={() => void runScreening()}>Run bounded SiO2 screening</button>
        </section>
      )}

      {screening && (
        <section className="review-panel screening-panel" aria-labelledby="screening-title">
          <div className="panel-heading"><div><p className="eyebrow">DETERMINISTIC SCREENING</p><h2 id="screening-title">SiO2 covariation ranking</h2></div><span>Spearman · pairwise finite n ≥ 8</span></div>
          {screening.result.available ? (
            screening.result.results.length > 0 ? (
              <table className="screening-table">
                <thead><tr><th>Variable</th><th>rho</th><th>n</th></tr></thead>
                <tbody>{screening.result.results.map((item) => <tr key={item.variable}><td>{item.variable}</td><td>{item.rho.toFixed(3)}</td><td>{item.n}</td></tr>)}</tbody>
              </table>
            ) : <p>No mapped variable met the finite pair threshold.</p>
          ) : <p>SiO2 is not mapped. Choose explicit X and Y variables in the XY workflow instead.</p>}
          {screening.result.variables_capped && <p>Variable scan reached the fixed 32-variable limit.</p>}
          <p className="screening-disclaimer">{screening.result.disclaimer}</p>
        </section>
      )}

      {runResult && (
        <section className="review-panel" aria-labelledby="outputs-title">
          <div className="panel-heading"><div><p className="eyebrow">GENERATED OUTPUTS</p><h2 id="outputs-title">Figures and QA</h2></div><span>{runResult.report.status}</span></div>
          <div className="artifact-tabs">{runResult.artifacts.map((item) => <button type="button" className={artifact?.task_id === item.task_id ? "active" : ""} key={item.task_id} onClick={() => void loadArtifact(item.task_id)}>{item.diagram}</button>)}</div>
          {artifact && <div className="artifact-view"><figure><img src={artifact.svg_data_url} alt={`${artifact.diagram} generated figure`} /><figcaption>Generated locally from the reviewed plan.</figcaption></figure><section><h3>QA summary</h3><pre>{artifact.qa_markdown}</pre><details><summary>Machine-readable report</summary><pre>{JSON.stringify(artifact.report, null, 2)}</pre></details></section></div>}
        </section>
      )}
    </div>
  );
}
