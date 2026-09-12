import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

import { App } from "../src/app/App";
import "../src/app/styles.css";
import type { DesktopBackend } from "../src/lib/backend";
import type {
  DesktopReport,
  ExecutionPlan,
  InspectResult,
  ProjectSummary,
} from "../src/types/desktop";
import mixedInspect from "./fixtures/mixed-unit-inspect.json";

const project: ProjectSummary = {
  schema_version: "geoskills.desktop-project/v1",
  id: "73f01f95-a9bb-490d-90b0-8c30ddbcc78e",
  title: "Responsive mixed-unit project with a deliberately long display name",
  created_at: "2026-09-11T00:00:00Z",
  updated_at: "2026-09-11T00:00:00Z",
  source: {
    stored_filename: "mixed-unit-transposed-source-with-long-name.xlsx",
    original_basename: "mixed-unit-transposed-source-with-long-name.xlsx",
    sha256: "a".repeat(64),
    size_bytes: 5806,
  },
  selected_sheet: "Mixed units",
  selected_layout: "auto",
  latest_plan_id: null,
};

const report: DesktopReport<InspectResult> = {
  schema_version: "geoskills.desktop-report/v1",
  operation: "inspect",
  status: "ready",
  engine: { name: "GeoSkills", version: "0.9.0-rc1", diagram_api_version: "geoskills.diagram/v1" },
  issues: [],
  result: {
    source: {
      stored_filename: project.source!.stored_filename,
      sha256: project.source!.sha256,
      size_bytes: project.source!.size_bytes,
      format: ".xlsx",
      sheet_names: ["Mixed units"],
      selected_sheet: "Mixed units",
      layout: mixedInspect.layout,
      transformation: "auto_transpose_geochemical_analytes_by_row",
    },
    row_count: 2,
    column_count: 49,
    sample_column_candidates: ["Sample"],
    sample_column_suggestion: "Sample",
    group_column_candidates: ["Group"],
    recognized_analytes: mixedInspect.recognized_analytes,
    mapping_suggestions: mixedInspect.mapping_suggestions,
    unrecognized_columns: [],
    quality: {
      missing_value_count: 0,
      below_detection_limit_count: 0,
      non_numeric_count: 0,
      non_positive_count: 0,
      duplicate_sample_id_count: 0,
      blank_sample_id_count: 0,
      ...mixedInspect.quality,
    },
    preview: {
      columns: ["Sample", "Group", ...mixedInspect.recognized_analytes.slice(0, 10).map((item) => item.source_column)],
      rows: [
        ["SYN-A", "Synthetic A", 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        ["SYN-B", "Synthetic B", 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
      ],
      preview_truncated_rows: false,
      preview_truncated_columns: true,
      notice: "Preview only. GeoSkills inspection and plotting use the complete dataset.",
    },
    figure_candidates: [
      {
        diagram: "ree",
        display_name_en: "REE pattern",
        display_name_zh: "稀土元素配分图",
        state: "AVAILABLE_AFTER_REVIEW",
        requirements: [],
        required_confirmations: [],
        suggestions: { elements: ["La", "Ce", "Pr", "Nd", "Sm"] },
      },
      {
        diagram: "tas",
        display_name_en: "Volcanic TAS classification",
        display_name_zh: "火山岩 TAS 分类图",
        state: "NEEDS_SCIENTIFIC_CONFIRMATION",
        requirements: ["volcanic_samples", "composition_basis_reviewed"],
        required_confirmations: ["volcanic_samples", "composition_basis_reviewed"],
        suggestions: {},
      },
    ],
  },
};

const planId = "responsive-qa-plan-000000000001";
const plan: ExecutionPlan = {
  schema_version: "geoskills.plan/v1",
  plan_id: planId,
  status: "ready",
  input: { source: project.source!.stored_filename },
  column_mapping: mixedInspect.recognized_analytes.map((item) => ({
    canonical: item.canonical,
    source_column: item.source_column,
    unit: item.explicit_unit,
  })),
  output: { directory: "outputs/current" },
  confirmations: {
    mapping_reviewed: true,
    units_reviewed: true,
    sample_id_reviewed: true,
    group_reviewed: true,
  },
  tasks: [
    {
      id: "ree-main",
      diagram: "ree",
      parameters: { reference: "chondrite-sm89" },
      confirmations: {},
      expected_outputs: [
        "ree-main/figure-ree.svg",
        "ree-main/figure-ree.report.json",
        "ree-main/figure-ree.qa.md",
      ],
    },
  ],
  issues: [],
};

function operationReport(operation: string): DesktopReport<Record<string, unknown>> {
  return {
    schema_version: "geoskills.desktop-report/v1",
    operation,
    status: "ready",
    engine: report.engine,
    result: operation === "plan" ? { plan_id: planId } : {},
    issues: [],
  };
}

const svgDataUrl = `data:image/svg+xml,${encodeURIComponent(`
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 520">
    <rect width="900" height="520" fill="#fffdf8"/>
    <path d="M95 65V440H835" stroke="#173d32" stroke-width="4" fill="none"/>
    <polyline points="105,355 210,300 315,330 420,235 525,270 630,175 735,205 825,115" fill="none" stroke="#8a5d18" stroke-width="7"/>
    <g fill="#8a5d18">${["105,355", "210,300", "315,330", "420,235", "525,270", "630,175", "735,205", "825,115"].map((point) => `<circle cx="${point.split(",")[0]}" cy="${point.split(",")[1]}" r="10"/>`).join("")}</g>
    <text x="450" y="500" text-anchor="middle" font-size="28" fill="#173d32">Reviewed REE elements</text>
    <text x="35" y="255" transform="rotate(-90 35 255)" text-anchor="middle" font-size="25" fill="#173d32">Sample / Chondrite</text>
  </svg>
`)}`;

const unused = async (): Promise<never> => { throw new Error("Not used by responsive QA"); };
const backend: DesktopBackend = {
  listProjects: async () => [project],
  createProject: unused,
  renameProject: unused,
  removeProject: unused,
  listRemovedProjects: async () => [],
  restoreProject: unused,
  importSourceFile: unused,
  inspectProject: async () => report,
  selectSheet: unused,
  selectLayout: unused,
  saveProjectRecipe: async () => operationReport("recipe"),
  createExecutionPlan: async () => ({
    report: operationReport("plan"),
    plan,
    project: { ...project, latest_plan_id: planId },
  }),
  getCurrentPlan: async () => plan,
  runExecutionPlan: async () => ({
    report: operationReport("run"),
    artifacts: [{ task_id: "ree-main", diagram: "ree", svg_available: true, qa_available: true, report_available: true }],
  }),
  runSio2Screening: async () => ({
    ...operationReport("screen"),
    result: {
      available: false,
      reason: "insufficient_pairs",
      x: "SiO2",
      variables_considered: ["TiO2"],
      variables_capped: false,
      results: [],
      method: "spearman_rank_then_pearson",
      minimum_pair_count: 8,
      maximum_variables: 32,
      maximum_results: 8,
      data_scope: "full_reviewed_mapped_dataset",
      disclaimer: "Exploratory screening only. Correlation strength is not statistical proof and does not identify a geochemical process.",
    },
  }),
  listGeneratedArtifacts: async () => [],
  getGeneratedArtifact: async () => ({
    task_id: "ree-main",
    diagram: "ree",
    svg_data_url: svgDataUrl,
    qa_markdown: "# QA summary\n\n- Full reviewed dataset used.\n- Long audit identifier: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n- Output: outputs/current/ree-main/figure-ree.svg",
    report: { status: "ready", source_sha256: "a".repeat(64), plan_id: planId },
  }),
};

function WidthProbe() {
  const [measurement, setMeasurement] = useState("waiting for layout");
  useEffect(() => {
    const update = () => {
      const root = document.documentElement;
      const cardPreview = document.querySelector<HTMLElement>(".preview-card-view");
      const tablePreview = document.querySelector<HTMLElement>(".table-scroll");
      setMeasurement(
        [
          `viewport=${window.innerWidth}x${window.innerHeight}`,
          `scrollWidth=${root.scrollWidth}`,
          `clientWidth=${root.clientWidth}`,
          `result=${root.scrollWidth <= root.clientWidth ? "PASS" : "FAIL"}`,
          `projectActions=${document.querySelectorAll(".project-actions").length}`,
          `mappingRows=${document.querySelectorAll(".mapping-row").length}`,
          `unitControls=${document.querySelectorAll('[aria-label$=" unit"]').length}`,
          `confirmations=${document.querySelectorAll(".confirmation").length}`,
          `cardPreview=${cardPreview ? getComputedStyle(cardPreview).display : "missing"}`,
          `tablePreview=${tablePreview ? getComputedStyle(tablePreview).display : "missing"}`,
          `plan=${document.querySelectorAll(".plan-panel").length}`,
          `artifact=${document.querySelectorAll(".artifact-view").length}`,
        ].join(" | "),
      );
    };
    const frame = requestAnimationFrame(update);
    const observer = new ResizeObserver(update);
    observer.observe(document.documentElement);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, []);
  return <output data-testid="width-probe" style={{ position: "fixed", zIndex: 99, right: 6, bottom: 6, maxWidth: "calc(100% - 12px)", padding: 6, overflowWrap: "anywhere", color: "#fff", background: "#102d24", fontSize: 10 }}>{measurement}</output>;
}

createRoot(document.getElementById("root")!).render(<><WidthProbe /><App backend={backend} /></>);
