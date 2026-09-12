import { describe, expect, it } from "vitest";

import { validateInspectReport } from "../src/lib/backend";
import mixedInspect from "./fixtures/mixed-unit-inspect.json";

function inspectWith(recognized_analytes: unknown) {
  return { result: { recognized_analytes } };
}

describe("desktop inspect runtime contract", () => {
  it("accepts the source-mode bridge golden records", () => {
    expect(() => validateInspectReport(inspectWith(mixedInspect.recognized_analytes))).not.toThrow();
  });

  it("rejects a non-array analyte collection", () => {
    expect(() => validateInspectReport(inspectWith({}))).toThrow(
      /Desktop bridge returned an invalid inspect contract.*must be an array/,
    );
  });

  it("rejects missing and empty canonical values", () => {
    const valid = mixedInspect.recognized_analytes[0];
    expect(() => validateInspectReport(inspectWith([{ ...valid, canonical: undefined }]))).toThrow(
      /canonical must be a non-empty string/,
    );
    expect(() => validateInspectReport(inspectWith([{ ...valid, canonical: "  " }]))).toThrow(
      /canonical must be a non-empty string/,
    );
  });

  it("preserves a legitimate duplicate canonical when source identities differ", () => {
    const valid = mixedInspect.recognized_analytes[0];
    const duplicateCanonical = [
      valid,
      { ...valid, source_column: `${valid.source_column}_replicate`, source_label: `${valid.source_label}_replicate` },
    ];
    expect(() => validateInspectReport(inspectWith(duplicateCanonical))).not.toThrow();
  });
});
