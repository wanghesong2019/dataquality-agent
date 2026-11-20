// d3-transition monkey-patches d3-selection.prototype.transition as a module
// side-effect. mermaid's flowchart tooltips call selection.transition(), but
// mermaid only imports `select` from the `d3` umbrella package, so bundlers
// drop d3-transition's side-effect and the runtime throws
// "tooltipElem.transition is not a function". Importing it here forces the
// patch to run before any diagram renders.
import 'd3-transition';
