# Unqualified workflow fixture

This synthetic board is for trying the workspace/area workflow, NOT fabrication.
It has a 4×4 illustrative BGA, an attached linear-courtyard area, inside and
boundary-crossing tracks, and a via. Dimensions are examples, not recommendations.
There are intentional shorts/unconnected or rule-violating objects; do not expect
a zero-violation native DRC result. The file has been parsed by this plugin but
NOT loaded or checked by native KiCad in the delivery environment.

Open an independent copy. Try the scope worksheet, use A/B preview, compare with
native DRC and move/rotate/flip in KiCad. Save and reopen the plugin afterward.
Do not interpret a synthetic pure-core fixture as native acceptance evidence.
