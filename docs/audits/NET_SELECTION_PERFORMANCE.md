# Net selection search performance

The shared net picker keeps case-insensitive literal substring matching as its
default. `*` and `?` enable wildcard matching while square brackets stay
literal, so `DATA[0]` names one bus bit and `DATA[*]` searches the bits. Prefix
`~` to request ranked, typo-tolerant suggestions. Search only filters choices;
it does not create assignments, and an existing exact selection remains
available when it does not match the query. Checked multi-selection keeps its
original item identities while the visible rows change.

Fuzzy suggestions use deterministic q-gram ranking followed by edit-distance
scoring. To keep large inventories responsive, the scorer examines at most 512
q-gram candidates and returns at most 100 suggestions. Queries over 96
characters, labels over 512 characters, and work beyond a 25-million-cell
budget are bounded. This is a shortlist: a best typo match outside the q-gram
candidate limit can be omitted in very dense or repetitive inventories.

On Windows with KiCad 10.0 / Python 3.11.5, a synthetic inventory of 10,000
long hierarchical names (`/Project/Board/Controller/ChannelN/NET_NNNNN_CLK`)
was measured with `SearchIndex` construction outside the timed query. For
`~NET_09998_CLK`, the intended typo target ranked first among 100 suggestions.
Before candidate scoring was capped and q-gram construction made lazy, the
first query took 943 ms and repeated queries averaged 746 ms. Afterward, index
construction took 0.91 ms, the first fuzzy query took 76.63 ms, and repeated
queries averaged 29.61 ms. Literal and wildcard searches in the same 10k list
averaged 0.47 ms and 0.94 ms respectively.

Focused shared-helper tests passed 21/21. Native KiCad tests passed 34/34 for
Quick PI inspector, workspace, field style, multisink, redraw/search/scope,
batch, auto-mesh, Sankey, electrothermal, board rendering and view scope. The
native modal hidden-check picker passed separately (1/1). These timings use a
synthetic list, not a real user's project inventory.
