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

export default function StartScreen({ onStart }) {
  return (
    <main className="start">
      <h1>Schematics AI Tutor</h1>
      <p className="lead">
        Learn how electric circuits work by building them. An AI tutor watches and helps you think.
      </p>

      <section>
        <ul>
          <li>Build circuits on the grid from parts and wires.</li>
          <li>Watch live meter readings as you change the circuit.</li>
          <li>Get nudges and questions from the tutor: never the answer.</li>
        </ul>
      </section>

      <section>
        <h2>Your Learning Path</h2>
        <ol className="path">
          {PATH.map(([title, discovery]) => (
            <li key={title}>
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
    </main>
  );
}
