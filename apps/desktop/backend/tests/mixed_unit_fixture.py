from __future__ import annotations

from pathlib import Path

import pandas as pd


MIXED_MAJOR_ANALYTES = (
    "SiO2", "TiO2", "Al2O3", "Fe2O3T", "MnO", "MgO", "CaO", "Na2O",
    "K2O", "P2O5", "LOI", "Total",
)
MIXED_TRACE_ANALYTES = (
    "Sc", "V", "Co", "Ni", "Cu", "Zn", "Ga", "Ge", "Rb", "Sr", "Y",
    "Zr", "Nb", "Cs", "Ba", "La", "Ce", "Pr", "Nd", "Sm", "Eu",
    "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta",
    "Pb", "Th", "U", "Mo",
)


def write_mixed_unit_transposed_workbook(path: Path) -> None:
    """Write the public, synthetic equivalent of the observed mixed-unit shape."""
    rows: list[list[object]] = [
        ["Rock type", "Synthetic A", "Synthetic B"],
        ["Sample No.", "SYN-A", "SYN-B"],
        ["Major element (wt.%)", None, None],
    ]
    rows.extend(
        [canonical, float(index + 1), float(index + 2)]
        for index, canonical in enumerate(MIXED_MAJOR_ANALYTES)
    )
    rows.append(["Trace element (ppm)", None, None])
    rows.extend(
        [canonical, float(index + 1), float(index + 2)]
        for index, canonical in enumerate(MIXED_TRACE_ANALYTES)
    )
    pd.DataFrame(rows).to_excel(
        path, sheet_name="Mixed units", header=False, index=False
    )


def mixed_public_contract(result: dict) -> dict:
    """Keep only stable fields consumed by the frontend contract fixture."""
    return {
        "recognized_analytes": result["recognized_analytes"],
        "mapping_suggestions": result["mapping_suggestions"],
        "quality": {
            "unknown_unit_count": result["quality"]["unknown_unit_count"],
            "unit_conflict_count": result["quality"]["unit_conflict_count"],
        },
        "layout": result["source"]["layout"],
        "candidate_states": {
            item["diagram"]: item["state"] for item in result["figure_candidates"]
        },
    }
