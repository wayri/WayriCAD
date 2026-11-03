# WayriCAD 4.1.2

The Quick PI series editor now fits the display work area. At high display
scaling, its previous minimum-content sizing could extend below the screen and
hide Load path, Save path, Run and Cancel. Inputs now scroll inside the dialog;
these actions remain outside the scrolling area and visible at the bottom.

Series topology, parallel models, pad groups and numerical calculations are
unchanged. The complete-path result views introduced in 4.1.1 remain available.

A native wx regression constrains the display work area and checks that every
footer action remains reachable while overflowing content scrolls.
