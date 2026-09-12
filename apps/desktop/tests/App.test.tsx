import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import type { DesktopBackend } from "../src/lib/backend";
import { CONFIRMATION_LABELS, TOP_CONFIRMATIONS } from "../src/lib/review";
import mixedInspect from "./fixtures/mixed-unit-inspect.json";
import type {
  DesktopReport,
  ExecutionPlan,
  InspectResult,
  ProjectSummary,
} from "../src/types/desktop";

const planId = "a".repeat(64);
const project: ProjectSummary = {
  schema_version: "geoskills.desktop-project/v1",
  id: "73f01f95-a9bb-490d-90b0-8c30ddbcc78e",
  title: "synthetic_ree_data",
  created_at: "2026-09-10T00:00:00Z",
  updated_at: "2026-09-10T00:00:00Z",
  source: null,
  selected_sheet: null,
  selected_layout: "auto",
  latest_plan_id: null,
};

const imported: ProjectSummary = {
  ...project,
  source: {
    stored_filename: "source.csv",
    original_basename: "synthetic_ree_data.csv",
    sha256: "abc",
    size_bytes: 120,
  },
};

const secondProject: ProjectSummary = {
  ...imported,
  id: "861c9855-5536-4b04-93fa-33928393330c",
  title: "second_project",
};

const report: DesktopReport<InspectResult> = {
  schema_version: "geoskills.desktop-report/v1",
  operation: "inspect",
  status: "ready",
  engine: {
    name: "GeoSkills",
    version: "0.9.0-rc1",
    diagram_api_version: "geoskills.diagram/v1",
  },
  issues: [],
  result: {
    source: {
      stored_filename: "source.csv",
      sha256: "abc",
      size_bytes: 120,
      format: ".csv",
      sheet_names: [],
      selected_sheet: null,
      layout: "row_per_sample",
      transformation: null,
    },
    row_count: 3,
    column_count: 7,
    sample_column_candidates: ["Sample"],
    sample_column_suggestion: "Sample",
    group_column_candidates: ["Group"],
    recognized_analytes: ["La", "Ce", "Pr", "Nd", "Sm"].map(
      (canonical) => ({
        canonical,
        kind: "trace_element",
        source_label: `${canonical}_ppm`,
        source_column: `${canonical}_ppm`,
        required_unit: "ppm",
        explicit_unit: "ppm",
        unit_status: "confirmed_from_header",
      }),
    ),
    mapping_suggestions: {
      La: "La_ppm",
      Ce: "Ce_ppm",
      Pr: "Pr_ppm",
      Nd: "Nd_ppm",
      Sm: "Sm_ppm",
    },
    quality: {},
    preview: {
      columns: ["Sample", "Group", "La_ppm", "Ce_ppm", "Pr_ppm", "Nd_ppm", "Sm_ppm"],
      rows: [["SYN-01", "A", 20, 40, 5, 18, 4]],
      preview_truncated_rows: false,
      preview_truncated_columns: false,
      notice: "Preview only. Full data are used.",
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
        state: "NOT_AVAILABLE",
        requirements: ["SiO2", "Na2O", "K2O"],
        required_confirmations: ["volcanic_samples", "composition_basis_reviewed"],
        suggestions: {},
      },
    ],
  },
};

const mixedReport: DesktopReport<InspectResult> = {
  ...report,
  result: {
    ...report.result,
    source: {
      ...report.result.source,
      stored_filename: "mixed-units.xlsx",
      format: ".xlsx",
      sheet_names: ["Mixed units"],
      selected_sheet: "Mixed units",
      layout: mixedInspect.layout,
      transformation: "auto_transpose_geochemical_analytes_by_row",
    },
    row_count: 2,
    column_count: 49,
    recognized_analytes: mixedInspect.recognized_analytes,
    mapping_suggestions: mixedInspect.mapping_suggestions,
    quality: {
      missing_value_count: 0,
      below_detection_limit_count: 0,
      non_numeric_count: 0,
      non_positive_count: 0,
      duplicate_sample_id_count: 0,
      blank_sample_id_count: 0,
      ...mixedInspect.quality,
    },
  },
};

