// Start screen for new learners (docs/gui.md §1).

// Typical path for a beginner: [title, what the learner discovers]. Each must fit one line.
const PATH = [
  ["Closed Loop", "Current flows only around a complete loop"],
  ["Measuring Voltage", "A voltmeter goes across a part"],
  ["Measuring Current", "An ammeter goes in the loop"],
  ["Ohm's Law", "Current, voltage and resistance are linked"],
  ["Series Circuits", "Resistances add up; current stays the same"],
  ["Parallel Circuits", "Each branch gets the full voltage"],
  ["Power and Safety", "Too little resistance means too much heat"],
  ["Troubleshooting", "Find the fault by measuring"],
];

// Small inline icons (currentColor), so they look the same on every system.
const Bolt = () => (
  <svg className="icon bolt" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M13 2 4 14h7l-1 8 9-12h-7z" fill="currentColor" />
  </svg>
);
const Lock = () => (
  <svg className="icon lock" viewBox="0 0 24 24" aria-hidden="true">
    <rect x="5" y="11" width="14" height="10" rx="2" fill="currentColor" />
    <path d="M8 11V8a4 4 0 0 1 8 0v3" fill="none" stroke="currentColor" strokeWidth="2" />
  </svg>
);

export default function StartScreen({ onStart }) {
  return (
    <main className="start">
      <div className="start-card">
        <h1>Schematics AI Tutor</h1>
        <p className="lead">
          Learn electronics by building real circuits, experimenting with components, and discovering how
          electricity works — with an AI tutor guiding you along the way.
        </p>

        <section>
          <h2>Your Learning Path</h2>
          <ol className="path">
            {PATH.map(([title, discovery], i) => (
              <li key={title} className={i === 0 ? "current" : "locked"}>
                {i === 0 ? <Bolt /> : <Lock />}
                <span className="step">{title}</span>
                <span className="discovery">{discovery}</span>
              </li>
            ))}
          </ol>
          <p className="note">Tasks adapt to you, so your path may differ.</p>
        </section>

        <div className="start-action">
          <button className="primary large" onClick={onStart}>
            Start Learning
          </button>
        </div>
      </div>
    </main>
  );
}
