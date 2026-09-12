import type { DesktopReport, InspectResult } from "../types/desktop";

interface InspectSummaryProps {
  projectTitle: string;
  report: DesktopReport<InspectResult>;
  onImportAnother: () => void;
}

const statusLabels = {
  ready: "✓ Ready",
  needs_confirmation: "? Confirmation required",
  review: "! Review",
  blocked: "× Blocked",
  error: "× Error",
} as const;

export function InspectSummary({
  projectTitle,
  report,
  onImportAnother,
}: InspectSummaryProps) {
  const { result } = report;
  return (
    <section className="workspace" aria-labelledby="workspace-title">
      <header className="workspace-header">
        <div>
          <p className="eyebrow">PROJECT WORKSPACE</p>
          <h1 id="workspace-title">{projectTitle}</h1>
        </div>
        <button className="secondary-button" type="button" onClick={onImportAnother}>
          Import another file
        </button>
      </header>
      <div className="status-line" data-status={report.status}>
        <strong>{statusLabels[report.status]}</strong>
        <span>{result.source.stored_filename}</span>
      </div>
      <div className="metric-grid">
        <article className="metric-card">
          <span>Samples</span>
          <strong>{result.row_count ?? "—"}</strong>
          <small>Full-table count</small>
        </article>
        <article className="metric-card">
          <span>Columns</span>
          <strong>{result.column_count ?? "—"}</strong>
          <small>Preview is bounded</small>
        </article>
        <article className="metric-card metric-card-wide">
          <span>Recognized analytes</span>
          <strong>{result.recognized_analytes.length}</strong>
          <small>
            {result.recognized_analytes
              .slice(0, 8)
              .map((item) => item.canonical)
              .join(" · ") || "No safe mappings yet"}
          </small>
        </article>
      </div>
      {report.issues.length > 0 && (
        <section className="issue-panel" aria-labelledby="issues-title">
          <h2 id="issues-title">Review needed</h2>
          <ul>
            {report.issues.map((item) => (
              <li key={`${item.code}-${item.field ?? "general"}`}>
                <strong>{item.code}</strong> {item.message}
              </li>
            ))}
          </ul>
        </section>
      )}
      {result.preview && (
        <section className="preview-panel" aria-labelledby="preview-title">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">BOUNDED PREVIEW</p>
              <h2 id="preview-title">Data preview</h2>
            </div>
            <span>30 rows × 40 columns maximum</span>
          </div>
          <div className="table-scroll" tabIndex={0}>
            <table>
              <thead>
                <tr>
                  {result.preview.columns.map((column) => (
                    <th key={column}>{column}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.preview.rows.map((row, rowIndex) => (
                  <tr key={rowIndex}>
                    {row.map((value, columnIndex) => (
                      <td key={columnIndex}>{value == null ? "—" : String(value)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="preview-card-view" aria-label="Responsive data preview">
            {result.preview.rows.map((row, rowIndex) => (
              <article className="preview-record" key={rowIndex}>
                <h3>Preview record {rowIndex + 1}</h3>
                <dl>
                  {result.preview?.columns.map((column, columnIndex) => (
                    <div key={`${column}-${columnIndex}`}>
                      <dt>{column}</dt>
                      <dd>{row[columnIndex] == null ? "—" : String(row[columnIndex])}</dd>
                    </div>
                  ))}
                </dl>
              </article>
            ))}
          </div>
          <p className="preview-notice">{result.preview.notice}</p>
        </section>
      )}
    </section>
  );
}