const plan: ExecutionPlan = {
  schema_version: "geoskills.plan/v1",
  plan_id: planId,
  status: "ready",
  input: {},
  column_mapping: [
    { canonical_analyte: "La", unit: "ppm" },
    { canonical_analyte: "Ce", unit: "ppm" },
    { canonical_analyte: "Pr", unit: "ppm" },
    { canonical_analyte: "Nd", unit: "ppm" },
    { canonical_analyte: "Sm", unit: "ppm" },
  ],
  output: { directory: "outputs/current", report_profile: "shareable" },
  confirmations: {},
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

function backend(
  initialProjects: ProjectSummary[] = [],
  inspectReport: DesktopReport<InspectResult> = report,
  initialRemovedProjects: ProjectSummary[] = [],
): DesktopBackend {
  return {
    listProjects: vi.fn().mockResolvedValue(initialProjects),
    listRemovedProjects: vi.fn().mockResolvedValue(initialRemovedProjects),
    createProject: vi.fn().mockResolvedValue(project),
    renameProject: vi.fn().mockImplementation(async (projectId: string, title: string) => ({
      ...(initialProjects.find((item) => item.id === projectId) ?? project),
      title: title.trim(),
    })),
    removeProject: vi.fn().mockImplementation(async (projectId: string) =>
      initialProjects.find((item) => item.id === projectId) ?? project,
    ),
    restoreProject: vi.fn().mockImplementation(async (projectId: string) =>
      initialRemovedProjects.find((item) => item.id === projectId) ?? project,
    ),
    importSourceFile: vi.fn().mockResolvedValue({ project: imported, replaced: false }),
    inspectProject: vi.fn().mockResolvedValue(inspectReport),
    selectSheet: vi.fn().mockResolvedValue(imported),
    selectLayout: vi.fn().mockResolvedValue({ ...imported, selected_layout: "row-per-sample" }),
    saveProjectRecipe: vi.fn().mockResolvedValue(operationReport("recipe")),
    createExecutionPlan: vi.fn().mockResolvedValue({
      report: operationReport("plan"),
      plan,
      project: { ...imported, latest_plan_id: planId },
    }),
    getCurrentPlan: vi.fn().mockResolvedValue(plan),
    runExecutionPlan: vi.fn().mockResolvedValue({
      report: operationReport("run"),
      artifacts: [
        {
          task_id: "ree-main",
          diagram: "ree",
          svg_available: true,
          qa_available: true,
          report_available: true,
        },
      ],
    }),
    runSio2Screening: vi.fn().mockResolvedValue({
      schema_version: "geoskills.desktop-report/v1",
      operation: "screen",
      status: "ready",
      engine: report.engine,
      result: {
        available: false,
        reason: "sio2_not_mapped",
        x: "SiO2",
        variables_considered: [],
        variables_capped: false,
        results: [],
        method: "spearman_rank_then_pearson",
        minimum_pair_count: 8,
        maximum_variables: 32,
        maximum_results: 8,
        data_scope: "full_reviewed_mapped_dataset",
        disclaimer: "Exploratory screening only. Correlation strength is not statistical proof and does not identify a geochemical process.",
      },
      issues: [],
    }),
    listGeneratedArtifacts: vi.fn().mockResolvedValue([]),
    getGeneratedArtifact: vi.fn().mockResolvedValue({
      task_id: "ree-main",
      diagram: "ree",
      svg_data_url: "data:image/svg+xml;base64,PHN2Zy8+",
      qa_markdown: "# QA\nAll checks complete.",
      report: { status: "ready" },
    }),
  };
}

async function importFixture(localBackend: DesktopBackend) {
  render(
    <App
      backend={localBackend}
      chooseFile={vi.fn().mockResolvedValue("C:\\fixtures\\synthetic_ree_data.csv")}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Choose a file" }));
  await screen.findByRole("heading", { name: "synthetic_ree_data" });
}

function completeReeReview() {
  fireEvent.click(screen.getByLabelText("Select REE pattern"));
  fireEvent.change(screen.getByLabelText("ree normalization reference"), {
    target: { value: "chondrite-sm89" },
  });
  for (const name of TOP_CONFIRMATIONS) {
    fireEvent.click(screen.getByLabelText(CONFIRMATION_LABELS[name]));
  }
}

describe("GeoPlot Gate 2 shell", () => {
  it("shows the empty local drop page", async () => {
    render(<App backend={backend()} chooseFile={vi.fn().mockResolvedValue(null)} />);
    expect(screen.getByRole("heading", { name: "Drop geochemical data here" })).toBeInTheDocument();
    expect(screen.getByText("Local processing only")).toBeInTheDocument();
    expect(screen.getByText("XLSX · CSV · TXT · maximum 20 MiB")).toBeInTheDocument();
  });

  it("renders persisted projects without exposing their filesystem IDs", async () => {
    render(<App backend={backend([imported])} chooseFile={vi.fn().mockResolvedValue(null)} />);
    expect(await screen.findByText("synthetic_ree_data")).toBeInTheDocument();
    expect(screen.queryByText(imported.id)).not.toBeInTheDocument();
  });

  it("copies then inspects a selected synthetic file", async () => {
    const localBackend = backend();
    await importFixture(localBackend);
    expect(screen.getByText("✓ Ready")).toBeInTheDocument();
    expect(screen.getByText("La · Ce · Pr · Nd · Sm")).toBeInTheDocument();
    await waitFor(() => {
      expect(localBackend.importSourceFile).toHaveBeenCalledWith(
        project.id,
        "C:\\fixtures\\synthetic_ree_data.csv",
        false,
      );
      expect(localBackend.inspectProject).toHaveBeenCalledWith(project.id);
    });
  });

  it("shows an actionable inspect-contract error from the adapter", async () => {
    const localBackend = backend();
    localBackend.inspectProject = vi.fn().mockRejectedValue(
      new Error("Desktop bridge returned an invalid inspect contract: canonical is missing."),
    );
    render(
      <App
        backend={localBackend}
        chooseFile={vi.fn().mockResolvedValue("C:\\fixtures\\synthetic_ree_data.csv")}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Choose a file" }));
    expect(await screen.findByText(/Desktop bridge returned an invalid inspect contract/)).toBeInTheDocument();
  });
});

describe("GeoPlot project lifecycle", () => {
  it("renames a project without changing the selected project", async () => {
    const localBackend = backend([imported, secondProject]);
    render(<App backend={localBackend} chooseFile={vi.fn().mockResolvedValue(null)} />);
    expect(await screen.findByRole("heading", { name: imported.title })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: `Actions for ${secondProject.title}` }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
    expect(screen.getByRole("heading", { name: imported.title })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Rename project title"), {
      target: { value: "Renamed second project" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Renamed second project")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: imported.title })).toBeInTheDocument();
    expect(localBackend.renameProject).toHaveBeenCalledWith(secondProject.id, "Renamed second project");
  });

  it("keeps rename open and shows a validation failure", async () => {
    const localBackend = backend([imported]);
    localBackend.renameProject = vi.fn().mockRejectedValue("Project title must contain 1 to 120 visible characters.");
    render(<App backend={localBackend} chooseFile={vi.fn().mockResolvedValue(null)} />);
    await screen.findByRole("heading", { name: imported.title });
    fireEvent.click(screen.getByRole("button", { name: `Actions for ${imported.title}` }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
    fireEvent.change(screen.getByLabelText("Rename project title"), { target: { value: " " } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Project title must contain 1 to 120 visible characters.");
    expect(screen.getByLabelText("Rename project title")).toBeInTheDocument();
  });

  it("confirms removal, chooses the next project, and restores without switching", async () => {
    const localBackend = backend([imported, secondProject]);
    render(<App backend={localBackend} chooseFile={vi.fn().mockResolvedValue(null)} />);
    await screen.findByRole("heading", { name: imported.title });
    fireEvent.click(screen.getByRole("button", { name: `Actions for ${imported.title}` }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Remove" }));

    expect(screen.getByRole("dialog", { name: `Remove ${imported.title}` })).toHaveTextContent(
      "The original external imported file is not touched",
    );
    expect(localBackend.removeProject).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Remove project" }));

    expect(await screen.findByRole("heading", { name: secondProject.title })).toBeInTheDocument();
    expect(localBackend.removeProject).toHaveBeenCalledWith(imported.id);
    fireEvent.click(screen.getByText("Recently removed"));
    fireEvent.click(await screen.findByRole("button", { name: "Restore" }));
    await waitFor(() => expect(localBackend.restoreProject).toHaveBeenCalledWith(imported.id));
    expect(screen.getByRole("heading", { name: secondProject.title })).toBeInTheDocument();
  });

  it("returns to the import landing state after removing the only active project", async () => {
    const localBackend = backend([imported]);
    render(<App backend={localBackend} chooseFile={vi.fn().mockResolvedValue(null)} />);
    await screen.findByRole("heading", { name: imported.title });
    fireEvent.click(screen.getByRole("button", { name: `Actions for ${imported.title}` }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Remove" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove project" }));
    expect(await screen.findByRole("heading", { name: "Drop geochemical data here" })).toBeInTheDocument();
  });
});

describe("GeoPlot Gate 3 review and execution", () => {
  it("keeps all 47 source-bridge analytes separate with both unit families", async () => {
    await importFixture(backend([], mixedReport));
    expect(within(screen.getByRole("table", { name: "Analyte mappings" })).getAllByRole("row")).toHaveLength(47);
    expect(screen.getByLabelText("SiO2 unit")).toHaveValue("wt%");
    expect(screen.getByLabelText("La unit")).toHaveValue("ppm");
    expect(screen.queryByLabelText("undefined unit")).not.toBeInTheDocument();
    expect(screen.getByText("5 review item(s) remaining · open to resolve")).toBeInTheDocument();
    for (const name of TOP_CONFIRMATIONS) {
      expect(screen.getByLabelText(CONFIRMATION_LABELS[name])).not.toBeChecked();
    }
  });

  it("keeps all confirmations false and blocks plan creation by default", async () => {
    await importFixture(backend());
    const create = screen.getByRole("button", { name: "Save reviewed recipe and create plan" });
    expect(create).toBeDisabled();
    expect(create).toHaveAttribute("aria-busy", "false");
    expect(create).toHaveAttribute("data-busy", "false");
    expect(create).toHaveAttribute("title", "Complete 5 required review items to enable this action.");
    expect(screen.getByText(/disabled button is waiting for review, not processing/i)).toBeInTheDocument();
    for (const name of TOP_CONFIRMATIONS) {
      expect(screen.getByLabelText(CONFIRMATION_LABELS[name])).not.toBeChecked();
    }
  });

  it("requires an explicit normalization reference selection", async () => {
    await importFixture(backend());
    fireEvent.click(screen.getByLabelText("Select REE pattern"));
    expect(screen.getByLabelText("ree normalization reference")).toHaveValue("");
    expect(screen.getByText(/Select the normalization reference for ree/)).toBeInTheDocument();
  });

  it("does not enable blocked candidates", async () => {
    await importFixture(backend());
    expect(screen.getByLabelText("Select Volcanic TAS classification")).toBeDisabled();
  });

  it("re-inspects after an explicit layout change", async () => {
    const localBackend = backend();
    await importFixture(localBackend);
    fireEvent.change(screen.getByLabelText("Table layout"), {
      target: { value: "row-per-sample" },
    });
    await waitFor(() => {
      expect(localBackend.selectLayout).toHaveBeenCalledWith(project.id, "row-per-sample");
      expect(localBackend.inspectProject).toHaveBeenCalledTimes(2);
    });
  });

  it("creates a recipe and plan only after the review gate is complete", async () => {
    const localBackend = backend();
    await importFixture(localBackend);
    completeReeReview();
    const create = screen.getByRole("button", { name: "Save reviewed recipe and create plan" });
    expect(create).toBeEnabled();
    fireEvent.click(create);
    expect(await screen.findByRole("heading", { name: "Review before run" })).toBeInTheDocument();
    expect(screen.getByText("outputs/current (project-relative)")).toBeInTheDocument();
    expect(localBackend.saveProjectRecipe).toHaveBeenCalled();
    expect(localBackend.createExecutionPlan).toHaveBeenCalledWith(project.id, ["ree-main"], true);
  });

  it("requires explicit review of the exact plan before run", async () => {
    await importFixture(backend());
    completeReeReview();
    fireEvent.click(screen.getByRole("button", { name: "Save reviewed recipe and create plan" }));
    const run = await screen.findByRole("button", { name: "Run reviewed plan locally" });
    expect(run).toBeDisabled();
    fireEvent.click(screen.getByLabelText("I reviewed this exact plan and its scientific parameters."));
    expect(run).toBeEnabled();
  });

  it("renders the generated SVG and QA as local artifacts", async () => {
    const localBackend = backend();
    await importFixture(localBackend);
    completeReeReview();
    fireEvent.click(screen.getByRole("button", { name: "Save reviewed recipe and create plan" }));
    await screen.findByRole("heading", { name: "Review before run" });
    fireEvent.click(screen.getByLabelText("I reviewed this exact plan and its scientific parameters."));
    fireEvent.click(screen.getByRole("button", { name: "Run reviewed plan locally" }));
    expect(await screen.findByAltText("ree generated figure")).toBeInTheDocument();
    expect(screen.getByText(/All checks complete/)).toBeInTheDocument();
    expect(localBackend.runExecutionPlan).toHaveBeenCalledWith(project.id, true, false);
  });

  it("shows bounded data-health counts without changing source values", async () => {
    await importFixture(backend());
    expect(screen.getByRole("heading", { name: "Basic quality counts" })).toBeInTheDocument();
    expect(screen.getByText("Missing values")).toBeInTheDocument();
    expect(screen.getByText(/not deleted, imputed, or regrouped/i)).toBeInTheDocument();
  });

  it("runs screening only after a reviewed plan and handles missing SiO2", async () => {
    const localBackend = backend();
    await importFixture(localBackend);
    completeReeReview();
    fireEvent.click(screen.getByRole("button", { name: "Save reviewed recipe and create plan" }));
    const screenButton = await screen.findByRole("button", { name: "Run bounded SiO2 screening" });
    fireEvent.click(screenButton);
    expect(await screen.findByText(/Choose explicit X and Y variables/)).toBeInTheDocument();
    expect(screen.getByText("Exploratory screening only. Correlation strength is not statistical proof and does not identify a geochemical process.")).toBeInTheDocument();
    expect(localBackend.runSio2Screening).toHaveBeenCalledWith(project.id);
  });
});
