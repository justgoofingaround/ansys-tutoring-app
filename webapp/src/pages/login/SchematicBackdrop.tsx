/** The left login panel's artwork: the course's own first problem, precisely
 * drafted — tut1's 3D bar under tension. Fixed-support hatching, force arrow,
 * dimension lines, faint drafting grid. Inline SVG, zero assets. */
export function SchematicBackdrop() {
  return (
    <svg
      viewBox="0 0 560 720"
      className="h-full w-full"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden
    >
      <defs>
        <pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse">
          <path d="M 28 0 L 0 0 0 28" fill="none" stroke="white" strokeOpacity="0.06" strokeWidth="1" />
        </pattern>
        <pattern id="hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="8" stroke="white" strokeOpacity="0.55" strokeWidth="1.5" />
        </pattern>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#B678E8" />
        </marker>
        <marker id="dim" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="white" fillOpacity="0.45" />
        </marker>
      </defs>

      {/* drafting grid */}
      <rect width="560" height="720" fill="url(#grid)" />

      {/* ── the bar, elevation view ── */}
      <g transform="translate(70, 270)">
        {/* fixed support wall + hatching */}
        <rect x="-26" y="-52" width="26" height="164" fill="url(#hatch)" />
        <line x1="0" y1="-52" x2="0" y2="112" stroke="white" strokeOpacity="0.8" strokeWidth="2" />

        {/* bar body */}
        <rect x="0" y="0" width="330" height="60" fill="none" stroke="white" strokeOpacity="0.75" strokeWidth="2" />
        {/* centerline */}
        <line x1="-14" y1="30" x2="352" y2="30" stroke="white" strokeOpacity="0.35" strokeWidth="1" strokeDasharray="14 5 3 5" />

        {/* force arrow */}
        <line x1="334" y1="30" x2="428" y2="30" stroke="#B678E8" strokeWidth="2.5" markerEnd="url(#arrow)" />
        <text x="372" y="14" fill="#CDA9EF" fontFamily="IBM Plex Mono, monospace" fontSize="15" textAnchor="middle">
          F = 3000 lbf
        </text>

        {/* length dimension */}
        <g stroke="white" strokeOpacity="0.45" strokeWidth="1">
          <line x1="0" y1="76" x2="0" y2="102" />
          <line x1="330" y1="76" x2="330" y2="102" />
          <line x1="4" y1="92" x2="326" y2="92" markerStart="url(#dim)" markerEnd="url(#dim)" />
        </g>
        <text x="165" y="116" fill="white" fillOpacity="0.6" fontFamily="IBM Plex Mono, monospace" fontSize="13" textAnchor="middle">
          L = 30 in
        </text>
      </g>

      {/* ── section view (circle) ── */}
      <g transform="translate(150, 500)">
        <circle cx="0" cy="0" r="46" fill="none" stroke="white" strokeOpacity="0.7" strokeWidth="2" />
        {/* center mark */}
        <line x1="-56" y1="0" x2="56" y2="0" stroke="white" strokeOpacity="0.3" strokeWidth="1" strokeDasharray="10 4 2 4" />
        <line x1="0" y1="-56" x2="0" y2="56" stroke="white" strokeOpacity="0.3" strokeWidth="1" strokeDasharray="10 4 2 4" />
        {/* radius */}
        <line x1="0" y1="0" x2="33" y2="-33" stroke="white" strokeOpacity="0.55" strokeWidth="1.2" markerEnd="url(#dim)" />
        <text x="58" y="-40" fill="white" fillOpacity="0.6" fontFamily="IBM Plex Mono, monospace" fontSize="13">
          r = 0.5 in
        </text>
        <text x="0" y="78" fill="white" fillOpacity="0.45" fontFamily="IBM Plex Mono, monospace" fontSize="12" textAnchor="middle">
          SECTION A–A
        </text>
      </g>

      {/* material note */}
      <g fontFamily="IBM Plex Mono, monospace" fontSize="12" fill="white" fillOpacity="0.5">
        <text x="320" y="472">STEEL</text>
        <text x="320" y="492">E  = 30e6 psi</text>
        <text x="320" y="512">nu = 0.27</text>
        <text x="320" y="544" fillOpacity="0.65" fill="#CDA9EF">
          δ ≈ 0.00382 in
        </text>
      </g>

      {/* title block line */}
      <line x1="40" y1="150" x2="520" y2="150" stroke="white" strokeOpacity="0.18" strokeWidth="1" />
      <text x="40" y="128" fill="white" fillOpacity="0.5" fontFamily="IBM Plex Mono, monospace" fontSize="12" letterSpacing="2">
        TUT-1 · ELONGATION OF A 3D BAR UNDER TENSION
      </text>
    </svg>
  );
}
