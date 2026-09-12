# Desktop inspect contract fixtures

`mixed-unit-inspect.json` is generated from a real source-mode desktop
bridge invocation over the synthetic transposed workbook created by
`backend/tests/test_bridge_contract.py`.  The paired Python test regenerates
and compares this stable public-contract projection so the frontend does not
maintain an independent hand-authored analyte schema.
