// Start screen for new learners (docs/gui.md §1).

const PATH = ["Closed loop", "Ohm's law", "Voltage divider", "Measuring", "Parallel circuits"];

export default function StartScreen({ onStart }) {
  return (
    <main className="start">
      <h1>Schematics AI Tutor</h1>
      <p className="lead">
        Learn how electric circuits work by building them. An AI tutor watches and helps you think.
      </p>

      <section>
        <h2>How it works</h2>
        <ul>
          <li>Build circuits on the grid from parts and wires.</li>
          <li>Watch live meter readings as you change the circuit.</li>
          <li>Get nudges and questions from the tutor: never the answer.</li>
        </ul>
      </section>

      <section>
        <h2>A typical learning path</h2>
        <ol className="path">
          {PATH.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
        <p className="note">Tasks adapt to you, so your path may differ.</p>
      </section>

      <button className="primary large" onClick={onStart}>
        Start learning
      </button>
    </main>
  );
}
