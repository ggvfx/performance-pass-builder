"""
The Layer Stack.

Combining layers into one picture, in the order the artist put them. Knows
nothing about what made any of them: a new pass is a module in
`performance/` and does not touch this package.

`composite/` may not import `performance/`. A compositor taking a dependency
on a pass is the exact mistake this structure exists to prevent.
"""
